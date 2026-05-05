from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cc_config import load_config
from providers import stream, TextChunk
from memory.store import MemoryEntry, save_memory


GRAPH_TEMPLATE: dict[str, Any] = {
    "id": "city_famous_things_task_graph",
    "nodes": [
        {
            "id": "node_1",
            "name": "Identify Top 10 Cities",
            "strategy": "direct",
            "should_decompose": "Decompose if city criteria are ambiguous or sources conflict.",
            "contract": {
                "inputs": {
                    "criteria": {"type": "string", "desc": "Criteria for identifying top cities"},
                    "search_focus": {"type": "array<string>", "desc": "Topics for famous things"},
                },
                "outputs": {
                    "cities": {"type": "array<string>", "desc": "List of 10 city names"}
                },
            },
            "input_example": {
                "criteria": "global prominence (tourism, economy, culture)",
                "search_focus": ["landmarks", "museums", "parks", "historical sites"],
            },
            "output_example": {"cities": ["Paris", "Tokyo", "New York City", "London"]},
            "necessity_claim": "Provides the base city list used by every downstream node.",
            "verification_rule": "Ensure exactly 10 city names and no empty entries.",
            "gate_condition_for_next": "cities.length == 10",
        },
        {
            "id": "node_2",
            "name": "Find Famous Things per City",
            "strategy": "hybrid",
            "should_decompose": "Decompose per city if research effort is high.",
            "contract": {
                "inputs": {
                    "cities": {"type": "array<string>", "desc": "Cities from node_1"}
                },
                "outputs": {
                    "famous_things_per_city": {
                        "type": "array<array<object>>",
                        "desc": "Each city has 10 famous things",
                    }
                },
            },
            "input_example": {"cities": ["Paris", "Tokyo"]},
            "output_example": {
                "famous_things_per_city": [
                    [
                        {
                            "name": "Eiffel Tower",
                            "category": "landmark",
                            "reason": "Iconic symbol",
                            "score": 100,
                        }
                    ]
                ]
            },
            "necessity_claim": "Collects the 100 required items (10 cities x 10 things).",
            "verification_rule": "Each city has 10 items; total count is 100.",
            "gate_condition_for_next": "total_items == 100",
        },
        {
            "id": "node_3",
            "name": "Compile All Items",
            "strategy": "direct",
            "should_decompose": "No further decomposition needed.",
            "contract": {
                "inputs": {
                    "famous_things_per_city": {
                        "type": "array<array<object>>",
                        "desc": "Output from node_2",
                    }
                },
                "outputs": {
                    "all_items": {
                        "type": "array<object>",
                        "desc": "Flat list of 100 items with city and thing",
                    }
                },
            },
            "input_example": {
                "famous_things_per_city": [[{"name": "Eiffel Tower", "city": "Paris"}]]
            },
            "output_example": {
                "all_items": [
                    {
                        "city": "Paris",
                        "thing": "Eiffel Tower",
                        "category": "landmark",
                        "reason": "Iconic symbol",
                        "score": 100,
                    }
                ]
            },
            "necessity_claim": "Normalizes data into a single list for ranking and tree building.",
            "verification_rule": "List length is 100; each item has city and thing.",
            "gate_condition_for_next": "all_items.length == 100",
        },
        {
            "id": "node_4",
            "name": "Create Tree Visualization",
            "strategy": "direct",
            "should_decompose": "No further decomposition needed.",
            "contract": {
                "inputs": {
                    "all_items": {
                        "type": "array<object>",
                        "desc": "Items list from node_3",
                    }
                },
                "outputs": {
                    "tree_visualization": {
                        "type": "string",
                        "desc": "Text tree of cities and famous things",
                    }
                },
            },
            "input_example": {"all_items": [{"city": "Paris", "thing": "Eiffel Tower"}]},
            "output_example": {"tree_visualization": "- Paris\n  - Eiffel Tower"},
            "necessity_claim": "Provides the required tree visualization.",
            "verification_rule": "Tree contains 10 cities and 10 items per city.",
            "gate_condition_for_next": "tree_visualization contains all items",
        },
        {
            "id": "node_5",
            "name": "Rank Items by Importance",
            "strategy": "direct",
            "should_decompose": "Decompose if ranking criteria are complex.",
            "contract": {
                "inputs": {
                    "all_items": {
                        "type": "array<object>",
                        "desc": "Items from node_3",
                    },
                    "ranking_criteria": {
                        "type": "string",
                        "desc": "Criteria for ranking importance",
                    },
                },
                "outputs": {
                    "ranked_items": {
                        "type": "array<object>",
                        "desc": "Items sorted with rank/score",
                    }
                },
            },
            "input_example": {"all_items": [{"thing": "Eiffel Tower"}], "ranking_criteria": "global fame"},
            "output_example": {
                "ranked_items": [{"city": "Paris", "thing": "Eiffel Tower", "rank": 1, "score": 100}]
            },
            "necessity_claim": "Implements the ranking requirement.",
            "verification_rule": "Ranked list length 100, scores unique 1-100, sorted desc.",
            "gate_condition_for_next": "ranked_items sorted desc",
        },
        {
            "id": "node_6",
            "name": "Validate Completeness",
            "strategy": "direct",
            "should_decompose": "No.",
            "contract": {
                "inputs": {"items_list": {"type": "array<object>", "desc": "Items from node_3"}},
                "outputs": {"is_complete": {"type": "boolean", "desc": "True if 100 items"}},
            },
            "input_example": {"items_list": [{"thing": "Eiffel Tower"}]},
            "output_example": {"is_complete": True},
            "necessity_claim": "Prevents downstream output if items are incomplete.",
            "verification_rule": "Count items == 100.",
            "gate_condition_for_next": "is_complete == true",
        },
        {
            "id": "node_7",
            "name": "Validate Ranking",
            "strategy": "direct",
            "should_decompose": "No.",
            "contract": {
                "inputs": {
                    "ranked_list": {"type": "array<object>", "desc": "Ranked items"},
                    "criteria": {"type": "string", "desc": "Ranking criteria"},
                },
                "outputs": {
                    "is_valid_ranking": {"type": "boolean", "desc": "True if ranking passes"}
                },
            },
            "input_example": {"ranked_list": [{"thing": "Eiffel Tower", "score": 100}], "criteria": "global fame"},
            "output_example": {"is_valid_ranking": True},
            "necessity_claim": "Ensures ranking validity before final output.",
            "verification_rule": "Scores are unique and descending.",
            "gate_condition_for_next": "is_valid_ranking == true",
        },
        {
            "id": "node_8",
            "name": "Generate Output File",
            "strategy": "direct",
            "should_decompose": "No.",
            "contract": {
                "inputs": {
                    "tree_text": {"type": "string", "desc": "Tree text from node_4"},
                    "ranked_list": {"type": "array<object>", "desc": "Ranked list from node_5"},
                    "is_complete": {"type": "boolean", "desc": "Gate from node_6"},
                    "is_valid_ranking": {"type": "boolean", "desc": "Gate from node_7"},
                },
                "outputs": {
                    "output_file": {"type": "file", "desc": "TXT file with tree and ranking"}
                },
            },
            "input_example": {"tree_text": "- Paris", "ranked_list": [], "is_complete": True, "is_valid_ranking": True},
            "output_example": {"output_file": "result.txt"},
            "necessity_claim": "Produces final deliverable once gates pass.",
            "verification_rule": "Output file exists and contains both tree and ranking sections.",
            "gate_condition_for_next": "is_complete && is_valid_ranking",
        },
    ],
    "edges": [
        {"from": {"nodeId": "node_1", "port": "cities"}, "to": {"nodeId": "node_2", "port": "cities"}},
        {"from": {"nodeId": "node_2", "port": "famous_things_per_city"}, "to": {"nodeId": "node_3", "port": "famous_things_per_city"}},
        {"from": {"nodeId": "node_3", "port": "all_items"}, "to": {"nodeId": "node_4", "port": "all_items"}},
        {"from": {"nodeId": "node_3", "port": "all_items"}, "to": {"nodeId": "node_5", "port": "all_items"}},
        {"from": {"nodeId": "node_3", "port": "all_items"}, "to": {"nodeId": "node_6", "port": "items_list"}},
        {"from": {"nodeId": "node_5", "port": "ranked_items"}, "to": {"nodeId": "node_7", "port": "ranked_list"}},
        {"from": {"nodeId": "node_4", "port": "tree_visualization"}, "to": {"nodeId": "node_8", "port": "tree_text"}},
        {"from": {"nodeId": "node_5", "port": "ranked_items"}, "to": {"nodeId": "node_8", "port": "ranked_list"}},
        {"from": {"nodeId": "node_6", "port": "is_complete"}, "to": {"nodeId": "node_8", "port": "is_complete"}},
        {"from": {"nodeId": "node_7", "port": "is_valid_ranking"}, "to": {"nodeId": "node_8", "port": "is_valid_ranking"}},
    ],
    "inputMapping": {
        "city_criteria": {"nodeId": "node_1", "port": "criteria"},
        "search_focus": {"nodeId": "node_1", "port": "search_focus"},
        "ranking_criteria": {"nodeId": "node_5", "port": "ranking_criteria"},
        "ranking_criteria_validation": {"nodeId": "node_7", "port": "criteria"},
    },
    "outputMapping": {"task_output": {"nodeId": "node_8", "port": "output_file"}},
}


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip("\"").strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def _call_model(system_prompt: str, user_prompt: str, config: dict) -> str:
    messages = [{"role": "user", "content": user_prompt}]
    text_out = ""
    for event in stream(
        model=config["model"],
        system=system_prompt,
        messages=messages,
        tool_schemas=[],
        config=config,
    ):
        if isinstance(event, TextChunk):
            text_out += event.text
    return text_out


def _validate_graph(graph: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(graph, dict):
        return ["Graph is not a JSON object."]
    for key in ("nodes", "edges", "inputMapping", "outputMapping"):
        if key not in graph:
            errors.append(f"Missing '{key}' field.")
    nodes = graph.get("nodes", [])
    if not isinstance(nodes, list):
        errors.append("'nodes' must be a list.")
        return errors
    for node in nodes:
        if not isinstance(node, dict):
            errors.append("Node entry is not an object.")
            continue
        for k in ("id", "name", "contract"):
            if k not in node:
                errors.append(f"Node missing '{k}'.")
        contract = node.get("contract", {})
        if not isinstance(contract, dict):
            errors.append(f"Node {node.get('id', '?')} contract is not an object.")
            continue
        for ck in ("inputs", "outputs"):
            if ck not in contract:
                errors.append(f"Node {node.get('id', '?')} missing contract.{ck}.")
        if not node.get("strategy"):
            errors.append(f"Node {node.get('id', '?')} missing strategy.")
        if not node.get("should_decompose"):
            errors.append(f"Node {node.get('id', '?')} missing should_decompose.")
        if not node.get("necessity_claim"):
            errors.append(f"Node {node.get('id', '?')} missing necessity_claim.")
        if not node.get("verification_rule"):
            errors.append(f"Node {node.get('id', '?')} missing verification_rule.")
        if "input_example" not in node:
            errors.append(f"Node {node.get('id', '?')} missing input_example.")
        if "output_example" not in node:
            errors.append(f"Node {node.get('id', '?')} missing output_example.")
        if "gate_condition_for_next" not in node:
            errors.append(f"Node {node.get('id', '?')} missing gate_condition_for_next.")
    return errors


def _fill_from_template(graph: dict) -> dict:
    template_nodes = {n["id"]: n for n in GRAPH_TEMPLATE.get("nodes", [])}
    for node in graph.get("nodes", []):
        tnode = template_nodes.get(node.get("id", ""))
        if not tnode:
            continue
        for key in (
            "strategy",
            "should_decompose",
            "input_example",
            "output_example",
            "necessity_claim",
            "verification_rule",
            "gate_condition_for_next",
        ):
            if not node.get(key):
                node[key] = tnode.get(key)
    if not graph.get("edges"):
        graph["edges"] = GRAPH_TEMPLATE.get("edges", [])
    if not graph.get("inputMapping"):
        graph["inputMapping"] = GRAPH_TEMPLATE.get("inputMapping", {})
    if not graph.get("outputMapping"):
        graph["outputMapping"] = GRAPH_TEMPLATE.get("outputMapping", {})
    return graph


def _build_graph_prompt(task_desc: str) -> str:
    return (
        "Return JSON only. Use node ids node_1..node_8 and include input_example/output_example and gate_condition_for_next.\n"
        "Decompose the task into a directed graph with explicit IO contracts and audit fields.\n"
        "Include validation nodes for completeness and ranking, and gate output on validation.\n"
        "Schema:\n"
        "{\n"
        "  \"id\": \"graph_id\",\n"
        "  \"nodes\": [\n"
        "    {\n"
        "      \"id\": \"node_1\",\n"
        "      \"name\": \"Short name\",\n"
        "      \"strategy\": \"direct|decompose|hybrid\",\n"
        "      \"should_decompose\": \"Condition for further decomposition\",\n"
        "      \"contract\": {\n"
        "        \"inputs\": {\"field\": {\"type\": \"string\", \"desc\": \"...\"}},\n"
        "        \"outputs\": {\"field\": {\"type\": \"string\", \"desc\": \"...\"}}\n"
        "      },\n"
        "      \"input_example\": {\"field\": \"sample\"},\n"
        "      \"output_example\": {\"field\": \"sample\"},\n"
        "      \"necessity_claim\": \"Why this node is indispensable\",\n"
        "      \"verification_rule\": \"How to verify its output\",\n"
        "      \"gate_condition_for_next\": \"Condition for downstream execution\"\n"
        "    }\n"
        "  ],\n"
        "  \"edges\": [\n"
        "    {\"from\": {\"nodeId\": \"node_1\", \"port\": \"field\"},\n"
        "     \"to\":   {\"nodeId\": \"node_2\", \"port\": \"field\"}}\n"
        "  ],\n"
        "  \"inputMapping\":  {\"task_input\": {\"nodeId\": \"node_1\", \"port\": \"field\"}},\n"
        "  \"outputMapping\": {\"task_output\": {\"nodeId\": \"node_8\", \"port\": \"field\"}}\n"
        "}\n"
        f"Task: {task_desc}\n"
    )


def _build_result_prompt(task_desc: str, issues: list[str] | None = None) -> str:
    issue_text = ""
    if issues:
        issue_lines = "\n".join(f"- {i}" for i in issues)
        issue_text = (
            "Previous attempt failed validation. Fix ALL issues below.\n"
            f"Issues:\n{issue_lines}\n"
        )
    return (
        "Return JSON only. Provide 10 globally prominent cities and 10 famous things per city.\n"
        "Constraints:\n"
        "- Exactly 10 cities.\n"
        "- Exactly 10 items per city.\n"
        "- Each item must include a short reason and an integer score (1-100).\n"
        "- Scores should be unique across all 100 items.\n"
        "- Names, categories, and reasons must be non-empty.\n"
        "Schema:\n"
        "{\n"
        "  \"selection_criteria\": \"...\",\n"
        "  \"assumptions\": [\"...\"],\n"
        "  \"cities\": [\n"
        "    {\n"
        "      \"city\": \"Name\",\n"
        "      \"items\": [\n"
        "        {\"name\": \"Thing\", \"category\": \"landmark\", \"reason\": \"...\", \"score\": 100}\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n"
        + issue_text
        + f"Task: {task_desc}\n"
    )


def _validate_result(result: dict[str, Any]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    cities = result.get("cities", [])
    if len(cities) != 10:
        issues.append(f"Expected 10 cities, got {len(cities)}.")
    scores: list[int] = []
    total_items = 0
    seen_pairs: set[tuple[str, str]] = set()
    for city in cities:
        items = city.get("items", [])
        total_items += len(items)
        if len(items) != 10:
            issues.append(f"City '{city.get('city', '')}' has {len(items)} items.")
        for item in items:
            score = int(item.get("score", 0))
            scores.append(score)
            name = str(item.get("name", "")).strip()
            category = str(item.get("category", "")).strip()
            reason = str(item.get("reason", "")).strip()
            if not name:
                issues.append(f"Missing item name in city '{city.get('city', '')}'.")
            if not category:
                issues.append(f"Missing category for item '{name}' in city '{city.get('city', '')}'.")
            if not reason:
                issues.append(f"Missing reason for item '{name}' in city '{city.get('city', '')}'.")
            pair = (city.get("city", ""), name)
            if pair in seen_pairs:
                issues.append(f"Duplicate item '{name}' in city '{city.get('city', '')}'.")
            seen_pairs.add(pair)
    if total_items != 100:
        issues.append(f"Expected 100 items total, got {total_items}.")
    if len(scores) != len(set(scores)):
        issues.append("Scores are not unique across all items.")
    bad_scores = [s for s in scores if s < 1 or s > 100]
    if bad_scores:
        issues.append("Some scores are outside 1-100.")
    return (len(issues) == 0), issues


def _flatten_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    for city in result.get("cities", []):
        cname = city.get("city", "")
        for item in city.get("items", []):
            flat.append(
                {
                    "city": cname,
                    "thing": item.get("name", ""),
                    "category": item.get("category", ""),
                    "reason": item.get("reason", ""),
                    "score": int(item.get("score", 0)),
                }
            )
    return flat


def _build_tree_text(cities: list[dict[str, Any]], ranked_map: dict[tuple[str, str], int]) -> str:
    lines: list[str] = []
    lines.append("Tree view (city -> items with global rank):")
    for city in cities:
        cname = city.get("city", "")
        lines.append(f"- {cname}")
        for item in city.get("items", []):
            key = (cname, item.get("name", ""))
            rank = ranked_map.get(key, 0)
            score = item.get("score", 0)
            category = item.get("category", "")
            reason = item.get("reason", "")
            lines.append(
                f"  - #{rank:03d} score={score:3d} | {item.get('name', '')} "
                f"({category}) | {reason}"
            )
    return "\n".join(lines)


def _build_ranking_text(flat: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("Global ranking (1-100):")
    for idx, item in enumerate(flat, start=1):
        lines.append(
            f"#{idx:03d} score={item.get('score', 0):3d} | {item.get('thing', '')} "
            f"[{item.get('city', '')}]"
        )
    return "\n".join(lines)


def _shape_summary(value: Any, depth: int = 1) -> Any:
    if depth < 0:
        return "..."
    if isinstance(value, dict):
        return {k: _shape_summary(v, depth - 1) for k, v in list(value.items())[:5]}
    if isinstance(value, list):
        if not value:
            return []
        return [
            {
                "type": type(value[0]).__name__,
                "sample": _shape_summary(value[0], depth - 1),
                "length": len(value),
            }
        ]
    return type(value).__name__


def _compare_sample_to_actual(sample: Any, actual: Any, path: str = "") -> list[str]:
    issues: list[str] = []
    if isinstance(sample, dict):
        if not isinstance(actual, dict):
            issues.append(f"{path}: expected object, got {type(actual).__name__}")
            return issues
        for key, sval in sample.items():
            if key not in actual:
                issues.append(f"{path}.{key}: missing")
                continue
            issues.extend(_compare_sample_to_actual(sval, actual[key], f"{path}.{key}"))
        return issues
    if isinstance(sample, list):
        if not isinstance(actual, list):
            issues.append(f"{path}: expected list, got {type(actual).__name__}")
            return issues
        if sample:
            issues.extend(_compare_sample_to_actual(sample[0], actual[0] if actual else None, f"{path}[0]"))
        return issues
    if sample is None:
        return issues
    if not isinstance(actual, type(sample)):
        issues.append(f"{path}: expected {type(sample).__name__}, got {type(actual).__name__}")
    return issues


def _necessity_audit(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = [n.get("id", "") for n in graph.get("nodes", [])]
    edges = graph.get("edges", [])
    outputs = {v.get("nodeId", "") for v in graph.get("outputMapping", {}).values()}
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for e in edges:
        src = e.get("from", {}).get("nodeId", "")
        dst = e.get("to", {}).get("nodeId", "")
        if src and dst:
            adj.setdefault(src, []).append(dst)
    
    def _reaches_output(start: str) -> bool:
        seen = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            if cur in outputs:
                return True
            for nxt in adj.get(cur, []):
                stack.append(nxt)
        return False

    results: dict[str, dict[str, Any]] = {}
    for node_id in nodes:
        reaches = _reaches_output(node_id)
        results[node_id] = {
            "counterfactual": f"remove {node_id}",
            "impact": "breaks path to output" if reaches else "no path to output",
            "necessary": reaches,
        }
    return results


def _audit_with_agent(
    audit_payload: dict[str, Any],
    config: dict,
    system_prompt: str,
) -> dict[str, Any]:
    user_prompt = (
        "You are an independent audit agent. Return JSON only.\n"
        "For each node, produce: acceptance_status (pass/fail), verification_result (string), "
        "compressed_judgment (short), evidence_pointer (array of section anchors), gate_condition_for_next (bool).\n"
        "Use only provided data; do not invent external evidence.\n"
        f"Payload:\n{json.dumps(audit_payload, ensure_ascii=False)}\n"
    )
    text = _call_model(system_prompt, user_prompt, config)
    return _extract_json(text)


def _write_module_memory(base_dir: Path, node_id: str, content: str) -> Path:
    mod_dir = base_dir / "modules" / node_id
    mod_dir.mkdir(parents=True, exist_ok=True)
    mem_path = mod_dir / "memory.md"
    mem_path.write_text(content, encoding="utf-8")
    return mem_path


def main() -> int:
    task_desc = (
        "搜寻世界上前10城市的10个出名的事物共100个，用树结构可视化展现出来，"
        "同时对这100个的重要性排序，排序结果生成txt文件"
    )
    if len(sys.argv) > 1:
        task_desc = " ".join(sys.argv[1:]).strip()

    log: list[str] = []
    log.append(f"{datetime.now().isoformat()} start")

    _load_dotenv(ROOT / ".env")

    config = load_config()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    if "/" not in model:
        model = f"anthropic/{model}"
    config["model"] = model

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if api_key:
        config["anthropic_api_key"] = api_key
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if base_url:
        config["anthropic_base_url"] = base_url

    fragment_path = ROOT / "prompts" / "fragments" / "evidence_chain.md"
    fragment = fragment_path.read_text(encoding="utf-8") if fragment_path.exists() else ""
    system_prompt = "You are a precise decomposition assistant.\n\n" + fragment

    graph_source = "model"
    graph: dict[str, Any] | None = None
    errors: list[str] = []
    for _ in range(3):
        graph_text = _call_model(system_prompt, _build_graph_prompt(task_desc), config)
        graph = _extract_json(graph_text)
        graph = _fill_from_template(graph)
        errors = _validate_graph(graph)
        if not errors:
            break
    if errors:
        graph = GRAPH_TEMPLATE
        graph_source = "template"
        errors = []
    log.append(f"{datetime.now().isoformat()} graph_source={graph_source}")

    result: dict[str, Any] | None = None
    issues: list[str] = []
    ok = False
    for _ in range(3):
        result_text = _call_model(system_prompt, _build_result_prompt(task_desc, issues), config)
        result = _extract_json(result_text)
        ok, issues = _validate_result(result)
        if ok:
            break
    if not result or not ok:
        print("Result validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 2

    cities = result.get("cities", [])
    flat = _flatten_items(result)
    flat.sort(key=lambda x: (-x.get("score", 0), x.get("city", ""), x.get("thing", "")))
    ranked_items = [
        {**item, "rank": idx + 1} for idx, item in enumerate(flat)
    ]
    rank_map = {(item["city"], item["thing"]): idx + 1 for idx, item in enumerate(flat)}
    tree_text = _build_tree_text(cities, rank_map)
    ranking_text = _build_ranking_text(flat)

    is_complete = len(flat) == 100 and len(cities) == 10 and all(len(c.get("items", [])) == 10 for c in cities)
    is_valid_ranking = is_complete and len({item["score"] for item in flat}) == 100

    ranking_criteria = "global fame, cultural significance, historical impact, tourist popularity"
    search_focus = ["landmarks", "museums", "parks", "historic sites", "modern architecture"]
    criteria = "global prominence (tourism, economy, culture)"

    actual_io: dict[str, dict[str, Any]] = {
        "node_1": {
            "inputs": {"criteria": criteria, "search_focus": search_focus},
            "outputs": {"cities": [c.get("city", "") for c in cities]},
        },
        "node_2": {
            "inputs": {"cities": [c.get("city", "") for c in cities]},
            "outputs": {
                "famous_things_per_city": [
                    [
                        {
                            "name": item.get("name", ""),
                            "category": item.get("category", ""),
                            "reason": item.get("reason", ""),
                            "score": item.get("score", 0),
                        }
                        for item in c.get("items", [])
                    ]
                    for c in cities
                ]
            },
        },
        "node_3": {
            "inputs": {"famous_things_per_city": "see node_2.output"},
            "outputs": {"all_items": flat},
        },
        "node_4": {
            "inputs": {"all_items": "see node_3.output"},
            "outputs": {"tree_visualization": tree_text},
        },
        "node_5": {
            "inputs": {"all_items": "see node_3.output", "ranking_criteria": ranking_criteria},
            "outputs": {"ranked_items": ranked_items},
        },
        "node_6": {
            "inputs": {"items_list": "see node_3.output"},
            "outputs": {"is_complete": is_complete},
        },
        "node_7": {
            "inputs": {"ranked_list": "see node_5.output", "criteria": ranking_criteria},
            "outputs": {"is_valid_ranking": is_valid_ranking},
        },
        "node_8": {
            "inputs": {
                "tree_text": tree_text,
                "ranked_list": ranked_items,
                "is_complete": is_complete,
                "is_valid_ranking": is_valid_ranking,
            },
            "outputs": {"output_file": "result.txt"},
        },
    }

    if not (is_complete and is_valid_ranking):
        print("Gate conditions failed; refusing to generate output.")
        return 2

    necessity_audit = _necessity_audit(graph)

    io_comparison: dict[str, dict[str, Any]] = {}
    for node in graph.get("nodes", []):
        nid = node.get("id", "")
        planned_in = node.get("input_example")
        planned_out = node.get("output_example")
        actual = actual_io.get(nid, {})
        in_issues = _compare_sample_to_actual(planned_in, actual.get("inputs"), "inputs")
        out_issues = _compare_sample_to_actual(planned_out, actual.get("outputs"), "outputs")
        io_comparison[nid] = {
            "input_match": len(in_issues) == 0,
            "output_match": len(out_issues) == 0,
            "issues": in_issues + out_issues,
        }

    audit_payload = {
        "nodes": [
            {
                "id": node.get("id", ""),
                "name": node.get("name", ""),
                "planned_io": {
                    "input_example": node.get("input_example"),
                    "output_example": node.get("output_example"),
                },
                "actual_io_summary": {
                    "inputs": _shape_summary(actual_io.get(node.get("id", ""), {}).get("inputs")),
                    "outputs": _shape_summary(actual_io.get(node.get("id", ""), {}).get("outputs")),
                },
                "comparison": io_comparison.get(node.get("id", ""), {}),
                "necessity_audit": necessity_audit.get(node.get("id", ""), {}),
            }
            for node in graph.get("nodes", [])
        ]
    }

    audit_agent_report = {}
    try:
        audit_agent_report = _audit_with_agent(audit_payload, config, "You are an independent audit agent.")
    except Exception:
        audit_agent_report = {"nodes": []}

    output_dir = ROOT.parent / "example" / "example1"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "result.txt"

    lines: list[str] = []
    lines.append("Task (original):")
    lines.append(task_desc)
    lines.append("")

    lines.append("Graph (raw JSON):")
    lines.append(json.dumps(graph, ensure_ascii=False, indent=2))
    lines.append("")

    lines.append("Node IO standards (with samples):")
    for node in graph.get("nodes", []):
        contract = node.get("contract", {})
        inputs = contract.get("inputs", {})
        outputs = contract.get("outputs", {})
        lines.append(f"- {node.get('id', '')} | {node.get('name', '')}")
        lines.append(f"  strategy: {node.get('strategy', '')}")
        lines.append(f"  should_decompose: {node.get('should_decompose', '')}")
        lines.append(f"  inputs:  {json.dumps(inputs, ensure_ascii=False)}")
        lines.append(f"  outputs: {json.dumps(outputs, ensure_ascii=False)}")
        lines.append(f"  input_example: {json.dumps(node.get('input_example'), ensure_ascii=False)}")
        lines.append(f"  output_example: {json.dumps(node.get('output_example'), ensure_ascii=False)}")
        lines.append(f"  necessity_claim: {node.get('necessity_claim', '')}")
        lines.append(f"  verification_rule: {node.get('verification_rule', '')}")
        lines.append(f"  gate_condition_for_next: {node.get('gate_condition_for_next', '')}")
    lines.append("")

    lines.append("Actual IO (per node):")
    for node in graph.get("nodes", []):
        nid = node.get("id", "")
        actual = actual_io.get(nid, {})
        lines.append(f"- {nid} actual_input:")
        lines.append(json.dumps(actual.get("inputs"), ensure_ascii=False, indent=2))
        lines.append(f"- {nid} actual_output:")
        lines.append(json.dumps(actual.get("outputs"), ensure_ascii=False, indent=2))
    lines.append("")

    lines.append("IO comparison results:")
    for node in graph.get("nodes", []):
        nid = node.get("id", "")
        cmp = io_comparison.get(nid, {})
        lines.append(f"- {nid}: input_match={cmp.get('input_match')} output_match={cmp.get('output_match')}")
        for issue in cmp.get("issues", []):
            lines.append(f"  issue: {issue}")
    lines.append("")

    lines.append("Necessity audit process:")
    for node in graph.get("nodes", []):
        nid = node.get("id", "")
        ninfo = necessity_audit.get(nid, {})
        lines.append(f"- {nid}: counterfactual={ninfo.get('counterfactual')} impact={ninfo.get('impact')} necessary={ninfo.get('necessary')}")
    lines.append("")

    lines.append("Independent audit agent report:")
    lines.append(json.dumps(audit_agent_report, ensure_ascii=False, indent=2))
    lines.append("")

    lines.append("Selection criteria:")
    lines.append(result.get("selection_criteria", ""))
    lines.append("")

    lines.append("Assumptions:")
    for a in result.get("assumptions", []):
        lines.append(f"- {a}")
    lines.append("")

    lines.append(tree_text)
    lines.append("")
    lines.append(ranking_text)
    lines.append("")

    ok, issues = _validate_result(result)
    lines.append("Audit summary:")
    lines.append(f"- acceptance_status: {'pass' if ok else 'fail'}")
    if issues:
        for issue in issues:
            lines.append(f"- issue: {issue}")
    lines.append("")

    lines.append("Node audit results:")
    audit_nodes = {n.get("id", ""): n for n in audit_agent_report.get("nodes", [])}
    for node in graph.get("nodes", []):
        nid = node.get("id", "")
        report = audit_nodes.get(nid, {})
        lines.append(f"- {nid} | {node.get('name', '')} | acceptance_status={report.get('acceptance_status', 'unknown')}")
        lines.append(f"  verification_result: {report.get('verification_result', '')}")
        lines.append(f"  compressed_judgment: {report.get('compressed_judgment', '')}")
        lines.append(f"  evidence_pointer: {report.get('evidence_pointer', [])}")
        lines.append(f"  gate_condition_for_next: {report.get('gate_condition_for_next', False)}")
    lines.append("")

    lines.append("Module memory files:")
    module_memories: dict[str, Path] = {}
    for node in graph.get("nodes", []):
        nid = node.get("id", "")
        report = audit_nodes.get(nid, {})
        mem_lines = []
        mem_lines.append(f"node_id: {nid}")
        mem_lines.append(f"node_name: {node.get('name', '')}")
        mem_lines.append(f"necessity_claim: {node.get('necessity_claim', '')}")
        mem_lines.append(f"necessity_audit: {json.dumps(necessity_audit.get(nid, {}), ensure_ascii=False)}")
        mem_lines.append(f"input_example: {json.dumps(node.get('input_example'), ensure_ascii=False)}")
        mem_lines.append(f"output_example: {json.dumps(node.get('output_example'), ensure_ascii=False)}")
        mem_lines.append(f"actual_input: {json.dumps(actual_io.get(nid, {}).get('inputs'), ensure_ascii=False)}")
        mem_lines.append(f"actual_output: {json.dumps(actual_io.get(nid, {}).get('outputs'), ensure_ascii=False)}")
        mem_lines.append(f"io_comparison: {json.dumps(io_comparison.get(nid, {}), ensure_ascii=False)}")
        mem_lines.append(f"audit_report: {json.dumps(report, ensure_ascii=False)}")
        mem_lines.append(f"evidence_pointer: {report.get('evidence_pointer', [])}")
        mem_path = _write_module_memory(output_dir, nid, "\n".join(mem_lines))
        module_memories[nid] = mem_path
        lines.append(f"- {nid}: {mem_path}")
    lines.append("")

    lines.append("Compressed judgment sentences:")
    if ok:
        lines.append("- [judgment] Output satisfies 10 cities, 100 unique items, unique scores 1-100, non-empty fields.")
    else:
        lines.append("- [judgment] Output failed validation checks; see audit issues above.")
        for issue in issues:
            lines.append(f"- [judgment] {issue}")
    lines.append("- [evidence] result.txt")
    lines.append("")

    log.append(f"{datetime.now().isoformat()} result_validation={ok}")
    log.append(f"{datetime.now().isoformat()} audit_agent_nodes={len(audit_nodes)}")
    log.append(f"{datetime.now().isoformat()} module_memories={len(module_memories)}")
    log.append(f"{datetime.now().isoformat()} write_result={output_path}")

    lines.append("Run log:")
    for entry in log:
        lines.append(f"- {entry}")

    output_path.write_text("\n".join(lines), encoding="utf-8")

    save_memory(
        MemoryEntry(
            name="city_famous_tree_judgment",
            description="Judgment sentence for city-famous-tree example run",
            type="project",
            content=f"Judgment: city-famous-tree generation\nStatus: {'pass' if ok else 'fail'}\nEvidence: {output_path}",
            created="",
            source="tool",
        ),
        scope="project",
    )

    print(f"Wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
