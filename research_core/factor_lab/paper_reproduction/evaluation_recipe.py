from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


IC_RECIPE_SCHEMA_VERSION = "paper_extraction.ic_recipe.v3"
GLOBAL_EVALUATION_POLICY_ID = "china_a_share_ic_evaluation_v1"


GLOBAL_EVALUATION_POLICY: dict[str, Any] = {
    "policy_id": GLOBAL_EVALUATION_POLICY_ID,
    "application_order": 1,
    "application_stage": "evaluation_before_truth_source_recipe",
    "filters": [
        {
            "method_id": "eligibility.exclude_st_pt",
            "semantic_input": "st_or_pt_status",
            "effective_date_rule": "signal_date_t",
            "missing_policy": "exclude",
        },
        {
            "method_id": "eligibility.exclude_next_trading_day_suspension",
            "semantic_input": "next_day_suspension_status",
            "effective_date_rule": "next_exchange_trading_day_t_plus_1",
            "missing_policy": "exclude",
        },
    ],
    "non_factor_missing_defaults": {
        "neutralization_control": "complete_case_regression_and_missing_residual",
        "return_label": "pairwise_drop_at_ic",
        "eligibility_status": "exclude",
        "invalid_security_or_date_key": "block_execution",
    },
}


METHOD_CATALOG: dict[str, dict[str, Any]] = {
    "factor_missing.drop": {"category": "factor_missing", "executor_support": "native"},
    "factor_missing.fill_zero": {"category": "factor_missing", "executor_support": "native"},
    "factor_missing.use_previous_exchange_day": {
        "category": "factor_missing",
        "executor_support": "native",
        "required_parameters": {"maximum_age_exchange_days": 1},
    },
    "factor_missing.none": {"category": "factor_missing", "executor_support": "native"},
    "winsorize.median_mad": {"category": "winsorize", "executor_support": "native"},
    "transform.natural_log": {"category": "transform", "executor_support": "native"},
    "neutralize.cross_sectional_regression_residual": {
        "category": "neutralize",
        "executor_support": "native",
    },
    "standardize.cross_sectional_zscore": {"category": "standardize", "executor_support": "native"},
    "return.forward_close_to_close": {"category": "return_label", "executor_support": "native"},
    "ic.spearman_rank": {"category": "ic", "executor_support": "native"},
    "ic.pearson": {"category": "ic", "executor_support": "native"},
    "metric.rank_ic_mean": {"category": "metric", "executor_support": "native"},
    "metric.ic_mean": {"category": "metric", "executor_support": "native"},
    "metric.rank_ic_std": {"category": "metric", "executor_support": "native"},
    "metric.ic_std": {"category": "metric", "executor_support": "native"},
    "metric.ic_ir": {"category": "metric", "executor_support": "native"},
    "metric.rank_ic_ir": {"category": "metric", "executor_support": "native"},
    "metric.ic_positive_ratio": {"category": "metric", "executor_support": "native"},
    "metric.rank_ic_positive_ratio": {"category": "metric", "executor_support": "native"},
}


@dataclass(slots=True)
class DataValueState:
    physical_field: str
    semantic_concept: str
    unit: str = ""
    price_basis: str = ""
    value_space: str = "unknown"
    transform_chain: list[str] = field(default_factory=list)
    temporal_semantics: str = ""
    source: str = ""


def validate_evaluation_recipe(recipe: dict[str, Any], *, prefix: str = "evaluation_recipe") -> list[str]:
    errors: list[str] = []
    if str(recipe.get("global_policy_ref", "")) != GLOBAL_EVALUATION_POLICY_ID:
        errors.append(f"{prefix}.global_policy_ref must be {GLOBAL_EVALUATION_POLICY_ID!r}")
    steps = recipe.get("preprocessing_steps", [])
    if not isinstance(steps, list):
        return [f"{prefix}.preprocessing_steps must be a list"]
    orders = [step.get("order") for step in steps if isinstance(step, dict)]
    if len(orders) != len(steps) or orders != list(range(1, len(steps) + 1)):
        errors.append(f"{prefix}.preprocessing_steps must have contiguous one-based order")
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"{prefix}.preprocessing_steps[{index}] must be an object")
            continue
        method_id = str(step.get("method_id", ""))
        if not method_id:
            errors.append(f"{prefix}.preprocessing_steps[{index}].method_id is required")
        elif method_id not in METHOD_CATALOG and method_id != "custom.paper_defined":
            errors.append(f"{prefix}.preprocessing_steps[{index}].method_id is unknown: {method_id}")
        if method_id == "custom.paper_defined" and not (
            step.get("source_text") and step.get("evidence")
        ):
            errors.append(
                f"{prefix}.preprocessing_steps[{index}] custom method requires source_text and evidence"
            )
    for section, category in (("return_label", "return_label"), ("ic_method", "ic")):
        value = recipe.get(section, {})
        method_id = str(value.get("method_id", "")) if isinstance(value, dict) else ""
        if not method_id:
            errors.append(f"{prefix}.{section}.method_id is required")
        elif method_id == "custom.paper_defined":
            if not isinstance(value, dict) or not (value.get("source_text") and value.get("evidence")):
                errors.append(f"{prefix}.{section} custom method requires source_text and evidence")
        elif METHOD_CATALOG.get(method_id, {}).get("category") != category:
            errors.append(f"{prefix}.{section}.method_id has wrong or unknown category: {method_id}")
    metrics = recipe.get("metric_methods", [])
    if not isinstance(metrics, list) or not metrics:
        errors.append(f"{prefix}.metric_methods must not be empty")
    else:
        for index, metric in enumerate(metrics):
            method_id = str(metric.get("method_id", "")) if isinstance(metric, dict) else str(metric)
            if method_id == "custom.paper_defined":
                if not isinstance(metric, dict) or not (metric.get("source_text") and metric.get("evidence")):
                    errors.append(f"{prefix}.metric_methods[{index}] custom method requires source_text and evidence")
            elif METHOD_CATALOG.get(method_id, {}).get("category") != "metric":
                errors.append(f"{prefix}.metric_methods[{index}] is unknown: {method_id}")
    return errors


def recipe_required_semantic_inputs(recipe: dict[str, Any]) -> dict[str, list[str]]:
    controls: list[str] = []
    for step in recipe.get("preprocessing_steps", []) or []:
        if not isinstance(step, dict):
            continue
        for control in step.get("controls", []) or []:
            if isinstance(control, dict):
                value = control.get("semantic_input") or control.get("semantic_concept")
            else:
                value = control
            if value and str(value) not in controls:
                controls.append(str(value))
    return {
        "evaluation": [
            str((recipe.get("return_label", {}) or {}).get("output_field") or _default_return_field(recipe))
        ],
        "controls": controls,
        "universe_filter": ["st_or_pt_status", "next_day_suspension_status"],
    }


def project_recipe_truth_source_for_factor(source: dict[str, Any], factor_id: str) -> dict[str, Any]:
    recipe = copy.deepcopy(source.get("evaluation_recipe", {}) or {})
    metrics = copy.deepcopy((source.get("reported_results", {}) or {}).get(factor_id, {}))
    truth_id = str(source.get("truth_source_id", ""))
    ic_method_id = str((recipe.get("ic_method", {}) or {}).get("method_id", "ic.spearman_rank"))
    return_label = recipe.get("return_label", {}) or {}
    return_col = str(return_label.get("output_field") or _default_return_field(recipe))
    sampling = recipe.get("sampling", {}) or {}
    return {
        "truth_id": truth_id,
        "truth_source_id": truth_id,
        "truth_type": "evaluation_results",
        "description": f"{factor_id} results from {truth_id}",
        "source_location": _format_source_location(source.get("source", {}) or {}),
        "source": copy.deepcopy(source.get("source", {}) or {}),
        "sample_period": _format_sample_period(sampling),
        "universe": str((sampling.get("universe", {}) or {}).get("description", "")),
        "frequency": str(sampling.get("signal_schedule", "")),
        "evaluation_method": "Spearman rank correlation" if ic_method_id == "ic.spearman_rank" else "Pearson correlation",
        "evaluation_family": "ic_analysis",
        "evaluation_recipe": recipe,
        "evaluation_spec": {
            "return_horizon": int(return_label.get("horizon_exchange_days", 1)),
            "return_horizon_unit": "trading_day",
            "return_col": return_col,
            "ic_type": "spearman_rank_ic" if ic_method_id == "ic.spearman_rank" else "pearson_ic",
            "ic_ir_convention": str((recipe.get("ic_method", {}) or {}).get("ic_ir_convention", "signed")),
            "signal_schedule": sampling.get("signal_schedule", "every_trading_day"),
        },
        "required_data": recipe_required_semantic_inputs(recipe),
        "metrics": metrics,
        "metric_definitions": copy.deepcopy(source.get("metric_definitions", {}) or {}),
        "paper_protocol": {"evaluation_recipe": copy.deepcopy(recipe)},
        "paper_protocol_refs": {
            "schema_version": IC_RECIPE_SCHEMA_VERSION,
            "truth_source_id": truth_id,
        },
        "global_policy_ref": recipe.get("global_policy_ref"),
        "selection_stage": 1,
        "truth_match_eligible_by_extraction": True,
        "notes": list(source.get("notes", []) or []),
    }


def resolve_recipe_value_states(
    recipe: dict[str, Any],
    data_profile: dict[str, Any],
) -> dict[str, Any]:
    """Bind recipe inputs to physical fields and prevent duplicate materialized transforms."""

    resolved = copy.deepcopy(recipe)
    states = _value_states_from_profile(data_profile)
    bindings = _semantic_bindings_from_profile(data_profile)
    resolved["global_policy_bindings"] = {
        semantic: bindings.get(semantic, semantic)
        for semantic in ("st_or_pt_status", "next_day_suspension_status")
    }
    blocked: list[str] = []
    trace: list[dict[str, Any]] = []
    for step in resolved.get("preprocessing_steps", []) or []:
        if not isinstance(step, dict):
            continue
        method_id = str(step.get("method_id", ""))
        if method_id == "neutralize.cross_sectional_regression_residual":
            for control in step.get("controls", []) or []:
                if not isinstance(control, dict):
                    continue
                semantic = str(control.get("semantic_input") or control.get("semantic_concept") or "")
                physical = str(control.get("resolved_field") or bindings.get(semantic) or semantic)
                control["resolved_field"] = physical
                if physical in states:
                    control["data_value_state"] = states[physical]
                for transform in control.get("transforms", []) or []:
                    _resolve_transform_execution(transform, physical, states, blocked, trace)
        target_semantic = str(step.get("semantic_input") or "factor_exposure")
        physical = str(step.get("resolved_field") or bindings.get(target_semantic) or target_semantic)
        if method_id == "transform.natural_log":
            if target_semantic == "factor_exposure":
                step["execution_mode"] = "apply"
                trace.append({
                    "order": step.get("order"),
                    "method_id": method_id,
                    "physical_field": "runtime_factor_exposure",
                    "execution_mode": "apply",
                })
            else:
                _resolve_transform_execution(step, physical, states, blocked, trace)
        else:
            step.setdefault("execution_mode", "apply")
            trace.append({"order": step.get("order"), "method_id": method_id, "execution_mode": step["execution_mode"]})
    resolved["resolution"] = {
        "status": "blocked" if blocked else "resolved",
        "blocked_reasons": blocked,
        "value_states": states,
        "execution_trace": trace,
    }
    return resolved


def _resolve_transform_execution(
    transform: dict[str, Any],
    physical_field: str,
    states: dict[str, dict[str, Any]],
    blocked: list[str],
    trace: list[dict[str, Any]],
) -> None:
    method_id = str(transform.get("method_id", ""))
    state = states.get(physical_field)
    mode = "apply"
    if method_id == "transform.natural_log":
        if not state:
            mode = "blocked_unknown_state"
        else:
            chain = [str(item) for item in state.get("transform_chain", []) or []]
            value_space = str(state.get("value_space", "unknown"))
            if chain == ["transform.natural_log"] or value_space == "log_level":
                mode = "reuse_materialized"
            elif chain or value_space not in {"level", "raw_level"}:
                mode = "incompatible" if chain else "blocked_unknown_state"
    transform["execution_mode"] = mode
    transform["resolved_field"] = physical_field
    if state:
        transform["data_value_state"] = state
    if mode in {"blocked_unknown_state", "incompatible"}:
        blocked.append(f"{method_id} on {physical_field}: {mode}")
    trace.append({
        "order": transform.get("order"),
        "method_id": method_id,
        "physical_field": physical_field,
        "execution_mode": mode,
    })


def _value_states_from_profile(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    conventions = profile.get("conventions", {}) if isinstance(profile.get("conventions", {}), dict) else {}
    declared = conventions.get("data_value_states", {})
    states: dict[str, dict[str, Any]] = {
        str(field): dict(value)
        for field, value in (declared.items() if isinstance(declared, dict) else [])
        if isinstance(value, dict)
    }
    for item in profile.get("derived_fields", []) or []:
        if not isinstance(item, dict) or not item.get("field"):
            continue
        field_name = str(item["field"])
        method = str(item.get("method") or (item.get("derivation", {}) or {}).get("method") or "")
        chain = list(item.get("transform_chain", []) or [])
        if not chain and method in {"log", "ln", "natural_log", "transform.natural_log"}:
            chain = ["transform.natural_log"]
        states.setdefault(field_name, {
            "physical_field": field_name,
            "semantic_concept": str(item.get("semantic_concept") or item.get("concept") or field_name),
            "unit": str(item.get("unit", "")),
            "price_basis": str(item.get("price_basis", "")),
            "value_space": str(item.get("value_space") or ("log_level" if chain == ["transform.natural_log"] else "unknown")),
            "transform_chain": chain,
            "temporal_semantics": str(item.get("temporal_semantics", "")),
            "source": "data_profile.derived_fields",
        })
    lineage = conventions.get("market_cap_lineage", {})
    if isinstance(lineage, dict):
        for field_name, item in lineage.items():
            if not isinstance(item, dict):
                continue
            states.setdefault(str(field_name), {
                "physical_field": str(field_name),
                "semantic_concept": str(item.get("semantic_concept") or field_name),
                "unit": str(item.get("unit", "CNY")),
                "price_basis": str(item.get("price_basis", "unadjusted")),
                "value_space": str(item.get("value_space", "level")),
                "transform_chain": list(item.get("transform_chain", []) or []),
                "temporal_semantics": str(item.get("temporal_semantics", "point_in_time_daily")),
                "source": "conventions.market_cap_lineage",
            })
    return states


def _semantic_bindings_from_profile(profile: dict[str, Any]) -> dict[str, str]:
    conventions = profile.get("conventions", {}) if isinstance(profile.get("conventions", {}), dict) else {}
    raw = conventions.get("semantic_bindings", {})
    bindings = {str(key): str(value) for key, value in raw.items()} if isinstance(raw, dict) else {}
    columns = {str(value) for value in profile.get("columns", []) or []}
    for relationship in profile.get("field_relationships", []) or []:
        if not isinstance(relationship, dict):
            continue
        semantic = str(relationship.get("paper_field", ""))
        physical = str(relationship.get("physical_field", ""))
        relation = str(relationship.get("relationship", ""))
        if semantic and physical in columns and relation != "unsupported_substitute":
            bindings.setdefault(semantic, physical)
    aliases = {
        "market_cap": ("market_cap", "market_cap_3", "total_market_cap"),
        "total_market_cap": ("total_market_cap", "market_cap", "market_cap_3"),
        "circulating_market_cap": ("circulating_market_cap", "market_cap_2"),
        "industry": ("industry", "industry_code", "citics_industry"),
        "beta": ("beta", "market_beta"),
        "st_or_pt_status": ("is_st", "st_or_pt_status"),
        "next_day_suspension_status": ("next_is_suspended", "next_day_suspension_status"),
    }
    for semantic, candidates in aliases.items():
        if semantic not in bindings:
            match = next((candidate for candidate in candidates if candidate in columns), None)
            if match:
                bindings[semantic] = match
    return bindings


def _default_return_field(recipe: dict[str, Any]) -> str:
    horizon = int(((recipe.get("return_label", {}) or {}).get("horizon_exchange_days", 1)))
    return f"forward_return_{horizon}d"


def _format_source_location(source: dict[str, Any]) -> str:
    parts: list[str] = []
    if source.get("page") is not None:
        parts.append(f"page {source['page']}")
    for key in ("table", "row_block", "section", "locator"):
        if source.get(key):
            parts.append(str(source[key]))
    return ", ".join(parts)


def _format_sample_period(sampling: dict[str, Any]) -> str:
    start, end = sampling.get("start"), sampling.get("end")
    if start and end:
        return f"{start} to {end}"
    return str(sampling.get("description", ""))
