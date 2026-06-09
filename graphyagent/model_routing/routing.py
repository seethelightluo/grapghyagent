"""Provider/model routing for GraphyAgent node execution."""
from __future__ import annotations

import os
from typing import Any

from ..core.types import GraphConfig, GraphState, ModelSpec, NodeSpec, ProviderSpec, RouteDecision


_TIER_ORDER = {
    "cheap": 0,
    "standard": 1,
    "expensive": 2,
}

_COMPLEX_TASK_TYPES = {
    "analysis",
    "audit",
    "code",
    "data_audit",
    "reasoning",
    "research",
    "eval",
    "evaluation",
    "planning",
    "llm",
    "validation",
    "verification",
}


def parse_model_ref(model_ref: str | None) -> tuple[str | None, str | None]:
    if not model_ref:
        return None, None
    if ":" not in model_ref:
        return None, model_ref
    provider_id, model_id = model_ref.split(":", 1)
    return provider_id or None, model_id or None


def route_model(
    config: GraphConfig,
    node: NodeSpec,
    state: GraphState | None = None,
) -> RouteDecision:
    """Choose a provider/model for a node without performing an LLM call."""
    explicit = (
        node.model_ref
        or node.routing.get("model_ref")
        or node.metadata.get("model_ref")
        or node.executor.get("model_ref")
    )
    if explicit:
        return _decision_from_ref(explicit, "explicit_override", node)

    router = config.router
    complexity = _classify_complexity(node, state)
    env_route = _env_route_value(complexity)
    if env_route:
        return _decision_from_ref(env_route, f"env:{complexity}", node)

    if router.strategy == "static":
        forced = router.default_model_ref or _route_value(router.routes.get("default"))
        return _decision_from_ref(forced, "static_default", node)

    task_type_route = _task_type_route(router.routes, node.task_type)
    if task_type_route:
        return _decision_from_ref(task_type_route, f"task_type:{node.task_type}", node)

    if router.strategy in {"simple_vs_complex", "complexity", "task_type_based"}:
        route = _route_value(router.routes.get(complexity))
        if route:
            return _decision_from_ref(route, complexity, node)

    fallback = router.default_model_ref or _select_provider_model(
        config.providers,
        complexity=complexity,
        task_type=node.task_type,
        max_tier=router.max_tier,
        cost_preference=router.cost_preference,
    )
    if fallback:
        return _decision_from_ref(fallback, f"default:{complexity}", node)

    return RouteDecision(
        routing_reason="unrouted",
        parameters=_sampling_parameters(node, None),
    )


def classify_node_complexity(node: NodeSpec, state: GraphState | None = None) -> str:
    """Classify a node as simple or complex using the router's current rules."""
    return _classify_complexity(node, state)


def _env_route_value(complexity: str) -> str | None:
    if complexity == "simple":
        return (
            os.environ.get("GRAPHYAGENT_SIMPLE_MODEL_REF")
            or os.environ.get("GRAPHYAGENT_DEFAULT_MODEL_REF")
        )
    if complexity == "complex":
        return (
            os.environ.get("GRAPHYAGENT_COMPLEX_MODEL_REF")
            or os.environ.get("GRAPHYAGENT_DEFAULT_MODEL_REF")
        )
    return os.environ.get("GRAPHYAGENT_DEFAULT_MODEL_REF")


def _decision_from_ref(
    model_ref: str | None,
    reason: str,
    node: NodeSpec,
) -> RouteDecision:
    provider_id, model_id = parse_model_ref(model_ref)
    return RouteDecision(
        provider_id=provider_id,
        model_id=model_id,
        model_ref=model_ref,
        routing_reason=reason,
        parameters=_sampling_parameters(node, reason),
    )


def _task_type_route(routes: dict[str, Any], task_type: str | None) -> str | None:
    if not task_type:
        return None
    task_routes = routes.get("task_types") or routes.get("tasks") or {}
    if isinstance(task_routes, dict):
        return _route_value(task_routes.get(task_type))
    return None


def _route_value(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        route = value.get("model_ref") or value.get("model")
        if route:
            return str(route)
        provider = value.get("provider_id") or value.get("provider")
        model = value.get("model_id") or value.get("model")
        if provider and model:
            return f"{provider}:{model}"
        if model:
            return str(model)
    return None


def _classify_complexity(node: NodeSpec, state: GraphState | None) -> str:
    explicit = (
        node.routing.get("complexity")
        or node.metadata.get("complexity")
        or node.executor.get("complexity")
    )
    if explicit:
        normalized = str(explicit).lower()
        if normalized in {"simple", "cheap", "low"}:
            return "simple"
        if normalized in {"complex", "hard", "high"}:
            return "complex"
    if node.task_type and node.task_type.lower() in _COMPLEX_TASK_TYPES:
        return "complex"
    context_size = len(str((state.context if state else {}) or {}))
    if context_size > 8000:
        return "complex"
    return "simple"


def _select_provider_model(
    providers: list[ProviderSpec],
    complexity: str,
    task_type: str | None,
    max_tier: str | None,
    cost_preference: str,
) -> str | None:
    candidates: list[tuple[int, str, ModelSpec]] = []
    max_tier_value = _TIER_ORDER.get(str(max_tier), 99) if max_tier else 99
    for provider in providers:
        for model in provider.models:
            tier_value = _TIER_ORDER.get(model.tier, 1)
            if tier_value > max_tier_value:
                continue
            capability_score = 0
            capabilities = {cap.lower() for cap in model.capabilities}
            if task_type and task_type.lower() in capabilities:
                capability_score += 10
            if complexity == "complex" and (
                "reasoning" in capabilities or "long_context" in capabilities
            ):
                capability_score += 5
            if complexity == "simple" and (
                model.tier == "cheap" or "simple_chat" in capabilities
            ):
                capability_score += 5
            tier_score = _tier_score(model.tier, cost_preference, complexity)
            candidates.append((capability_score + tier_score, provider.provider_id, model))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, provider_id, model = candidates[0]
    return f"{provider_id}:{model.model_id}"


def _tier_score(tier: str, cost_preference: str, complexity: str) -> int:
    tier_value = _TIER_ORDER.get(tier, 1)
    if cost_preference == "quality":
        return tier_value
    if cost_preference == "cheap":
        return 2 - tier_value
    if complexity == "complex":
        return tier_value
    return 2 - tier_value


def _sampling_parameters(node: NodeSpec, reason: str | None) -> dict[str, Any]:
    parameters = dict(node.routing.get("parameters") or {})
    if "temperature" not in parameters and reason:
        parameters["temperature"] = 0.2 if "complex" in reason or "code" in reason else 0.5
    if "max_tokens" not in parameters and reason and "complex" in reason:
        try:
            parameters["max_tokens"] = int(os.environ.get("GRAPHYAGENT_COMPLEX_MAX_TOKENS") or 8192)
        except ValueError:
            parameters["max_tokens"] = 8192
    return parameters
