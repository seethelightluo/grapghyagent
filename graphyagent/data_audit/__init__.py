"""Evidence-first data quality audit helpers.

The audit pipeline follows ``deep-research-report.md``: local detectors emit
structured evidence, evidence is normalized into record labels, and narrative
summaries should be generated only from the structured facts in
``llm_summary_input``.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}

QUALITY_DIMENSIONS = {
    "schema_integrity": {"schema_violation", "missing_critical"},
    "uniqueness_and_leakage": {"exact_duplicate", "near_duplicate", "leakage_risk"},
    "text_and_synthetic_signals": {"templated_text", "synthetic_likely"},
    "statistical_forensics": {"digit_anomaly", "stat_inconsistency"},
    "label_quality": {"label_suspect"},
    "task_representativeness": {"distribution_mismatch"},
    "provenance_and_metadata": {"provenance_gap"},
    "general_outliers": {"outlier_needs_review"},
}

TAG_ACTIONS = {
    "schema_violation": "quarantine_batch",
    "missing_critical": "quarantine_batch",
    "exact_duplicate": "deduplicate",
    "near_duplicate": "deduplicate",
    "templated_text": "human_forensic_review",
    "label_suspect": "relabel_review",
    "distribution_mismatch": "resample_or_recollect",
    "digit_anomaly": "human_forensic_review",
    "stat_inconsistency": "human_forensic_review",
    "synthetic_likely": "human_forensic_review",
    "outlier_needs_review": "sample_review",
    "provenance_gap": "collect_missing_metadata",
    "leakage_risk": "quarantine_batch",
}

TAG_REVIEW_STEPS = {
    "schema_violation": ["Compare source schema and field-level constraints.", "Fix parser or quarantine invalid records."],
    "missing_critical": ["Confirm whether missing placeholders are valid.", "Backfill or reject records missing critical fields."],
    "exact_duplicate": ["Inspect duplicate source ids and import batches.", "Deduplicate before training or evaluation."],
    "near_duplicate": ["Review candidate pairs and source pages.", "Tune similarity thresholds against a trusted reference batch."],
    "templated_text": ["Inspect template clusters and boilerplate rules.", "Whitelist legitimate templates or remove synthetic boilerplate."],
    "label_suspect": ["Route records to relabel review.", "Compare label policy against feature duplicates/conflicts."],
    "distribution_mismatch": ["Compare against declared target distribution.", "Resample, recollect, or document intentional stratification."],
    "digit_anomaly": ["Check rounding, pricing, quantization, and instrument protocols.", "Run field-specific reference-batch calibration."],
    "stat_inconsistency": ["Recompute statistical summaries from raw records.", "Inspect reporting/selection rules before alleging manipulation."],
    "synthetic_likely": ["Require at least two independent evidence families before escalation.", "Check provenance, generator logs, watermarks, and benign explanations."],
    "outlier_needs_review": ["Sample records for manual review.", "Decide whether the outlier pattern is task-relevant."],
    "provenance_gap": ["Collect source, version, collection date, and synthetic disclosure metadata.", "Treat fit-for-task conclusions as limited until provenance is complete."],
    "leakage_risk": ["Compare against benchmark/test/service samples.", "Remove overlaps before training or evaluation."],
}

TAG_BENIGN_EXPLANATIONS = {
    "digit_anomaly": ["pricing suffixes", "instrument quantization", "rounding policy", "unit conversion"],
    "templated_text": ["legitimate boilerplate", "form-generated text", "legal footer/header"],
    "near_duplicate": ["valid repeated cases", "deduplicated source not yet applied"],
    "synthetic_likely": ["simulation output", "templated data generation disclosed in provenance"],
    "distribution_mismatch": ["intentional stratified sampling", "balanced benchmark construction"],
    "stat_inconsistency": ["format parsing issue", "dependent p-values", "non-comparable study subsets"],
}

LLM_PHRASES = (
    "as an ai language model",
    "i cannot assist",
    "i do not have access",
    "it is important to note",
    "it is worth noting",
    "in conclusion",
    "overall,",
    "to summarize",
    "based on the information provided",
    "here are some",
    "here is a",
    "certainly!",
    "i hope this helps",
    "综上",
    "总之",
    "需要注意的是",
    "值得注意的是",
    "作为一个人工智能",
    "以下是",
)

SYNTHETIC_SOURCE_TERMS = (
    "synthetic",
    "generated",
    "llm",
    "gpt",
    "chatgpt",
    "claude",
    "ai-generated",
    "fake",
    "mock",
    "dummy",
    "simulated",
    "fabricated",
    "人工合成",
    "生成",
    "模拟",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "na", "n/a", "null", "none", "nan"}
    return False


def _to_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        out = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if math.isfinite(out):
        return out
    return None


def _looks_numeric(value: Any) -> bool:
    return _to_float(value) is not None


def _normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _word_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text.lower())


def _template_key(value: Any) -> str:
    text = _normalize_text(value)
    text = re.sub(r"https?://\S+", "<url>", text)
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.\w+\b", "<email>", text)
    text = re.sub(r"\b[0-9a-f]{8,}\b", "<hex>", text)
    text = re.sub(r"\b\d{4}-\d{1,2}-\d{1,2}(?:[ t]\d{1,2}:\d{2}(?::\d{2})?)?\b", "<date>", text)
    text = re.sub(r"\b\d{1,2}[:：]\d{2}(?::\d{2})?\b", "<time>", text)
    text = re.sub(r"\b[a-z]{1,6}[-_ ]?\d{2,}\b", "<id>", text)
    text = re.sub(r"\b\d+(?:[.,]\d+)?\b", "<num>", text)
    return text


def _shape_key(value: Any) -> str:
    text = _normalize_text(value)
    text = re.sub(r"[a-z]+", "a", text)
    text = re.sub(r"\d+", "0", text)
    text = re.sub(r"[\u4e00-\u9fff]+", "中", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _fingerprint_record(row: dict[str, Any], exclude: set[str] | None = None) -> str:
    exclude = exclude or set()
    items = [
        (str(k), _normalize_text(v))
        for k, v in sorted(row.items())
        if str(k) not in exclude
    ]
    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _last_two_decimal_digits(value: Any) -> int | None:
    if _is_missing(value):
        return None
    text = str(value).strip().replace(",", "")
    try:
        number = Decimal(text).copy_abs().quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    return int(number * 100) % 100


def _first_significant_digit(value: Any) -> int | None:
    number = _to_float(value)
    if number is None or number == 0:
        return None
    number = abs(number)
    while 0 < number < 1:
        number *= 10
    while number >= 10:
        number /= 10
    digit = int(number)
    return digit if 1 <= digit <= 9 else None


def _column_values(rows: list[dict[str, Any]], column: str) -> list[Any]:
    return [row.get(column) for row in rows]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _coefficient_of_variation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    if mean == 0:
        return None
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance) / abs(mean)


def _char_shingles(text: str, k: int = 5) -> set[str]:
    clean = re.sub(r"\s+", " ", text)
    if len(clean) <= k:
        return {clean} if clean else set()
    return {clean[i : i + k] for i in range(len(clean) - k + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _try_parse_datetime(value: Any) -> datetime | None:
    if _is_missing(value):
        return None
    text = str(value).strip()
    normalized = text.replace("Z", "+00:00")
    for candidate in (
        normalized,
        normalized.replace(" ", "T"),
    ):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass
    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%m/%d/%Y",
        "%m/%d/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


@dataclass
class AuditEvidence:
    evidence_id: str
    detector: str
    tag: str
    severity: str
    confidence: float
    scope: str
    message: str
    record_indices: list[int] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    applicability: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "detector": self.detector,
            "tag": self.tag,
            "severity": self.severity,
            "confidence": round(float(self.confidence), 4),
            "scope": self.scope,
            "message": self.message,
            "record_indices": list(self.record_indices),
            "columns": list(self.columns),
            "details": dict(self.details),
            "applicability": dict(self.applicability),
        }


class DataAudit:
    def __init__(self, rows: list[dict[str, Any]], metadata: dict[str, Any] | None = None):
        self.rows = rows
        self.metadata = metadata or {}
        self.schema = self.metadata.get("schema") or {}
        self.fields = self._normalize_fields(self.schema.get("fields") or {})
        self.primary_key = [str(c) for c in _as_list(self.schema.get("primary_key"))]
        self.task_spec = self.metadata.get("task_spec") or self.metadata.get("task") or {}
        self.target_distribution = self.metadata.get("target_distribution") or {}
        self.provenance = self.metadata.get("provenance") or {}
        self.validation_context = self.metadata.get("validation_context") or self.metadata.get("validation") or {}
        self.evidence: list[AuditEvidence] = []
        self.record_tags: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self.detector_notes: dict[str, list[dict[str, Any]]] = defaultdict(list)

    @staticmethod
    def _normalize_fields(raw_fields: dict[str, Any]) -> dict[str, dict[str, Any]]:
        fields: dict[str, dict[str, Any]] = {}
        for name, spec in raw_fields.items():
            if isinstance(spec, str):
                fields[str(name)] = {"type": spec}
            elif isinstance(spec, dict):
                fields[str(name)] = dict(spec)
            else:
                fields[str(name)] = {}
        return fields

    @property
    def columns(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for row in self.rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    out.append(key)
        for key in self.fields:
            if key not in seen:
                out.append(key)
        return out

    def run(self) -> dict[str, Any]:
        self._audit_metadata_presence()
        self._audit_schema()
        self._audit_duplicates()
        self._audit_leakage_and_contamination()
        self._audit_label_conflicts()
        self._audit_text_artifacts()
        self._audit_digit_patterns()
        self._audit_benford()
        self._audit_pvalues()
        self._audit_target_distribution()
        self._audit_task_coverage()
        self._audit_distribution_uniformity()
        self._audit_sequence_patterns()
        self._audit_missingness_patterns()
        self._audit_synthetic_fusion()
        return self._build_report()

    def _record_detector_note(
        self,
        detector: str,
        *,
        applicable: bool,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.detector_notes[detector].append({
            "applicable": applicable,
            "reason": reason,
            "details": details or {},
        })

    def _add_evidence(
        self,
        detector: str,
        tag: str,
        severity: str,
        confidence: float,
        scope: str,
        message: str,
        *,
        record_indices: Iterable[int] = (),
        columns: Iterable[str] = (),
        details: dict[str, Any] | None = None,
        applicability: dict[str, Any] | None = None,
    ) -> AuditEvidence:
        evidence_id = f"E{len(self.evidence) + 1:04d}"
        item = AuditEvidence(
            evidence_id=evidence_id,
            detector=detector,
            tag=tag,
            severity=severity,
            confidence=confidence,
            scope=scope,
            message=message,
            record_indices=list(record_indices),
            columns=list(columns),
            details=details or {},
            applicability=applicability or {"applicable": True},
        )
        self.evidence.append(item)
        for idx in item.record_indices:
            self._tag_record(idx, tag, severity, confidence, evidence_id, item.applicability)
        return item

    def _tag_record(
        self,
        index: int,
        tag: str,
        severity: str,
        confidence: float,
        evidence_id: str,
        applicability: dict[str, Any] | None = None,
    ) -> None:
        tag_applicability = dict(applicability or {"applicable": True})
        existing = next(
            (entry for entry in self.record_tags[index] if entry["tag"] == tag),
            None,
        )
        if existing:
            existing["confidence"] = max(existing["confidence"], round(confidence, 4))
            if SEVERITY_RANK[severity] > SEVERITY_RANK[existing["severity"]]:
                existing["severity"] = severity
            existing["evidence_refs"].append(evidence_id)
            existing.setdefault("applicability_refs", {})[evidence_id] = tag_applicability
            existing["applicability"] = {
                "applicable": bool(existing.get("applicability", {}).get("applicable", True))
                and bool(tag_applicability.get("applicable", True)),
                "source": "evidence_refs",
            }
            return
        self.record_tags[index].append({
            "tag": tag,
            "severity": severity,
            "confidence": round(confidence, 4),
            "applicability": {
                "applicable": bool(tag_applicability.get("applicable", True)),
                "source": "evidence_refs",
            },
            "applicability_refs": {evidence_id: tag_applicability},
            "evidence_refs": [evidence_id],
        })

    def _audit_metadata_presence(self) -> None:
        self._record_detector_note(
            "metadata",
            applicable=True,
            reason="metadata presence and provenance disclosure checks are always evaluated",
            details={
                "has_schema_fields": bool(self.fields),
                "has_task_spec": bool(self.task_spec),
                "has_target_distribution": bool(self.target_distribution),
                "has_provenance": bool(self.provenance),
                "has_validation_context": bool(self.validation_context),
            },
        )
        missing = []
        if not self.fields:
            missing.append("schema.fields")
        if not self.task_spec:
            missing.append("task_spec")
        if not self.provenance:
            missing.append("provenance")
        else:
            provenance_keys = {str(key).lower() for key in self.provenance}
            if not provenance_keys & {"source", "source_system", "collector", "data_source"}:
                missing.append("provenance.source")
            if not provenance_keys & {"version", "dataset_version", "collection_date", "created_at"}:
                missing.append("provenance.version_or_collection_date")
            if not provenance_keys & {"synthetic_policy", "contains_synthetic", "generation_process"}:
                missing.append("provenance.synthetic_disclosure")
        if missing:
            self._add_evidence(
                "metadata",
                "provenance_gap",
                "high" if "provenance" in missing else "medium",
                0.9,
                "dataset",
                "Audit metadata is incomplete; conclusions must be treated as limited.",
                details={"missing": missing, "detector_family": "provenance"},
                applicability={"applicable": True, "required_for_high_confidence": True},
            )

        source_like_cols = [
            col for col in self.columns
            if any(term in col.lower() for term in ("source", "origin", "generator", "created_by", "provenance"))
            or str(self.fields.get(col, {}).get("role", "")).lower() == "provenance"
        ]
        for column in source_like_cols:
            values = [
                (idx, _normalize_text(row.get(column)))
                for idx, row in enumerate(self.rows)
                if not _is_missing(row.get(column))
            ]
            synthetic_hits = [
                idx for idx, value in values
                if any(term in value for term in SYNTHETIC_SOURCE_TERMS)
            ]
            if synthetic_hits and len(synthetic_hits) / max(1, len(values)) >= 0.1:
                self._add_evidence(
                    "metadata",
                    "synthetic_likely",
                    "high",
                    min(0.95, 0.65 + len(synthetic_hits) / max(1, len(values))),
                    "record",
                    f"Column '{column}' contains source/provenance values that disclose synthetic or generated data.",
                    record_indices=synthetic_hits,
                    columns=[column],
                    details={
                        "count": len(synthetic_hits),
                        "rate": round(len(synthetic_hits) / max(1, len(values)), 4),
                        "detector_family": "provenance",
                    },
                )

    def _audit_schema(self) -> None:
        self._record_detector_note(
            "schema",
            applicable=bool(self.fields),
            reason="declared schema.fields found" if self.fields else "schema.fields_not_declared",
            details={"field_count": len(self.fields)},
        )
        for column, spec in self.fields.items():
            missing_indices = [
                idx for idx, row in enumerate(self.rows)
                if column not in row or _is_missing(row.get(column))
            ]
            if missing_indices and spec.get("required", False):
                severity = "critical" if spec.get("critical", True) else "high"
                self._add_evidence(
                    "schema",
                    "missing_critical",
                    severity,
                    0.98,
                    "record",
                    f"Required column '{column}' is missing or empty.",
                    record_indices=missing_indices,
                    columns=[column],
                    details={"count": len(missing_indices), "detector_family": "schema"},
                )

            expected_type = str(spec.get("type", "")).lower()
            if expected_type:
                bad_indices = [
                    idx for idx, row in enumerate(self.rows)
                    if not _is_missing(row.get(column))
                    and not self._matches_type(row.get(column), expected_type)
                ]
                if bad_indices:
                    self._add_evidence(
                        "schema",
                        "schema_violation",
                        "critical",
                        0.98,
                        "record",
                        f"Column '{column}' has values outside declared type '{expected_type}'.",
                        record_indices=bad_indices,
                        columns=[column],
                        details={
                            "count": len(bad_indices),
                            "expected_type": expected_type,
                            "detector_family": "schema",
                        },
                    )

            enum_values = spec.get("enum") or spec.get("allowed_values")
            if enum_values:
                allowed = {str(v) for v in enum_values}
                bad_indices = [
                    idx for idx, row in enumerate(self.rows)
                    if not _is_missing(row.get(column)) and str(row.get(column)) not in allowed
                ]
                if bad_indices:
                    self._add_evidence(
                        "schema",
                        "schema_violation",
                        "critical",
                        0.98,
                        "record",
                        f"Column '{column}' contains values outside the allowed domain.",
                        record_indices=bad_indices,
                        columns=[column],
                        details={
                            "count": len(bad_indices),
                            "allowed_values": sorted(allowed),
                            "detector_family": "schema",
                        },
                    )

            numeric_values = [
                (idx, _to_float(row.get(column)))
                for idx, row in enumerate(self.rows)
                if not _is_missing(row.get(column))
            ]
            numeric_values = [(idx, val) for idx, val in numeric_values if val is not None]
            bad_range = []
            if "min" in spec:
                bad_range.extend(idx for idx, val in numeric_values if val < float(spec["min"]))
            if "max" in spec:
                bad_range.extend(idx for idx, val in numeric_values if val > float(spec["max"]))
            if bad_range:
                self._add_evidence(
                    "schema",
                    "schema_violation",
                    "critical",
                    0.98,
                    "record",
                    f"Column '{column}' contains values outside declared numeric range.",
                    record_indices=sorted(set(bad_range)),
                    columns=[column],
                    details={
                        "count": len(set(bad_range)),
                        "min": spec.get("min"),
                        "max": spec.get("max"),
                        "detector_family": "schema",
                    },
                )

        key_cols = self.primary_key or [
            col for col, spec in self.fields.items() if spec.get("primary_key") or spec.get("unique")
        ]
        for cols in ([key_cols] if key_cols else []):
            seen: dict[tuple[Any, ...], int] = {}
            dup_indices: list[int] = []
            for idx, row in enumerate(self.rows):
                key = tuple(row.get(col) for col in cols)
                if any(_is_missing(v) for v in key):
                    continue
                if key in seen:
                    dup_indices.extend([seen[key], idx])
                else:
                    seen[key] = idx
            if dup_indices:
                self._add_evidence(
                    "schema",
                    "exact_duplicate",
                    "critical",
                    0.99,
                    "record",
                    "Primary key or unique field duplicate detected.",
                    record_indices=sorted(set(dup_indices)),
                    columns=cols,
                    details={
                        "duplicate_record_count": len(set(dup_indices)),
                        "detector_family": "duplicates",
                    },
                )

    @staticmethod
    def _matches_type(value: Any, expected: str) -> bool:
        if expected in {"string", "str", "text", "category", "categorical"}:
            return isinstance(value, str) or value is not None
        if expected in {"number", "numeric", "float", "double", "decimal"}:
            return _looks_numeric(value)
        if expected in {"integer", "int"}:
            number = _to_float(value)
            return number is not None and number.is_integer()
        if expected in {"boolean", "bool"}:
            return str(value).strip().lower() in {"true", "false", "1", "0", "yes", "no", "y", "n"}
        if expected in {"datetime", "date", "timestamp"}:
            return _try_parse_datetime(value) is not None
        return True

    def _audit_duplicates(self) -> None:
        self._record_detector_note(
            "duplicate",
            applicable=True,
            reason="normalized row hashing is available for CSV/JSON/JSONL rows",
            details={"row_count": len(self.rows)},
        )
        exclude = set(self.primary_key)
        fingerprints: dict[str, list[int]] = defaultdict(list)
        for idx, row in enumerate(self.rows):
            fingerprints[_fingerprint_record(row, exclude=exclude)].append(idx)
        duplicate_groups = [indices for indices in fingerprints.values() if len(indices) > 1]
        for group in duplicate_groups[:50]:
            self._add_evidence(
                "duplicate",
                "exact_duplicate",
                "high",
                0.99,
                "record",
                "Normalized record duplicate detected.",
                record_indices=group,
                details={"group_size": len(group), "detector_family": "duplicates"},
            )
        if len(duplicate_groups) > 50:
            self._add_evidence(
                "duplicate",
                "exact_duplicate",
                "high",
                0.95,
                "dataset",
                "More duplicate groups exist than are expanded in record evidence.",
                details={
                    "duplicate_group_count": len(duplicate_groups),
                    "detector_family": "duplicates",
                },
            )

    def _reference_items(self) -> list[dict[str, Any]]:
        if not isinstance(self.validation_context, dict):
            return []
        key_kinds = {
            "benchmark_records": "benchmark",
            "test_records": "test",
            "holdout_records": "test",
            "service_records": "service",
            "reference_records": "reference",
            "benchmark_texts": "benchmark",
            "test_texts": "test",
            "holdout_texts": "test",
            "service_texts": "service",
            "reference_texts": "reference",
        }
        items: list[dict[str, Any]] = []
        for key, kind in key_kinds.items():
            raw = self.validation_context.get(key)
            if isinstance(raw, dict):
                raw = raw.get("records") or raw.get("texts") or raw.get("items")
            if not isinstance(raw, list):
                continue
            for value in raw:
                if isinstance(value, dict):
                    items.append({"kind": kind, "record": value, "source_key": key})
                elif not _is_missing(value):
                    items.append({"kind": kind, "text": str(value), "source_key": key})
        return items

    def _audit_leakage_and_contamination(self) -> None:
        references = self._reference_items()
        if not references:
            self._record_detector_note(
                "leakage",
                applicable=False,
                reason="missing_validation_context_reference_records",
                details={
                    "expected_metadata_keys": [
                        "validation_context.benchmark_records",
                        "validation_context.test_records",
                        "validation_context.reference_records",
                        "validation_context.benchmark_texts",
                    ],
                },
            )
            return

        self._record_detector_note(
            "leakage",
            applicable=True,
            reason="validation_context contains benchmark/test/reference samples",
            details={"reference_item_count": len(references)},
        )

        id_like = self._id_like_columns()
        row_hashes: dict[str, list[int]] = defaultdict(list)
        for idx, row in enumerate(self.rows):
            row_hashes[_fingerprint_record(row, exclude=id_like)].append(idx)

        exact_by_kind: dict[str, set[int]] = defaultdict(set)
        exact_ref_counts: Counter[str] = Counter()
        for ref in references:
            record = ref.get("record")
            if not isinstance(record, dict):
                continue
            fingerprint = _fingerprint_record(record, exclude=id_like)
            matched = row_hashes.get(fingerprint) or []
            if matched:
                kind = str(ref["kind"])
                exact_by_kind[kind].update(matched)
                exact_ref_counts[kind] += 1

        for kind, indices in sorted(exact_by_kind.items()):
            self._add_evidence(
                "leakage",
                "leakage_risk",
                "critical" if kind in {"benchmark", "test"} else "high",
                0.99,
                "record",
                f"Dataset records exactly overlap with {kind} validation or benchmark samples.",
                record_indices=sorted(indices),
                details={
                    "validation_set": kind,
                    "match_type": "normalized_record_hash",
                    "matched_reference_count": int(exact_ref_counts[kind]),
                    "detector_family": "leakage",
                },
                applicability={"applicable": True, "requires": "declared validation_context reference records"},
            )

        text_columns = self._text_columns()
        if not text_columns:
            return

        reference_texts: list[tuple[str, str]] = []
        for ref in references:
            kind = str(ref["kind"])
            if "text" in ref:
                text = _normalize_text(ref.get("text"))
                if text:
                    reference_texts.append((kind, text))
                continue
            record = ref.get("record")
            if not isinstance(record, dict):
                continue
            for column in text_columns:
                text = _normalize_text(record.get(column))
                if text:
                    reference_texts.append((kind, text))
        if not reference_texts:
            return

        for column in text_columns:
            observed = [
                (idx, _normalize_text(row.get(column)))
                for idx, row in enumerate(self.rows)
                if not _is_missing(row.get(column))
            ]
            exact_text_index: dict[str, list[int]] = defaultdict(list)
            for idx, text in observed:
                if text:
                    exact_text_index[text].append(idx)

            exact_text_by_kind: dict[str, set[int]] = defaultdict(set)
            near_text_by_kind: dict[str, set[int]] = defaultdict(set)
            near_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for kind, ref_text in reference_texts[:500]:
                exact_matches = exact_text_index.get(ref_text) or []
                if exact_matches:
                    exact_text_by_kind[kind].update(exact_matches)
                    continue
                ref_shingles = _char_shingles(ref_text)
                for idx, text in observed[:1500]:
                    max_len = max(len(ref_text), len(text))
                    if max_len < 20 or abs(len(ref_text) - len(text)) > max(40, 0.45 * max_len):
                        continue
                    jaccard = _jaccard(ref_shingles, _char_shingles(text))
                    if jaccard < 0.72:
                        continue
                    ratio = SequenceMatcher(None, ref_text, text).ratio()
                    if ratio >= 0.92 or (ratio >= 0.86 and jaccard >= 0.82):
                        near_text_by_kind[kind].add(idx)
                        if len(near_examples[kind]) < 5:
                            near_examples[kind].append({
                                "record_index": idx,
                                "sequence_similarity": round(ratio, 4),
                                "shingle_jaccard": round(jaccard, 4),
                            })
                        if sum(len(values) for values in near_text_by_kind.values()) >= 100:
                            break

            for kind, indices in sorted(exact_text_by_kind.items()):
                self._add_evidence(
                    "leakage",
                    "leakage_risk",
                    "critical" if kind in {"benchmark", "test"} else "high",
                    0.99,
                    "record",
                    f"Column '{column}' exactly overlaps with {kind} validation or benchmark text.",
                    record_indices=sorted(indices),
                    columns=[column],
                    details={
                        "validation_set": kind,
                        "match_type": "exact_text",
                        "detector_family": "leakage",
                    },
                    applicability={"applicable": True, "requires": "declared validation_context reference text"},
                )
            for kind, indices in sorted(near_text_by_kind.items()):
                self._add_evidence(
                    "leakage",
                    "leakage_risk",
                    "critical" if kind in {"benchmark", "test"} else "high",
                    0.9,
                    "record",
                    f"Column '{column}' has near-overlap with {kind} validation or benchmark text.",
                    record_indices=sorted(indices),
                    columns=[column],
                    details={
                        "validation_set": kind,
                        "match_type": "near_duplicate_text",
                        "examples": near_examples[kind],
                        "detector_family": "leakage",
                    },
                    applicability={"applicable": True, "requires": "declared validation_context reference text"},
                )

    def _audit_label_conflicts(self) -> None:
        label_cols = [
            col for col, spec in self.fields.items()
            if str(spec.get("role", "")).lower() == "label" or spec.get("label")
        ]
        if not label_cols:
            self._record_detector_note(
                "label",
                applicable=False,
                reason="no_declared_label_column",
                details={"expected_field_role": "label"},
            )
            return
        self._record_detector_note(
            "label",
            applicable=True,
            reason="declared label column found",
            details={"label_columns": label_cols},
        )
        label_col = label_cols[0]
        feature_cols = [
            col for col in self.columns
            if col != label_col and col not in self.primary_key
            and str(self.fields.get(col, {}).get("role", "")).lower() != "provenance"
        ]
        by_features: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        for idx, row in enumerate(self.rows):
            fingerprint = _fingerprint_record({col: row.get(col) for col in feature_cols})
            by_features[fingerprint][str(row.get(label_col))].append(idx)
        for labels in by_features.values():
            if len(labels) <= 1:
                continue
            indices = sorted(idx for group in labels.values() for idx in group)
            self._add_evidence(
                "label",
                "label_suspect",
                "high",
                0.9,
                "record",
                "Same normalized features appear with conflicting labels.",
                record_indices=indices,
                columns=[label_col],
                details={
                    "label_values": sorted(labels.keys()),
                    "count": len(indices),
                    "detector_family": "label",
                },
            )

    def _text_columns(self) -> list[str]:
        explicit = [
            col for col, spec in self.fields.items()
            if str(spec.get("role", "")).lower() in {"text", "prompt", "document", "response"}
        ]
        if explicit:
            return explicit
        candidates = []
        for col in self.columns:
            values = [str(v) for v in _column_values(self.rows, col) if not _is_missing(v)]
            if not values:
                continue
            numeric_rate = sum(1 for v in values if _looks_numeric(v)) / len(values)
            avg_len = sum(len(v) for v in values) / len(values)
            if numeric_rate < 0.2 and avg_len >= 20:
                candidates.append(col)
        return candidates[:5]

    def _audit_text_artifacts(self) -> None:
        text_columns = self._text_columns()
        self._record_detector_note(
            "text_artifacts",
            applicable=bool(text_columns),
            reason="text-like columns found" if text_columns else "no_text_like_columns",
            details={"text_columns": text_columns},
        )
        for column in text_columns:
            values = [(idx, _normalize_text(row.get(column))) for idx, row in enumerate(self.rows)]
            values = [(idx, text) for idx, text in values if text]
            if len(values) < 2:
                continue

            self._audit_text_templates(column, values)
            self._audit_text_surface_homogeneity(column, values)
            self._audit_text_llm_phrases(column, values)
            self._audit_text_pair_similarity(column, values)

    def _audit_text_templates(self, column: str, values: list[tuple[int, str]]) -> None:
        for detector_name, key_func, family in (
            ("template", _template_key, "text_template"),
            ("shape", _shape_key, "text_shape"),
        ):
            grouped: dict[str, list[int]] = defaultdict(list)
            for idx, text in values:
                key = key_func(text)
                if len(key) >= 20:
                    grouped[key].append(idx)
            for key, indices in sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)[:20]:
                rate = len(indices) / max(1, len(values))
                if len(indices) >= 3 and rate >= 0.1:
                    severity = "critical" if rate >= 0.65 and len(indices) >= 20 else "high"
                    self._add_evidence(
                        "text_artifacts",
                        "templated_text",
                        severity,
                        min(0.98, 0.6 + rate),
                        "record",
                        f"Column '{column}' contains a repeated {detector_name} pattern.",
                        record_indices=indices,
                        columns=[column],
                        details={
                            detector_name: key[:240],
                            "group_size": len(indices),
                            "group_rate": round(rate, 4),
                            "detector_family": family,
                        },
                    )

    def _audit_text_surface_homogeneity(self, column: str, values: list[tuple[int, str]]) -> None:
        if len(values) < 20:
            return
        lengths = [float(len(text)) for _, text in values if len(text) >= 20]
        if len(lengths) >= 20:
            cv = _coefficient_of_variation(lengths)
            unique_rate = len({text for _, text in values}) / len(values)
            if cv is not None and cv <= 0.08 and unique_rate >= 0.5:
                self._add_evidence(
                    "text_artifacts",
                    "templated_text",
                    "medium",
                    min(0.9, 0.75 + (0.08 - cv)),
                    "column",
                    f"Column '{column}' has unusually uniform text lengths.",
                    columns=[column],
                    details={
                        "n": len(lengths),
                        "length_cv": round(cv, 5),
                        "unique_rate": round(unique_rate, 4),
                        "detector_family": "text_homogeneity",
                    },
                )

        sentence_counts = [
            len(re.findall(r"[.!?。！？]", text)) or 1
            for _, text in values
            if len(text) >= 20
        ]
        if len(sentence_counts) >= 20:
            common_count, common_n = Counter(sentence_counts).most_common(1)[0]
            common_rate = common_n / len(sentence_counts)
            if common_rate >= 0.85:
                self._add_evidence(
                    "text_artifacts",
                    "templated_text",
                    "medium",
                    min(0.9, common_rate),
                    "column",
                    f"Column '{column}' has unusually uniform sentence/punctuation structure.",
                    columns=[column],
                    details={
                        "sentence_count": common_count,
                        "common_rate": round(common_rate, 4),
                        "detector_family": "text_homogeneity",
                    },
                )

        starts: Counter[str] = Counter()
        endings: Counter[str] = Counter()
        bigrams: Counter[tuple[str, str]] = Counter()
        token_total = 0
        token_vocab: set[str] = set()
        for _, text in values:
            tokens = _word_tokens(text)
            if len(tokens) >= 5:
                starts[" ".join(tokens[:5])] += 1
                endings[" ".join(tokens[-5:])] += 1
            for pos in range(max(0, len(tokens) - 1)):
                bigrams[(tokens[pos], tokens[pos + 1])] += 1
            token_total += len(tokens)
            token_vocab.update(tokens)

        for label, counter in (("opening", starts), ("closing", endings)):
            if not counter:
                continue
            phrase, count = counter.most_common(1)[0]
            rate = count / len(values)
            if count >= 10 and rate >= 0.35:
                phrase_indices = []
                for idx, text in values:
                    tokens = _word_tokens(text)
                    if len(tokens) < 5:
                        continue
                    current = " ".join(tokens[:5] if label == "opening" else tokens[-5:])
                    if current == phrase:
                        phrase_indices.append(idx)
                self._add_evidence(
                    "text_artifacts",
                    "templated_text",
                    "high" if rate >= 0.55 else "medium",
                    min(0.95, 0.55 + rate),
                    "record",
                    f"Column '{column}' repeats the same {label} phrase across many records.",
                    record_indices=phrase_indices[:500],
                    columns=[column],
                    details={
                        "phrase": phrase,
                        "rate": round(rate, 4),
                        "detector_family": "text_homogeneity",
                    },
                )

        if token_total >= 300 and bigrams:
            top_bigram, top_count = bigrams.most_common(1)[0]
            top_bigram_rate = top_count / max(1, token_total)
            token_diversity = len(token_vocab) / token_total
            if token_diversity <= 0.16 and top_bigram_rate >= 0.03:
                self._add_evidence(
                    "text_artifacts",
                    "templated_text",
                    "medium",
                    min(0.9, 0.7 + top_bigram_rate),
                    "column",
                    f"Column '{column}' has low token diversity with repeated n-grams.",
                    columns=[column],
                    details={
                        "token_total": token_total,
                        "token_diversity": round(token_diversity, 5),
                        "top_bigram": " ".join(top_bigram),
                        "top_bigram_rate": round(top_bigram_rate, 5),
                        "detector_family": "text_homogeneity",
                    },
                )

    def _audit_text_llm_phrases(self, column: str, values: list[tuple[int, str]]) -> None:
        hits: list[int] = []
        phrase_counts: Counter[str] = Counter()
        bullet_like = []
        for idx, text in values:
            hit_phrases = [phrase for phrase in LLM_PHRASES if phrase in text]
            if hit_phrases:
                hits.append(idx)
                phrase_counts.update(hit_phrases)
            if re.search(r"(^|\n)\s*(?:\d+\.|[-*])\s+\S+", text):
                bullet_like.append(idx)
        hit_rate = len(set(hits)) / max(1, len(values))
        if len(set(hits)) >= 3 and hit_rate >= 0.15:
            self._add_evidence(
                "text_artifacts",
                "synthetic_likely",
                "high" if hit_rate >= 0.45 else "medium",
                min(0.95, 0.58 + hit_rate),
                "record",
                f"Column '{column}' contains repeated generic LLM-style phrases.",
                record_indices=sorted(set(hits)),
                columns=[column],
                details={
                    "hit_rate": round(hit_rate, 4),
                    "phrases": phrase_counts.most_common(8),
                    "detector_family": "llm_text",
                },
            )
        bullet_rate = len(bullet_like) / max(1, len(values))
        if len(bullet_like) >= 10 and bullet_rate >= 0.4:
            self._add_evidence(
                "text_artifacts",
                "templated_text",
                "medium",
                min(0.9, 0.55 + bullet_rate),
                "record",
                f"Column '{column}' repeats numbered or bulleted response structure.",
                record_indices=bullet_like,
                columns=[column],
                details={
                    "rate": round(bullet_rate, 4),
                    "detector_family": "llm_text",
                },
            )

    def _audit_text_pair_similarity(self, column: str, values: list[tuple[int, str]]) -> None:
        bounded = values[:350]
        shingles = {idx: _char_shingles(text) for idx, text in bounded}
        emitted = 0
        for pos, (idx_a, text_a) in enumerate(bounded):
            for idx_b, text_b in bounded[pos + 1:]:
                if emitted >= 80:
                    return
                max_len = max(len(text_a), len(text_b))
                if abs(len(text_a) - len(text_b)) > max(40, 0.4 * max_len):
                    continue
                jaccard = _jaccard(shingles[idx_a], shingles[idx_b])
                if jaccard < 0.68:
                    continue
                ratio = SequenceMatcher(None, text_a, text_b).ratio()
                if ratio >= 0.9 or (ratio >= 0.84 and jaccard >= 0.82):
                    emitted += 1
                    self._add_evidence(
                        "text_artifacts",
                        "near_duplicate",
                        "high",
                        min(0.98, max(ratio, jaccard)),
                        "record",
                        f"Column '{column}' has near-duplicate text records.",
                        record_indices=[idx_a, idx_b],
                        columns=[column],
                        details={
                            "sequence_similarity": round(ratio, 4),
                            "shingle_jaccard": round(jaccard, 4),
                            "detector_family": "near_duplicates",
                        },
                    )

    def _numeric_columns(self) -> list[str]:
        explicit = [
            col for col, spec in self.fields.items()
            if str(spec.get("type", "")).lower() in {"number", "numeric", "float", "double", "decimal", "integer", "int"}
            or str(spec.get("role", "")).lower() in {"measure", "metric", "amount"}
        ]
        if explicit:
            return explicit
        candidates = []
        for col in self.columns:
            values = [v for v in _column_values(self.rows, col) if not _is_missing(v)]
            if not values:
                continue
            numeric_rate = sum(1 for v in values if _looks_numeric(v)) / len(values)
            if numeric_rate >= 0.8:
                candidates.append(col)
        return candidates

    def _id_like_columns(self) -> set[str]:
        out = set(self.primary_key)
        for col in self.columns:
            name = col.lower()
            if name == "id" or name.endswith("_id") or name.endswith("id") or "uuid" in name:
                out.add(col)
            spec = self.fields.get(col, {})
            if spec.get("primary_key") or spec.get("unique") or str(spec.get("role", "")).lower() in {"id", "identifier"}:
                out.add(col)
        return out

    def _audit_digit_patterns(self) -> None:
        numeric_cols = self._numeric_columns()
        self._record_detector_note(
            "digits",
            applicable=bool(numeric_cols),
            reason="numeric columns found" if numeric_cols else "no_numeric_columns",
            details={"numeric_columns": numeric_cols},
        )
        suffix_by_col: dict[str, list[tuple[int, int]]] = {}
        min_n = int(self.metadata.get("digit_min_n", 30))
        dominant_warn = float(self.metadata.get("dominant_suffix_warn", 0.45))
        cross_warn = float(self.metadata.get("cross_column_same_suffix_warn", 0.80))

        for column in numeric_cols:
            suffixes = [
                (idx, suffix)
                for idx, row in enumerate(self.rows)
                if (suffix := _last_two_decimal_digits(row.get(column))) is not None
            ]
            suffix_by_col[column] = suffixes
            if len(suffixes) < min_n:
                self._add_evidence(
                    "digits",
                    "digit_anomaly",
                    "low",
                    0.4,
                    "column",
                    f"Column '{column}' has too few numeric values for last-two digit audit.",
                    columns=[column],
                    details={"n": len(suffixes), "min_n": min_n, "detector_family": "digits"},
                    applicability={"applicable": False, "reason": "insufficient_n"},
                )
                continue
            counts = Counter(suffix for _, suffix in suffixes)
            dominant_suffix, dominant_count = counts.most_common(1)[0]
            dominant_rate = dominant_count / len(suffixes)
            expected = len(suffixes) / 100.0
            chi2 = sum(((counts.get(bucket, 0) - expected) ** 2) / expected for bucket in range(100))
            spec = self.fields.get(column, {})
            high_false_positive = bool(
                spec.get("price_like")
                or spec.get("quantized")
                or spec.get("allow_rounding")
                or column in self._id_like_columns()
            )
            chi2_warn = chi2 >= float(self.metadata.get("last_two_digit_chi2_warn", 180.0))
            if (dominant_rate >= dominant_warn or chi2_warn) and not high_false_positive:
                indices = [idx for idx, suffix in suffixes if suffix == dominant_suffix]
                severity = "medium"
                if dominant_rate >= 0.7 or chi2 >= 260:
                    severity = "high"
                self._add_evidence(
                    "digits",
                    "digit_anomaly",
                    severity,
                    min(0.98, max(dominant_rate, 0.55 + min(0.4, chi2 / 1000))),
                    "record" if dominant_rate >= dominant_warn else "column",
                    f"Column '{column}' has suspicious last-two digit distribution.",
                    record_indices=indices if dominant_rate >= dominant_warn else [],
                    columns=[column],
                    details={
                        "n": len(suffixes),
                        "dominant_suffix": f"{dominant_suffix:02d}",
                        "dominant_rate": round(dominant_rate, 4),
                        "chi2_against_uniform_100_buckets": round(chi2, 4),
                        "detector_family": "digits",
                    },
                    applicability={
                        "applicable": True,
                        "false_positive_controls": ["price_like", "quantized", "allow_rounding", "id_like"],
                    },
                )

        for pos, col_a in enumerate(numeric_cols):
            map_a = dict(suffix_by_col.get(col_a, []))
            for col_b in numeric_cols[pos + 1:]:
                if col_a in self._id_like_columns() or col_b in self._id_like_columns():
                    continue
                map_b = dict(suffix_by_col.get(col_b, []))
                shared = sorted(set(map_a) & set(map_b))
                if len(shared) < min_n:
                    continue
                same = [idx for idx in shared if map_a[idx] == map_b[idx]]
                same_rate = len(same) / len(shared)
                if same_rate >= cross_warn:
                    self._add_evidence(
                        "digits",
                        "digit_anomaly",
                        "critical" if same_rate >= 0.9 else "high",
                        min(0.99, same_rate),
                        "record",
                        "Multiple numeric columns share the same last-two digit suffix unusually often.",
                        record_indices=same,
                        columns=[col_a, col_b],
                        details={
                            "n": len(shared),
                            "same_suffix_rate": round(same_rate, 4),
                            "detector_family": "digits",
                        },
                    )

    def _audit_benford(self) -> None:
        min_n = int(self.metadata.get("benford_min_n", 1000))
        eligible_columns = 0
        skipped: Counter[str] = Counter()
        for column in self._numeric_columns():
            if column in self._id_like_columns():
                skipped["id_like"] += 1
                continue
            values = [_to_float(row.get(column)) for row in self.rows]
            values = [v for v in values if v is not None and v > 0]
            if len(values) < min_n:
                skipped["insufficient_n"] += 1
                continue
            order_span = math.log10(max(values)) - math.log10(min(values))
            if order_span < 2:
                skipped["range_too_narrow"] += 1
                continue
            eligible_columns += 1
            observed = Counter(
                digit for digit in (_first_significant_digit(v) for v in values)
                if digit is not None
            )
            total = sum(observed.values())
            if not total:
                continue
            expected = {digit: math.log10(1 + 1 / digit) for digit in range(1, 10)}
            mad = sum(abs(observed.get(d, 0) / total - expected[d]) for d in range(1, 10)) / 9
            if mad >= 0.015:
                self._add_evidence(
                    "benford",
                    "digit_anomaly",
                    "medium",
                    min(0.95, 0.55 + mad * 20),
                    "column",
                    f"Column '{column}' does not conform to first-digit Benford expectations.",
                    columns=[column],
                    details={
                        "n": total,
                        "order_span": round(order_span, 4),
                        "mad": round(mad, 6),
                        "observed": {str(k): observed.get(k, 0) for k in range(1, 10)},
                        "detector_family": "digits",
                    },
                    applicability={"applicable": True, "requires": "positive values spanning multiple orders"},
                )
        self._record_detector_note(
            "benford",
            applicable=eligible_columns > 0,
            reason="eligible_numeric_columns_checked" if eligible_columns else "no_benford_eligible_columns",
            details={"eligible_columns": eligible_columns, "skipped": dict(skipped), "min_n": min_n},
        )

    def _audit_pvalues(self) -> None:
        pvalue_cols = [
            col for col in self.columns
            if "pvalue" in col.lower().replace("_", "") or self.fields.get(col, {}).get("role") == "pvalue"
        ]
        checked = 0
        for column in pvalue_cols:
            pvalues = [
                val for val in (_to_float(row.get(column)) for row in self.rows)
                if val is not None and 0 <= val <= 1
            ]
            if len(pvalues) < 30:
                continue
            checked += 1
            below = sum(1 for val in pvalues if 0.045 <= val < 0.05)
            above = sum(1 for val in pvalues if 0.05 <= val < 0.055)
            sig_high = sum(1 for val in pvalues if 0.04 <= val < 0.05)
            sig_low = sum(1 for val in pvalues if 0 <= val < 0.01)
            flag = (below >= max(5, above * 3)) or (sig_high > sig_low and sig_high >= 10)
            if flag:
                self._add_evidence(
                    "pvalue",
                    "stat_inconsistency",
                    "high",
                    0.82,
                    "column",
                    f"Column '{column}' has p-values concentrated near 0.05.",
                    columns=[column],
                    details={
                        "n": len(pvalues),
                        "below_0_05_window": below,
                        "above_0_05_window": above,
                        "sig_0_04_to_0_05": sig_high,
                        "sig_0_to_0_01": sig_low,
                        "detector_family": "stats",
                    },
                    applicability={"applicable": True, "requires": "independent comparable p-values"},
                )
        self._record_detector_note(
            "pvalue",
            applicable=checked > 0,
            reason="pvalue_columns_checked" if checked else "no_pvalue_column_with_minimum_n",
            details={"pvalue_columns": pvalue_cols, "checked_columns": checked},
        )

    def _audit_target_distribution(self) -> None:
        if not isinstance(self.target_distribution, dict):
            self._record_detector_note(
                "target_distribution",
                applicable=False,
                reason="target_distribution_not_declared",
            )
            return
        tolerance = float(self.metadata.get("target_distribution_tolerance", 0.15))
        checked = 0
        for column, expected_raw in self.target_distribution.items():
            if not isinstance(expected_raw, dict) or column not in self.columns:
                continue
            checked += 1
            observed_counts = Counter(str(row.get(column)) for row in self.rows if not _is_missing(row.get(column)))
            total = sum(observed_counts.values())
            if not total:
                continue
            mismatches = {}
            for key, expected in expected_raw.items():
                try:
                    expected_rate = float(expected)
                except (TypeError, ValueError):
                    continue
                observed_rate = observed_counts.get(str(key), 0) / total
                if abs(observed_rate - expected_rate) > tolerance:
                    mismatches[str(key)] = {
                        "expected": round(expected_rate, 4),
                        "observed": round(observed_rate, 4),
                    }
            if mismatches:
                self._add_evidence(
                    "target_distribution",
                    "distribution_mismatch",
                    "medium",
                    0.8,
                    "dataset",
                    f"Column '{column}' distribution differs from the target distribution.",
                    columns=[column],
                    details={
                        "mismatches": mismatches,
                        "tolerance": tolerance,
                        "detector_family": "distribution",
                    },
                    applicability={"applicable": True},
                )
        self._record_detector_note(
            "target_distribution",
            applicable=checked > 0,
            reason="declared_target_columns_checked" if checked else "no_declared_target_columns_in_dataset",
            details={"checked_columns": checked},
        )

    def _critical_slice_specs(self) -> list[dict[str, Any]]:
        raw = self.task_spec.get("critical_slices") if isinstance(self.task_spec, dict) else None
        if not raw:
            return []
        default_min = int(self.task_spec.get("minimum_slice_count", self.metadata.get("minimum_slice_count", 5)))
        specs: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            for column, values in raw.items():
                if isinstance(values, dict):
                    for value, min_count in values.items():
                        specs.append({"column": str(column), "value": str(value), "min_count": int(min_count)})
                elif isinstance(values, list):
                    for value in values:
                        specs.append({"column": str(column), "value": str(value), "min_count": default_min})
                else:
                    specs.append({"column": str(column), "value": str(values), "min_count": default_min})
        elif isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict) or "column" not in item:
                    continue
                column = str(item["column"])
                min_count = int(item.get("min_count", default_min))
                values = item.get("values", item.get("value"))
                for value in _as_list(values):
                    if value is not None:
                        specs.append({"column": column, "value": str(value), "min_count": min_count})
        return specs

    def _audit_task_coverage(self) -> None:
        specs = self._critical_slice_specs()
        if not specs:
            self._record_detector_note(
                "task_coverage",
                applicable=False,
                reason="task_spec_critical_slices_not_declared",
                details={"task_spec_keys": sorted(self.task_spec) if isinstance(self.task_spec, dict) else []},
            )
            return

        self._record_detector_note(
            "task_coverage",
            applicable=True,
            reason="task_spec critical_slices declared",
            details={"slice_spec_count": len(specs)},
        )
        by_column: dict[str, Counter[str]] = {}
        for spec in specs:
            column = spec["column"]
            if column not in self.columns:
                self._add_evidence(
                    "task_coverage",
                    "distribution_mismatch",
                    "high",
                    0.9,
                    "dataset",
                    f"Critical slice column '{column}' is not present in the dataset.",
                    columns=[column],
                    details={
                        "critical_slice": spec,
                        "detector_family": "task_coverage",
                    },
                    applicability={"applicable": True, "requires": "task_spec critical_slices"},
                )
                continue
            by_column.setdefault(column, Counter(
                str(row.get(column)) for row in self.rows if not _is_missing(row.get(column))
            ))

        undercovered: list[dict[str, Any]] = []
        for spec in specs:
            column = spec["column"]
            if column not in self.columns:
                continue
            value = spec["value"]
            min_count = int(spec["min_count"])
            observed = by_column[column].get(value, 0)
            if observed < min_count:
                undercovered.append({
                    "column": column,
                    "value": value,
                    "observed_count": observed,
                    "min_count": min_count,
                })

        if undercovered:
            columns = sorted({item["column"] for item in undercovered})
            self._add_evidence(
                "task_coverage",
                "distribution_mismatch",
                "high",
                0.86,
                "dataset",
                "One or more task-critical slices are below the declared minimum sample count.",
                columns=columns,
                details={
                    "undercovered_slices": undercovered,
                    "detector_family": "task_coverage",
                    "interpretation": "Coverage evidence limits fit-for-task conclusions until recollection or resampling.",
                },
                applicability={"applicable": True, "requires": "task_spec critical_slices"},
            )

    def _categorical_columns(self) -> list[str]:
        out = []
        numeric_cols = set(self._numeric_columns())
        for col in self.columns:
            if col in numeric_cols:
                continue
            values = [str(row.get(col)) for row in self.rows if not _is_missing(row.get(col))]
            if not values:
                continue
            unique = len(set(values))
            if 2 <= unique <= min(30, max(2, len(values) // 3)):
                out.append(col)
        return out

    def _audit_distribution_uniformity(self) -> None:
        categorical_columns = self._categorical_columns()
        self._record_detector_note(
            "distribution",
            applicable=bool(categorical_columns),
            reason="categorical columns found" if categorical_columns else "no_categorical_columns",
            details={"categorical_columns": categorical_columns},
        )
        for column in categorical_columns:
            if str(self.fields.get(column, {}).get("role", "")).lower() in {"provenance", "id", "identifier"}:
                continue
            values = [str(row.get(column)) for row in self.rows if not _is_missing(row.get(column))]
            if len(values) < 24:
                continue
            counts = Counter(values)
            if len(counts) < 2:
                continue
            min_count = min(counts.values())
            max_count = max(counts.values())
            mean_count = len(values) / len(counts)
            max_deviation = max(abs(count - mean_count) for count in counts.values())
            perfectly_balanced = max_count - min_count <= 1
            has_declared_target = (
                isinstance(self.target_distribution, dict)
                and isinstance(self.target_distribution.get(column), dict)
            )
            if perfectly_balanced and mean_count >= 8 and not has_declared_target:
                self._add_evidence(
                    "distribution",
                    "distribution_mismatch",
                    "medium",
                    0.78,
                    "dataset",
                    f"Column '{column}' is almost perfectly balanced without a declared sampling target.",
                    columns=[column],
                    details={
                        "counts": dict(sorted(counts.items())),
                        "mean_count": round(mean_count, 4),
                        "max_deviation": round(max_deviation, 4),
                        "detector_family": "distribution",
                        "benign_explanations": ["stratified sampling", "balanced benchmark construction"],
                    },
                )

    def _audit_sequence_patterns(self) -> None:
        id_like = self._id_like_columns()
        sequence_min_n = int(self.metadata.get("sequence_min_n", 20))
        numeric_cols = [col for col in self._numeric_columns() if col not in id_like]
        time_like_cols = [
            col for col in self.columns
            if any(token in col.lower() for token in ("time", "date", "timestamp", "created_at"))
            or str(self.fields.get(col, {}).get("type", "")).lower() in {"datetime", "date", "timestamp"}
        ]
        self._record_detector_note(
            "sequence",
            applicable=bool(numeric_cols or time_like_cols),
            reason="numeric or time-like columns found" if numeric_cols or time_like_cols else "no_sequence_like_columns",
            details={"numeric_columns": numeric_cols, "time_like_columns": time_like_cols, "min_n": sequence_min_n},
        )

        numeric_series: dict[str, list[tuple[int, float]]] = {}
        for column in numeric_cols:
            series = [
                (idx, value)
                for idx, row in enumerate(self.rows)
                if (value := _to_float(row.get(column))) is not None
            ]
            numeric_series[column] = series
            if len(series) < sequence_min_n:
                continue
            diffs = [
                round(series[pos + 1][1] - series[pos][1], 10)
                for pos in range(len(series) - 1)
            ]
            if not diffs:
                continue
            step, step_count = Counter(diffs).most_common(1)[0]
            step_rate = step_count / len(diffs)
            monotonic_rate = sum(1 for diff in diffs if diff >= 0) / len(diffs)
            if step != 0 and step_rate >= 0.9:
                indices = [idx for idx, _ in series]
                self._add_evidence(
                    "sequence",
                    "synthetic_likely",
                    "high" if step_rate >= 0.97 else "medium",
                    min(0.95, 0.55 + step_rate / 2),
                    "record",
                    f"Column '{column}' follows an unusually regular arithmetic sequence.",
                    record_indices=indices,
                    columns=[column],
                    details={
                        "n": len(series),
                        "dominant_step": step,
                        "dominant_step_rate": round(step_rate, 4),
                        "monotonic_rate": round(monotonic_rate, 4),
                        "detector_family": "sequence",
                        "benign_explanations": ["sorted time series", "counter field", "simulation output"],
                    },
                )

        for pos, col_a in enumerate(numeric_cols):
            series_a = dict(numeric_series.get(col_a, []))
            for col_b in numeric_cols[pos + 1:]:
                series_b = dict(numeric_series.get(col_b, []))
                shared = sorted(set(series_a) & set(series_b))
                if len(shared) < sequence_min_n:
                    continue
                offsets = [round(series_b[idx] - series_a[idx], 10) for idx in shared]
                offset, offset_count = Counter(offsets).most_common(1)[0]
                offset_rate = offset_count / len(shared)
                if offset_rate >= 0.9:
                    self._add_evidence(
                        "sequence",
                        "synthetic_likely",
                        "medium",
                        min(0.92, 0.5 + offset_rate / 2),
                        "record",
                        "Two numeric columns preserve the same row-wise offset unusually often.",
                        record_indices=[idx for idx in shared if round(series_b[idx] - series_a[idx], 10) == offset],
                        columns=[col_a, col_b],
                        details={
                            "n": len(shared),
                            "offset": offset,
                            "offset_rate": round(offset_rate, 4),
                            "detector_family": "sequence",
                            "benign_explanations": ["derived feature", "unit conversion", "paired measurement protocol"],
                        },
                    )

        for column in time_like_cols:
            parsed = [
                (idx, dt.timestamp())
                for idx, row in enumerate(self.rows)
                if (dt := _try_parse_datetime(row.get(column))) is not None
            ]
            if len(parsed) < sequence_min_n:
                continue
            diffs = [
                round(parsed[pos + 1][1] - parsed[pos][1], 6)
                for pos in range(len(parsed) - 1)
            ]
            diffs = [diff for diff in diffs if diff > 0]
            if len(diffs) < sequence_min_n - 1:
                continue
            step, count = Counter(diffs).most_common(1)[0]
            rate = count / len(diffs)
            if rate >= 0.95:
                self._add_evidence(
                    "sequence",
                    "synthetic_likely",
                    "medium",
                    min(0.9, 0.45 + rate / 2),
                    "column",
                    f"Timestamp column '{column}' advances at a nearly fixed interval.",
                    columns=[column],
                    details={
                        "n": len(parsed),
                        "dominant_interval_seconds": step,
                        "dominant_interval_rate": round(rate, 4),
                        "detector_family": "sequence",
                        "benign_explanations": ["scheduled sampling", "batch export interval"],
                    },
                )

    def _audit_missingness_patterns(self) -> None:
        self._record_detector_note(
            "missingness",
            applicable=len(self.rows) >= 30 and len(self.columns) >= 4,
            reason="minimum rows and columns available" if len(self.rows) >= 30 and len(self.columns) >= 4 else "insufficient_rows_or_columns",
            details={"row_count": len(self.rows), "column_count": len(self.columns), "min_rows": 30, "min_columns": 4},
        )
        if len(self.rows) < 30 or len(self.columns) < 4:
            return
        patterns: Counter[str] = Counter()
        complete_rows = 0
        for row in self.rows:
            flags = ["1" if not _is_missing(row.get(col)) else "0" for col in self.columns]
            patterns["".join(flags)] += 1
            if all(flag == "1" for flag in flags):
                complete_rows += 1
        dominant_pattern, dominant_count = patterns.most_common(1)[0]
        dominant_rate = dominant_count / len(self.rows)
        complete_rate = complete_rows / len(self.rows)
        has_required_schema = any(spec.get("required") for spec in self.fields.values())
        if dominant_rate >= 0.98 and complete_rate >= 0.98 and not has_required_schema:
            self._add_evidence(
                "missingness",
                "outlier_needs_review",
                "low",
                0.45,
                "dataset",
                "All records share the same complete missingness pattern without declared required fields.",
                details={
                    "dominant_pattern": dominant_pattern,
                    "dominant_rate": round(dominant_rate, 4),
                    "complete_rate": round(complete_rate, 4),
                    "detector_family": "missingness",
                    "benign_explanations": ["well-curated export", "schema-enforced upstream pipeline"],
                },
            )

    def _audit_synthetic_fusion(self) -> None:
        family_to_refs: dict[str, list[str]] = defaultdict(list)
        family_to_indices: dict[str, set[int]] = defaultdict(set)
        family_to_strength: dict[str, float] = defaultdict(float)
        family_rank: dict[str, int] = defaultdict(int)
        ignored_families = {"schema", "missingness"}
        for item in self.evidence:
            if not item.applicability.get("applicable", True):
                continue
            family = item.details.get("detector_family")
            if not family or family in ignored_families:
                continue
            if item.severity == "low" and item.tag != "synthetic_likely":
                continue
            if item.tag in {
                "templated_text",
                "near_duplicate",
                "digit_anomaly",
                "stat_inconsistency",
                "distribution_mismatch",
                "synthetic_likely",
                "provenance_gap",
                "exact_duplicate",
            }:
                family_to_refs[str(family)].append(item.evidence_id)
                family_to_indices[str(family)].update(item.record_indices)
                family_to_strength[str(family)] = max(family_to_strength[str(family)], item.confidence)
                family_rank[str(family)] = max(family_rank[str(family)], SEVERITY_RANK[item.severity])

        families = sorted(family_to_refs)
        if len(families) < 2:
            return

        max_rank = max(family_rank.values()) if family_rank else 1
        strong_family_count = sum(
            1 for family in families
            if family_rank[family] >= SEVERITY_RANK["high"] or family_to_strength[family] >= 0.8
        )
        confidence = min(
            0.98,
            0.55
            + 0.12 * len(families)
            + 0.08 * strong_family_count
            + 0.05 * (max_rank - 1),
        )
        severity = "high"
        if len(families) >= 3 or strong_family_count >= 2 or max_rank >= SEVERITY_RANK["critical"]:
            severity = "critical"
        union_indices = sorted(set().union(*family_to_indices.values()))[:1000]
        self._add_evidence(
            "synthetic_fusion",
            "synthetic_likely",
            severity,
            confidence,
            "dataset",
            "Multiple independent evidence families point to synthetic, manually generated, or manipulated data patterns.",
            record_indices=union_indices,
            details={
                "families": families,
                "family_evidence_refs": dict(family_to_refs),
                "family_strength": {key: round(value, 4) for key, value in family_to_strength.items()},
                "detector_family": "fusion",
                "interpretation": "This is anomaly evidence requiring review, not standalone proof of fabrication.",
            },
        )

    def _build_report(self) -> dict[str, Any]:
        evidence_dicts = [item.to_dict() for item in self.evidence]
        tag_summary = self._tag_summary()
        gate = self._gate(tag_summary)
        top_anomalies = sorted(
            evidence_dicts,
            key=lambda item: (
                SEVERITY_RANK.get(item["severity"], 0),
                item["confidence"],
                len(item["record_indices"]),
            ),
            reverse=True,
        )[:20]
        record_tags = [
            {
                "record_index": idx,
                "tags": sorted(tags, key=lambda item: SEVERITY_RANK[item["severity"]], reverse=True),
            }
            for idx, tags in sorted(self.record_tags.items())
        ]
        synthetic_family_set: set[str] = set()
        for item in self.evidence:
            if item.tag != "synthetic_likely":
                continue
            family = item.details.get("detector_family")
            if family:
                synthetic_family_set.add(str(family))
            if item.detector == "synthetic_fusion":
                synthetic_family_set.update(str(family) for family in item.details.get("families", []))
        synthetic_families = sorted(synthetic_family_set)
        dataset_metrics = {
            "row_count": len(self.rows),
            "column_count": len(self.columns),
            "evidence_count": len(evidence_dicts),
            "tagged_record_count": len(record_tags),
            "tagged_record_rate": round(len(record_tags) / len(self.rows), 4) if self.rows else 0.0,
            "synthetic_evidence_families": synthetic_families,
        }
        quality_dimensions = self._quality_dimensions(tag_summary)
        risk_assessment = self._risk_assessment(tag_summary, gate, synthetic_families)
        detector_applicability = self._detector_applicability()
        review_queue = self._review_queue(evidence_dicts)
        llm_summary_input = {
            "task_spec": self.task_spec,
            "target_distribution": self.target_distribution,
            "dataset_metadata": {
                "schema": self.schema,
                "provenance": self.provenance,
                "row_count": len(self.rows),
                "columns": self.columns,
            },
            "dataset_metrics": dataset_metrics,
            "tag_summary": tag_summary,
            "top_anomalies": top_anomalies,
            "quality_dimensions": quality_dimensions,
            "risk_assessment": risk_assessment,
            "review_queue": review_queue[:25],
            "detector_applicability": detector_applicability,
            "gate": gate,
            "summary_contract": {
                "allowed": ["facts from evidence", "risk inference", "limitations", "recommended actions"],
                "forbidden": ["declare fraud from one detector", "quote raw data beyond evidence snippets"],
            },
        }
        return {
            "created_at": _utc_now(),
            "verdict": gate["verdict"],
            "gate": gate,
            "dataset_metrics": dataset_metrics,
            "quality_dimensions": quality_dimensions,
            "risk_assessment": risk_assessment,
            "detector_applicability": detector_applicability,
            "review_queue": review_queue,
            "tag_summary": tag_summary,
            "record_tags": record_tags,
            "evidence": evidence_dicts,
            "llm_summary_input": llm_summary_input,
        }

    def _quality_dimensions(self, tag_summary: dict[str, Any]) -> dict[str, Any]:
        dimensions: dict[str, Any] = {}
        for dimension, tags in QUALITY_DIMENSIONS.items():
            matched = {
                tag: tag_summary[tag]
                for tag in sorted(tags)
                if tag in tag_summary
            }
            if not matched:
                dimensions[dimension] = {
                    "status": "pass",
                    "tags": {},
                    "evidence_refs": [],
                    "max_severity": "low",
                    "record_count": 0,
                }
                continue
            max_severity = max(
                (item["max_severity"] for item in matched.values()),
                key=lambda severity: SEVERITY_RANK.get(severity, 0),
            )
            if max_severity == "critical":
                status = "fail"
            elif max_severity in {"high", "medium"}:
                status = "warning"
            else:
                status = "note"
            dimensions[dimension] = {
                "status": status,
                "tags": matched,
                "evidence_refs": sorted({
                    ref
                    for item in matched.values()
                    for ref in item.get("evidence_refs", [])
                }),
                "max_severity": max_severity,
                "record_count": sum(int(item.get("record_count") or 0) for item in matched.values()),
            }
        if not self.fields or not self.task_spec or not self.provenance:
            dimensions.setdefault("provenance_and_metadata", {}).setdefault("limitations", []).append(
                "schema/task_spec/provenance are required for high-confidence fit-for-task conclusions"
            )
        return dimensions

    def _risk_assessment(
        self,
        tag_summary: dict[str, Any],
        gate: dict[str, Any],
        synthetic_families: list[str],
    ) -> dict[str, Any]:
        task_tags = {
            "schema_violation",
            "missing_critical",
            "label_suspect",
            "distribution_mismatch",
            "provenance_gap",
            "leakage_risk",
        }
        task_evidence = sorted({
            ref
            for tag in task_tags
            for ref in (tag_summary.get(tag, {}).get("evidence_refs") or [])
        })
        if gate["verdict"] == "Fail":
            suitability = "not_fit_until_remediated"
        elif "provenance_gap" in tag_summary and not task_evidence:
            suitability = "insufficient_evidence"
        elif task_evidence:
            suitability = "fit_with_warnings"
        else:
            suitability = "fit_for_declared_task"

        manipulation_tags = {
            "synthetic_likely",
            "digit_anomaly",
            "stat_inconsistency",
            "templated_text",
            "near_duplicate",
            "exact_duplicate",
            "leakage_risk",
        }
        manipulation_evidence = sorted({
            ref
            for tag in manipulation_tags
            for ref in (tag_summary.get(tag, {}).get("evidence_refs") or [])
        })
        independent_families = len(set(synthetic_families))
        if "synthetic_likely" in tag_summary and independent_families >= 2:
            manipulation_risk = "high_review"
        elif manipulation_evidence:
            manipulation_risk = "elevated_review"
        else:
            manipulation_risk = "low_observed"

        confidence_limitations = []
        if not self.fields:
            confidence_limitations.append("missing schema.fields")
        if not self.task_spec:
            confidence_limitations.append("missing task_spec")
        if not self.provenance:
            confidence_limitations.append("missing provenance")
        if not self.target_distribution:
            confidence_limitations.append("missing target_distribution")
        return {
            "task_suitability": {
                "status": suitability,
                "evidence_refs": task_evidence,
                "reason": "derived from schema, missingness, label, distribution, and provenance evidence",
            },
            "manipulation_or_synthetic_risk": {
                "status": manipulation_risk,
                "evidence_refs": manipulation_evidence,
                "independent_evidence_families": synthetic_families,
                "caveat": "anomaly evidence is not standalone proof of fabrication",
            },
            "metadata_confidence": {
                "status": "limited" if confidence_limitations else "sufficient",
                "limitations": confidence_limitations,
            },
            "recommended_actions": list(gate.get("recommended_actions") or []),
        }

    def _detector_applicability(self) -> dict[str, Any]:
        detectors: dict[str, dict[str, Any]] = {}
        for detector, notes in self.detector_notes.items():
            entry = detectors.setdefault(detector, {
                "evidence_count": 0,
                "applicable_count": 0,
                "not_applicable_count": 0,
                "not_applicable_reasons": Counter(),
                "notes": [],
            })
            for note in notes:
                entry["notes"].append(dict(note))
                if note.get("applicable"):
                    entry["applicable_count"] += 1
                else:
                    entry["not_applicable_count"] += 1
                    entry["not_applicable_reasons"][str(note.get("reason") or "unspecified")] += 1
        for item in self.evidence:
            entry = detectors.setdefault(item.detector, {
                "evidence_count": 0,
                "applicable_count": 0,
                "not_applicable_count": 0,
                "not_applicable_reasons": Counter(),
                "notes": [],
            })
            entry["evidence_count"] += 1
            if item.applicability.get("applicable", True):
                entry["applicable_count"] += 1
            else:
                entry["not_applicable_count"] += 1
                reason = str(item.applicability.get("reason") or "unspecified")
                entry["not_applicable_reasons"][reason] += 1
        out = {}
        for detector, entry in detectors.items():
            reasons = entry.pop("not_applicable_reasons")
            out[detector] = {
                **entry,
                "not_applicable_reasons": dict(reasons),
            }
        return out

    def _review_queue(self, evidence_dicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        queue = []
        for item in evidence_dicts:
            severity = item.get("severity", "low")
            if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK["medium"]:
                continue
            tag = str(item.get("tag") or "")
            details = item.get("details") or {}
            benign = list(details.get("benign_explanations") or TAG_BENIGN_EXPLANATIONS.get(tag, []))
            action = TAG_ACTIONS.get(tag, "human_review")
            priority_score = (
                SEVERITY_RANK.get(severity, 0) * 100
                + int(float(item.get("confidence") or 0) * 20)
                + min(20, len(item.get("record_indices") or []))
            )
            queue.append({
                "queue_id": f"RQ{len(queue) + 1:04d}",
                "priority": severity,
                "priority_score": priority_score,
                "recommended_action": action,
                "tag": tag,
                "evidence_id": item.get("evidence_id"),
                "detector": item.get("detector"),
                "scope": item.get("scope"),
                "confidence": item.get("confidence"),
                "message": item.get("message"),
                "record_indices_sample": list(item.get("record_indices") or [])[:25],
                "record_count": len(item.get("record_indices") or []),
                "columns": list(item.get("columns") or []),
                "benign_explanations": benign,
                "next_validation_steps": TAG_REVIEW_STEPS.get(tag, ["Inspect evidence and compare against a trusted reference batch."]),
                "evidence_details": details,
            })
        queue.sort(key=lambda item: item["priority_score"], reverse=True)
        for idx, item in enumerate(queue, start=1):
            item["queue_id"] = f"RQ{idx:04d}"
        return queue

    def _tag_summary(self) -> dict[str, Any]:
        summary: dict[str, dict[str, Any]] = {}
        for item in self.evidence:
            tag = item.tag
            entry = summary.setdefault(tag, {
                "evidence_count": 0,
                "record_count": 0,
                "_record_indices": set(),
                "max_severity": "low",
                "max_confidence": 0.0,
                "evidence_refs": [],
            })
            entry["evidence_count"] += 1
            entry["_record_indices"].update(item.record_indices)
            if SEVERITY_RANK[item.severity] > SEVERITY_RANK[entry["max_severity"]]:
                entry["max_severity"] = item.severity
            entry["max_confidence"] = max(entry["max_confidence"], round(item.confidence, 4))
            entry["evidence_refs"].append(item.evidence_id)
        for entry in summary.values():
            entry["record_count"] = len(entry.pop("_record_indices"))
        return summary

    def _gate(self, tag_summary: dict[str, Any]) -> dict[str, Any]:
        blockers = []
        warnings = []
        insufficient = []
        substantive_tags = set()
        for item in self.evidence:
            if item.applicability.get("required_for_high_confidence"):
                insufficient.append(item.evidence_id)
            elif item.applicability.get("applicable", True) and item.severity != "low":
                substantive_tags.add(item.tag)
            if item.severity == "critical":
                blockers.append(item.evidence_id)
            elif item.severity in {"high", "medium"}:
                warnings.append(item.evidence_id)
        if blockers:
            verdict = "Fail"
        elif insufficient and not substantive_tags:
            verdict = "Insufficient Evidence"
        elif warnings or insufficient:
            verdict = "Pass with Warning"
        else:
            verdict = "Pass"
        actions = []
        tags = set(tag_summary)
        if {"exact_duplicate", "near_duplicate", "templated_text"} & tags:
            actions.append("deduplicate")
        if "missing_critical" in tags or "schema_violation" in tags:
            actions.append("quarantine_batch")
        if "label_suspect" in tags:
            actions.append("relabel_review")
        if "distribution_mismatch" in tags:
            actions.append("resample_or_recollect")
        if "digit_anomaly" in tags or "stat_inconsistency" in tags:
            actions.append("human_forensic_review")
        if "synthetic_likely" in tags:
            actions.extend(["human_forensic_review", "quarantine_batch"])
        if "leakage_risk" in tags:
            actions.append("quarantine_batch")
        if "provenance_gap" in tags:
            actions.append("collect_missing_metadata")
        return {
            "verdict": verdict,
            "blocker_evidence_refs": blockers,
            "warning_evidence_refs": warnings,
            "insufficient_evidence_refs": insufficient,
            "recommended_actions": sorted(set(actions)),
            "policy": "critical evidence fails; high/medium evidence warns; metadata gaps limit confidence; synthetic_likely requires multi-evidence review",
        }


def load_rows(path: str | Path) -> list[dict[str, Any]]:
    data_path = Path(path).expanduser().resolve()
    suffix = data_path.suffix.lower()
    if suffix == ".csv":
        with data_path.open("r", encoding="utf-8-sig", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]
    if suffix == ".jsonl":
        rows = []
        with data_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    if not isinstance(item, dict):
                        raise ValueError(f"JSONL rows must be objects: {data_path}")
                    rows.append(item)
        return rows
    if suffix == ".json":
        raw = json.loads(data_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            if not all(isinstance(item, dict) for item in raw):
                raise ValueError(f"JSON dataset must be a list of objects: {data_path}")
            return list(raw)
        if isinstance(raw, dict) and isinstance(raw.get("records"), list):
            return [dict(item) for item in raw["records"]]
        raise ValueError(f"Unsupported JSON dataset shape: {data_path}")
    raise ValueError(f"Unsupported dataset extension: {data_path.suffix}")


def load_metadata(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    meta_path = Path(path).expanduser().resolve()
    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"audit metadata must be a JSON object: {meta_path}")
    return raw


def audit_dataset(
    dataset_path: str | Path,
    metadata_path: str | Path | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = load_rows(dataset_path)
    merged_metadata = load_metadata(metadata_path)
    if metadata:
        merged_metadata.update(metadata)
    return DataAudit(rows, merged_metadata).run()


def write_audit_outputs(report: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "audit_report_json": out / "audit_report.json",
        "audit_report_md": out / "audit_report.md",
        "record_tags_jsonl": out / "record_tags.jsonl",
        "evidence_jsonl": out / "evidence.jsonl",
        "review_queue_jsonl": out / "review_queue.jsonl",
        "quality_dimensions_json": out / "quality_dimensions.json",
        "risk_assessment_json": out / "risk_assessment.json",
        "detector_applicability_json": out / "detector_applicability.json",
        "llm_summary_input_json": out / "llm_summary_input.json",
    }
    paths["audit_report_json"].write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    paths["llm_summary_input_json"].write_text(
        json.dumps(report["llm_summary_input"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    paths["quality_dimensions_json"].write_text(
        json.dumps(report.get("quality_dimensions") or {}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    paths["risk_assessment_json"].write_text(
        json.dumps(report.get("risk_assessment") or {}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    paths["detector_applicability_json"].write_text(
        json.dumps(report.get("detector_applicability") or {}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    with paths["record_tags_jsonl"].open("w", encoding="utf-8") as f:
        for item in report["record_tags"]:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    with paths["evidence_jsonl"].open("w", encoding="utf-8") as f:
        for item in report["evidence"]:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    with paths["review_queue_jsonl"].open("w", encoding="utf-8") as f:
        for item in report.get("review_queue") or []:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    paths["audit_report_md"].write_text(render_markdown_report(report), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def render_markdown_report(report: dict[str, Any]) -> str:
    metrics = report["dataset_metrics"]
    gate = report["gate"]
    synthetic_families = ", ".join(metrics.get("synthetic_evidence_families") or []) or "none"
    lines = [
        "# Data Quality Audit Report",
        "",
        f"- Verdict: **{report['verdict']}**",
        f"- Rows: {metrics['row_count']}",
        f"- Columns: {metrics['column_count']}",
        f"- Evidence items: {metrics['evidence_count']}",
        f"- Tagged records: {metrics['tagged_record_count']} ({metrics['tagged_record_rate']:.2%})",
        f"- Synthetic evidence families: {synthetic_families}",
        "",
        "## Gate",
        "",
        f"- Policy: {gate['policy']}",
        f"- Recommended actions: {', '.join(gate['recommended_actions']) or 'none'}",
        "",
        "## Risk Assessment",
        "",
        f"- Task suitability: {report.get('risk_assessment', {}).get('task_suitability', {}).get('status', 'unknown')}",
        f"- Manipulation/synthetic risk: {report.get('risk_assessment', {}).get('manipulation_or_synthetic_risk', {}).get('status', 'unknown')}",
        f"- Metadata confidence: {report.get('risk_assessment', {}).get('metadata_confidence', {}).get('status', 'unknown')}",
        "",
        "## Quality Dimensions",
        "",
        "| Dimension | Status | Max severity | Records |",
        "|---|---|---|---:|",
    ]
    for dimension, item in sorted((report.get("quality_dimensions") or {}).items()):
        lines.append(
            f"| `{dimension}` | {item.get('status')} | {item.get('max_severity')} | {item.get('record_count', 0)} |"
        )
    lines.extend([
        "",
        "## Tag Summary",
        "",
        "| Tag | Evidence | Records | Max severity | Max confidence |",
        "|---|---:|---:|---|---:|",
    ])
    for tag, item in sorted(report["tag_summary"].items()):
        lines.append(
            f"| `{tag}` | {item['evidence_count']} | {item['record_count']} | "
            f"{item['max_severity']} | {item['max_confidence']:.2f} |"
        )
    if not report["tag_summary"]:
        lines.append("| none | 0 | 0 | low | 0.00 |")
    lines.extend(["", "## Top Evidence", ""])
    for item in report["llm_summary_input"]["top_anomalies"][:10]:
        record_note = (
            f" records={item['record_indices'][:8]}"
            if item["record_indices"] else ""
        )
        cols = f" columns={item['columns']}" if item["columns"] else ""
        lines.append(
            f"- `{item['evidence_id']}` `{item['tag']}` {item['severity']} "
            f"confidence={item['confidence']:.2f}:{record_note}{cols} {item['message']}"
        )
    if not report["evidence"]:
        lines.append("- No evidence items emitted.")
    lines.extend(["", "## Review Queue", ""])
    for item in (report.get("review_queue") or [])[:10]:
        lines.append(
            f"- `{item['queue_id']}` {item['priority']} `{item['tag']}` "
            f"action={item['recommended_action']} evidence={item['evidence_id']}: {item['message']}"
        )
    if not report.get("review_queue"):
        lines.append("- No medium-or-higher evidence requires manual review.")
    lines.extend([
        "",
        "## LLM Summary Contract",
        "",
        "The LLM summary agent should consume `llm_summary_input.json` only and must distinguish facts, inferences, limitations, and recommended actions.",
        "",
    ])
    return "\n".join(lines)
