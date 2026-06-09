"""Main interface for data quality audit."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import audit_dataset, write_audit_outputs


def run(
    dataset: str | Path,
    *,
    metadata: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    report = audit_dataset(dataset, metadata_path=metadata)
    if output_dir:
        return {"report": report, "paths": write_audit_outputs(report, output_dir)}
    return {"report": report}


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("data_audit", target_type)


__all__ = ["commands", "run"]
