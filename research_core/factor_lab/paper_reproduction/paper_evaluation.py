from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from contracts.factor_research import FactorResearchSpec
from research_core.factor_lab.paper_reproduction.data_validation import assess_evaluation_case_support
from research_core.factor_lab.paper_reproduction.evaluators import evaluator_capabilities_for_case

GENERIC_EVALUATION_FAMILIES = {"ic_analysis", "ic_regression"}
EVALUATION_METHOD_PRIORITY = {
    "ic_analysis": 10,
    "ic_regression": 20,
    "regression_t_test": 30,
    "wls_regression": 30,
    "ols_regression": 30,
    "ic_decay": 40,
    "layered_portfolio_backtest": 50,
    "custom": 90,
}
EVALUATION_FAMILY_ALIASES = {
    "regression_t_test": "ic_regression",
    "wls_regression": "ic_regression",
    "ols_regression": "ic_regression",
}
MAX_EVALUATION_METHODS_PER_RUN = 2


@dataclass(slots=True)
class PaperFactorEvaluationPlan:
    factor_name: str
    status: str
    evaluation_method: str = ""
    required_metrics: list[str] = field(default_factory=list)
    evaluation_features: list[str] = field(default_factory=list)
    forward_return_periods: list[int] = field(default_factory=list)
    truth_source_ids: list[str] = field(default_factory=list)
    evaluation_cases: list[dict[str, Any]] = field(default_factory=list)
    assessed_evaluation_cases: list[dict[str, Any]] = field(default_factory=list)
    selected_evaluation_cases: list[dict[str, Any]] = field(default_factory=list)
    skipped_evaluation_cases: list[dict[str, Any]] = field(default_factory=list)
    unsupported_evaluation_cases: list[dict[str, Any]] = field(default_factory=list)
    deferred_evaluation_cases: list[dict[str, Any]] = field(default_factory=list)
    requires_paper_local_evaluator: bool = False
    evaluator_implementation_targets: list[dict[str, Any]] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PaperEvaluationPlan:
    library: str
    status: str
    factor_plans: list[PaperFactorEvaluationPlan]
    notes: list[str] = field(default_factory=list)


def build_paper_evaluation_plan(
    specs: list[FactorResearchSpec],
    *,
    data_profiles: dict[str, dict[str, Any]] | None = None,
) -> PaperEvaluationPlan:
    if not specs:
        raise ValueError("At least one FactorResearchSpec is required to build a paper evaluation plan.")
    factor_plans = [_build_factor_evaluation_plan(spec, data_profiles=data_profiles or {}) for spec in specs]
    statuses = {plan.status for plan in factor_plans}
    if "needs_human_review" in statuses:
        status = "needs_human_review"
    elif statuses == {"ready_for_evaluation"}:
        status = "ready_for_evaluation"
    elif statuses <= {"ready_for_evaluation", "ready_for_evaluation_with_limitations"}:
        status = "ready_for_evaluation_with_limitations"
    else:
        status = "mixed"
    return PaperEvaluationPlan(library=specs[0].library, status=status, factor_plans=factor_plans)


def _build_factor_evaluation_plan(
    spec: FactorResearchSpec,
    *,
    data_profiles: dict[str, dict[str, Any]],
) -> PaperFactorEvaluationPlan:
    selected_truth_sources = _candidate_truth_sources(spec)
    evaluation_truth_sources = [
        source
        for source in selected_truth_sources
        if isinstance(source, dict) and source.get("truth_type") == "evaluation_results"
    ]
    metrics: list[str] = []
    truth_ids: list[str] = []
    methods: list[str] = []
    cases = [_evaluation_case_from_truth_source(source) for source in evaluation_truth_sources]
    for source in evaluation_truth_sources:
        truth_ids.append(str(source.get("truth_id", "")))
        source_metrics = source.get("metrics", {})
        if isinstance(source_metrics, dict):
            for metric in source_metrics:
                if metric not in metrics:
                    metrics.append(str(metric))
        method = str(source.get("evaluation_method", "")).strip()
        if method:
            methods.append(method)

    spec_method = str(spec.metadata.get("evaluation_method", "")).strip()
    evaluation_method = methods[0] if methods else spec_method
    blocked_reasons: list[str] = []
    if evaluation_truth_sources and not evaluation_method:
        blocked_reasons.append("paper evaluation method is missing")
    if evaluation_truth_sources and not metrics:
        blocked_reasons.append("paper evaluation metrics are missing")

    profile = data_profiles.get(spec.factor_name) or data_profiles.get("*")
    (
        assessed_cases,
        selected_cases,
        skipped_cases,
        unsupported_cases,
        deferred_cases,
        implementation_targets,
    ) = _select_evaluation_cases(cases, data_profile=profile)
    requires_paper_local_evaluator = bool(implementation_targets)

    if blocked_reasons:
        status = "needs_human_review"
    elif skipped_cases or unsupported_cases or deferred_cases or any(case.get("comparability") != "exact" for case in selected_cases):
        status = "ready_for_evaluation_with_limitations"
    else:
        status = "ready_for_evaluation"
    return PaperFactorEvaluationPlan(
        factor_name=spec.factor_name,
        status=status,
        evaluation_method=evaluation_method,
        required_metrics=metrics,
        evaluation_features=_evaluation_features(evaluation_method, metrics),
        forward_return_periods=_forward_return_periods(evaluation_method),
        truth_source_ids=[truth_id for truth_id in truth_ids if truth_id],
        evaluation_cases=cases,
        assessed_evaluation_cases=assessed_cases,
        selected_evaluation_cases=selected_cases,
        skipped_evaluation_cases=skipped_cases,
        unsupported_evaluation_cases=unsupported_cases,
        deferred_evaluation_cases=deferred_cases,
        requires_paper_local_evaluator=requires_paper_local_evaluator,
        evaluator_implementation_targets=implementation_targets,
        blocked_reasons=blocked_reasons,
    )


def _evaluation_case_from_truth_source(source: dict[str, Any]) -> dict[str, Any]:
    raw_family = str(source.get("evaluation_family", "") or _infer_evaluation_family(source))
    family = _normalize_evaluation_family(raw_family)
    truth_id = str(source.get("truth_id", ""))
    universe_protocol = _universe_protocol_from_source(source)
    paper_evaluation_spec = dict(
        source.get("evaluation_spec", {}) if isinstance(source.get("evaluation_spec", {}), dict) else {}
    )
    paper_required_data = dict(
        source.get("required_data", {}) if isinstance(source.get("required_data", {}), dict) else {}
    )
    runtime_evaluation_spec, runtime_required_data = _canonical_runtime_evaluation_inputs(
        paper_evaluation_spec,
        paper_required_data,
        family=family,
    )
    return {
        "truth_case_id": truth_id,
        "truth_id": truth_id,
        "source_truth_id": truth_id,
        "evaluation_family": family,
        "raw_evaluation_family": raw_family,
        "evaluation_method": str(source.get("evaluation_method", "")),
        "sample_period": str(source.get("sample_period", "")),
        "universe": str(source.get("universe", "")),
        "frequency": str(source.get("frequency", "")),
        "evaluation_spec": runtime_evaluation_spec,
        "transform_spec": dict(source.get("transform_spec", {}) if isinstance(source.get("transform_spec", {}), dict) else {}),
        "neutralization_spec": dict(
            source.get("neutralization_spec", {}) if isinstance(source.get("neutralization_spec", {}), dict) else {}
        ),
        "universe_protocol": universe_protocol,
        "required_data": runtime_required_data,
        "metrics": dict(source.get("metrics", {}) if isinstance(source.get("metrics", {}), dict) else {}),
        "source_location": str(source.get("source_location", "")),
        "paper_protocol": {
            "evaluation_method": str(source.get("evaluation_method", "")),
            "sample_period": str(source.get("sample_period", "")),
            "universe": str(source.get("universe", "")),
            "frequency": str(source.get("frequency", "")),
            "evaluation_spec": paper_evaluation_spec,
            "required_data": paper_required_data,
            "transform_spec": dict(source.get("transform_spec", {}) if isinstance(source.get("transform_spec", {}), dict) else {}),
            "neutralization_spec": dict(
                source.get("neutralization_spec", {}) if isinstance(source.get("neutralization_spec", {}), dict) else {}
            ),
            "universe_protocol": universe_protocol,
            "paper_protocol_refs": dict(source.get("paper_protocol_refs", {}) or {}),
            "protocol_id": str(source.get("protocol_id", "")),
            "operation_pipeline_id": str(source.get("operation_pipeline_id", "")),
            "operation_pipeline": dict(
                source.get("operation_pipeline", {})
                if isinstance(source.get("operation_pipeline", {}), dict)
                else {}
            ),
            "semantic_requirements": list(source.get("semantic_requirements", []) or []),
        },
        "truth_source_id": str(source.get("truth_source_id") or truth_id),
        "protocol_id": str(source.get("protocol_id", "")),
        "operation_pipeline_id": str(source.get("operation_pipeline_id", "")),
        "paper_protocol_refs": dict(source.get("paper_protocol_refs", {}) or {}),
        "semantic_requirements": list(source.get("semantic_requirements", []) or []),
        "operation_capability_requirements": list(source.get("operation_capability_requirements", []) or []),
        "conflict_group_id": source.get("conflict_group_id"),
        "paper_truth_conflict": bool(source.get("paper_truth_conflict", False)),
        "paper_truth_conflict_status": str(source.get("paper_truth_conflict_status", "none")),
    }


def _canonical_runtime_evaluation_inputs(
    evaluation_spec: dict[str, Any],
    required_data: dict[str, Any],
    *,
    family: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime_spec = copy.deepcopy(evaluation_spec)
    runtime_required = copy.deepcopy(required_data)
    if family not in {"ic_analysis", "ic_regression"}:
        return runtime_spec, runtime_required
    horizon = runtime_spec.get("return_horizon")
    if horizon in (None, ""):
        horizon = runtime_spec.get("return_horizon_days")
    if horizon in (None, ""):
        horizon = runtime_spec.get("rebalance_days")
    try:
        horizon_int = int(horizon) if horizon not in (None, "") else 0
    except (TypeError, ValueError):
        horizon_int = 0
    if horizon_int > 0:
        runtime_spec["return_horizon"] = horizon_int
        unit = str(runtime_spec.get("forward_horizon_unit") or runtime_spec.get("return_horizon_unit") or "trading_day")
        unit = unit.strip().lower()
        if unit == "calendar_month":
            unit = "natural_month"
        runtime_spec["return_horizon_unit"] = unit
        runtime_spec.setdefault(
            "return_col",
            f"forward_return_{horizon_int}{'m' if unit == 'natural_month' else 'd'}",
        )
    return_col = str(runtime_spec.get("return_col", "") or "")
    if return_col:
        evaluation_fields = runtime_required.get("evaluation", []) or []
        if not isinstance(evaluation_fields, list):
            evaluation_fields = [evaluation_fields]
        runtime_required["evaluation"] = list(
            dict.fromkeys([*(str(value) for value in evaluation_fields if value), return_col])
        )
    return runtime_spec, runtime_required


def _universe_protocol_from_source(source: dict[str, Any]) -> dict[str, Any]:
    declared = source.get("universe_protocol", {})
    if isinstance(declared, dict) and declared:
        return copy.deepcopy(declared)
    universe = str(source.get("universe", "") or "")
    text = universe.lower()
    exclusion_tokens = ("exclude", "exclusion", "remove", "剔除", "排除", "不含")
    if not any(token in text for token in exclusion_tokens):
        return {}
    filters: list[dict[str, Any]] = []
    if "st" in text or "pt" in text:
        filters.append(
            {
                "filter_name": "exclude_st_pt",
                "paper_field": "st_or_pt_status",
                "application_stage": "factor_cross_section",
                "effective_date_rule": "signal_date_t",
                "operator": "falsy",
                "missing_policy": "exclude",
                "source": "inferred",
                "confidence": 0.9,
                "reason": "Universe text excludes ST/PT securities; apply only after factor time-series calculation.",
            }
        )
    if any(token in text for token in ("suspend", "suspension", "停牌")):
        next_day = any(token in text for token in ("next-day", "next day", "next trading day", "次日", "下一交易日"))
        filters.append(
            {
                "filter_name": "exclude_next_day_suspension" if next_day else "exclude_suspension",
                "paper_field": "next_day_suspension_status" if next_day else "suspension_status",
                "application_stage": "factor_cross_section",
                "effective_date_rule": "next_trading_day_t_plus_1" if next_day else "signal_date_t",
                "operator": "falsy",
                "missing_policy": "exclude",
                "source": "inferred",
                "confidence": 0.85,
                "reason": "Universe text excludes suspended securities; apply only to evaluation eligibility.",
            }
        )
    if not filters:
        return {}
    return {
        "calculation_universe": {
            "description": "retain complete valid security history for factor calculation",
            "source": "defaulted",
            "confidence": 1.0,
        },
        "evaluation_universe": {
            "description": universe,
            "source": "explicit",
            "confidence": 1.0,
        },
        "filters": filters,
    }


def _select_evaluation_cases(
    cases: list[dict[str, Any]],
    *,
    data_profile: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    valid_cases: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for case in cases:
        if not str(case.get("evaluation_method", "")).strip():
            skipped.append(_case_with_skip_reason(case, "missing_or_ambiguous_method"))
        else:
            valid_cases.append(case)

    if data_profile is not None:
        return _select_evaluation_cases_by_support(valid_cases, skipped, data_profile=data_profile)

    if any(case.get("paper_protocol_refs") for case in valid_cases):
        unresolved = [
            _case_with_lifecycle(
                _case_with_skip_reason(case, "stage_3_support_assessment_required"),
                "insufficient_data",
            )
            for case in valid_cases
        ]
        skipped.extend(unresolved)
        return [], [], skipped, unresolved, [], []

    ordered = sorted(valid_cases, key=_case_priority)
    generic_cases = [case for case in ordered if case.get("evaluation_family") in GENERIC_EVALUATION_FAMILIES]
    unsupported_cases = [case for case in ordered if case.get("evaluation_family") not in GENERIC_EVALUATION_FAMILIES]

    if generic_cases:
        selected = generic_cases[:MAX_EVALUATION_METHODS_PER_RUN]
        skipped.extend(
            _case_with_skip_reason(case, "method_budget_exceeded")
            for case in generic_cases[MAX_EVALUATION_METHODS_PER_RUN:]
        )
        skipped.extend(_case_with_skip_reason(case, "known_method_available") for case in unsupported_cases)
        resolved_selected = [_resolved_case(case, selection_reason="generic evaluator family selected by priority") for case in selected]
        return [], resolved_selected, skipped, unsupported_cases, skipped, []

    targets = [_implementation_target_from_case(case) for case in unsupported_cases[:MAX_EVALUATION_METHODS_PER_RUN]]
    skipped.extend(
        _case_with_skip_reason(case, "method_budget_exceeded")
        for case in unsupported_cases[MAX_EVALUATION_METHODS_PER_RUN:]
    )
    return [], [], skipped, unsupported_cases, skipped, targets


def _select_evaluation_cases_by_support(
    valid_cases: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    *,
    data_profile: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    assessed: list[dict[str, Any]] = []
    for case in valid_cases:
        descriptor = evaluator_capabilities_for_case(case) or {}
        assessment = assess_evaluation_case_support(case, data_profile, descriptor).to_dict()
        assessed_case = dict(case)
        assessed_case["support_assessment"] = assessment
        assessed_case["support_score"] = assessment["support_score"]
        assessed_case["comparability"] = assessment["comparability"]
        assessed_case["deviations"] = assessment["deviations"]
        assessed_case["truth_match_eligible_metrics"] = assessment["truth_match_eligible_metrics"]
        assessed_case["diagnostic_only_metrics"] = assessment["diagnostic_only_metrics"]
        assessed_case["replacement_records"] = assessment.get("replacement_records", [])
        assessed_case["case_executable"] = assessment.get("case_executable", True)
        assessed.append(assessed_case)

    ordered = sorted(assessed, key=_support_priority)
    selected: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    canonical_ic_only = bool(ordered) and all(
        case.get("evaluation_family") == "ic_analysis" and case.get("paper_protocol_refs")
        for case in ordered
    )
    selection_limit = 1 if canonical_ic_only else MAX_EVALUATION_METHODS_PER_RUN
    for case in ordered:
        if case.get("paper_truth_conflict"):
            conflict_case = _case_with_lifecycle(
                _case_with_skip_reason(case, "unresolved_paper_truth_conflict"),
                "paper_truth_conflict",
            )
            unsupported.append(conflict_case)
            continue
        if not case.get("case_executable", True):
            capability_missing = any(
                result.get("category") == "evaluator_capability" and not result.get("execution_ready", True)
                for result in (case.get("support_assessment", {}).get("requirement_results", []) or [])
                if isinstance(result, dict)
            )
            lifecycle = "unsupported_evaluator" if capability_missing else "insufficient_data"
            unsupported_case = _case_with_lifecycle(case, lifecycle)
            unsupported.append(unsupported_case)
            if lifecycle == "unsupported_evaluator" and case.get("evaluation_family") not in GENERIC_EVALUATION_FAMILIES:
                targets.append(_implementation_target_from_case(case))
            continue
        if case.get("comparability") == "not_comparable":
            unsupported_case = _case_with_lifecycle(case, "unsupported_evaluator")
            unsupported.append(unsupported_case)
            if case.get("evaluation_family") not in GENERIC_EVALUATION_FAMILIES:
                targets.append(_implementation_target_from_case(case))
            continue
        if len(selected) < selection_limit:
            selected.append(
                _resolved_case(
                    case,
                    selection_reason=(
                        "highest semantic comparability and data-support score among assessed IC truth sources; "
                        "reported metric values were not used"
                        if canonical_ic_only
                        else "highest support score among assessed truth sources"
                    ),
                )
            )
        else:
            skipped_case = _case_with_lifecycle(
                _case_with_skip_reason(case, "superseded_by_better_supported_truth"),
                "superseded_by_better_supported_truth",
            )
            skipped.append(skipped_case)

    if not selected and unsupported:
        skipped.extend(_case_with_skip_reason(case, "unsupported_evaluator") for case in unsupported)
    return assessed, selected, skipped, unsupported, deferred, targets[:MAX_EVALUATION_METHODS_PER_RUN]


def _resolved_case(case: dict[str, Any], *, selection_reason: str) -> dict[str, Any]:
    payload = dict(case)
    payload["lifecycle_state"] = "selected"
    payload["selection_reason"] = selection_reason
    resolved_evaluation_spec = dict(payload.get("evaluation_spec", {}) or {})
    resolved_required_data = _resolved_required_data(payload)
    resolved_transform_spec = _resolved_transform_spec(payload)
    resolved_neutralization_spec = _resolved_neutralization_spec(payload)
    resolved_universe_protocol = _resolved_universe_protocol(payload)
    deviations = list(payload.get("deviations", []) or [])
    diagnostic_only_metrics = list(payload.get("diagnostic_only_metrics", []) or [])
    eligible_metrics = list(payload.get("truth_match_eligible_metrics", list((payload.get("metrics", {}) or {}).keys())) or [])

    return_col = _available_requirement_value(payload, "return")
    if return_col:
        resolved_evaluation_spec["return_col"] = return_col
        _replace_required_value(resolved_required_data, "evaluation", return_col)

    regression_type = str(resolved_evaluation_spec.get("regression_type", "") or "").lower()
    paper_weight = str(
        resolved_evaluation_spec.get("weight_col")
        or resolved_evaluation_spec.get("regression_weight")
        or _first_required_value(payload.get("required_data", {}), "regression_weight")
        or ""
    ).strip()
    available_weight = _available_requirement_value(payload, "regression_weight")
    if paper_weight and available_weight:
        resolved_evaluation_spec["weight_col"] = available_weight
    if regression_type == "wls" and not available_weight:
        resolved_evaluation_spec["regression_type"] = "ols"
        resolved_evaluation_spec["weight_col"] = None
        deviations.append(
            {
                "category": "regression_weight",
                "paper_value": paper_weight or "wls_weight",
                "resolved_value": "ols_without_weight",
                "reason": "WLS weight is unavailable; runtime protocol uses OLS proxy while preserving paper protocol.",
                "severity": "material",
                "affected_metrics": _regression_metrics(payload),
                "truth_matching_policy": "proxy_or_diagnostic_only",
                "source": "automatically_detected",
            }
        )
        for metric in _regression_metrics(payload):
            if metric not in diagnostic_only_metrics:
                diagnostic_only_metrics.append(metric)
            if metric in eligible_metrics:
                eligible_metrics.remove(metric)
        if payload.get("comparability") == "exact":
            payload["comparability"] = "proxy"

    controls = _resolved_controls(payload)
    if controls:
        resolved_evaluation_spec["regression_controls"] = controls
        resolved_required_data["controls"] = controls
    elif resolved_evaluation_spec.get("regression_controls"):
        resolved_evaluation_spec["regression_controls"] = []

    payload["resolved_protocol"] = {
        "evaluation_family": payload.get("evaluation_family", ""),
        "evaluation_method": payload.get("evaluation_method", ""),
        "sample_period": _resolved_sample_period(payload),
        "universe": payload.get("universe", ""),
        "frequency": payload.get("frequency", ""),
        "evaluation_spec": resolved_evaluation_spec,
        "required_data": resolved_required_data,
        "transform_spec": resolved_transform_spec,
        "neutralization_spec": resolved_neutralization_spec,
        "universe_protocol": resolved_universe_protocol,
        "paper_protocol_refs": dict(payload.get("paper_protocol_refs", {}) or {}),
        "operation_pipeline_id": payload.get("operation_pipeline_id", ""),
        "timing": {
            "signal_date": "t",
            "history_cutoff": "t",
            "eligibility_date": "t",
            "tradability_filter_date": _tradability_filter_date(resolved_universe_protocol),
            "return_target_date": "market_calendar_t_plus_h",
            "return_interval": "paper_defined_factor_t_to_following_h_trading_days",
        },
    }
    payload.setdefault("comparability", "exact")
    payload.setdefault("support_assessment", {})
    payload["deviations"] = deviations
    payload["truth_match_eligible_metrics"] = eligible_metrics
    payload["diagnostic_only_metrics"] = diagnostic_only_metrics
    return payload


def _case_with_lifecycle(case: dict[str, Any], lifecycle_state: str) -> dict[str, Any]:
    payload = dict(case)
    payload["lifecycle_state"] = lifecycle_state
    return payload


def _case_priority(case: dict[str, Any]) -> tuple[int, str]:
    family = str(case.get("evaluation_family", "") or "custom")
    return EVALUATION_METHOD_PRIORITY.get(family, EVALUATION_METHOD_PRIORITY["custom"]), str(case.get("truth_id", ""))


def _support_priority(case: dict[str, Any]) -> tuple[float, int, int, int, int, str]:
    comparability_rank = {
        "exact": 5,
        "materially_comparable": 4,
        "proxy": 3,
        "directional_only": 2,
        "not_comparable": 1,
    }.get(str(case.get("comparability", "")), 0)
    eligible_count = len(case.get("truth_match_eligible_metrics", []) or [])
    material_deviations = sum(1 for deviation in case.get("deviations", []) if deviation.get("severity") in {"material", "fundamental"})
    return (
        -float(case.get("support_score", 0.0) or 0.0),
        -comparability_rank,
        -eligible_count,
        material_deviations,
        -len(case.get("metrics", {}) or {}),
        str(case.get("truth_id", "")),
    )


def _normalize_evaluation_family(family: str) -> str:
    normalized = family.strip().lower().replace("-", "_").replace(" ", "_")
    return EVALUATION_FAMILY_ALIASES.get(normalized, normalized or "custom")


def _case_with_skip_reason(case: dict[str, Any], reason: str) -> dict[str, Any]:
    payload = dict(case)
    payload["skip_reason"] = reason
    return payload


def _implementation_target_from_case(case: dict[str, Any]) -> dict[str, Any]:
    family = str(case.get("evaluation_family", "") or "custom")
    return {
        "truth_id": str(case.get("truth_id", "")),
        "evaluation_family": family,
        "suggested_function_name": f"evaluate_paper_{family}",
        "reason": "No generic evaluator exists and no IC/regression truth source was available.",
    }


def _candidate_truth_sources(spec: FactorResearchSpec) -> list[dict[str, Any]]:
    selected = [source for source in spec.metadata.get("selected_truth_sources", []) if isinstance(source, dict)]
    all_sources = [source for source in spec.metadata.get("truth_sources", []) if isinstance(source, dict)]
    rule = str(spec.metadata.get("truth_selection_rule", "") or "").strip()
    if not rule or not all_sources:
        return selected
    selected_ids = {str(source.get("truth_id", "")) for source in selected}
    candidates = list(selected)
    for source in all_sources:
        truth_id = str(source.get("truth_id", ""))
        if truth_id and truth_id not in selected_ids:
            candidates.append(source)
    return candidates


def _resolved_required_data(case: dict[str, Any]) -> dict[str, Any]:
    required_data = dict(case.get("required_data", {}) or {})
    results = _support_requirement_results(case)
    for category, values in list(required_data.items()):
        values_list = values if isinstance(values, list) else [values]
        resolved_values: list[str] = []
        for value in [str(item) for item in values_list if str(item)]:
            replacement = _available_value_for_requirement(results, value)
            if replacement:
                resolved_values.append(replacement)
            elif not _requirement_missing(results, value):
                resolved_values.append(value)
        required_data[category] = _dedupe(resolved_values)
    return required_data


def _resolved_transform_spec(case: dict[str, Any]) -> dict[str, Any]:
    transform_spec = dict(case.get("transform_spec", {}) or {})
    results = _support_requirement_results(case)
    steps: list[dict[str, Any]] = []
    deviations = case.get("deviations", []) or []
    for step in transform_spec.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        payload = dict(step)
        if str(payload.get("name", "")).lower() == "neutralization":
            controls = []
            for control in [str(item) for item in payload.get("controls", []) or []]:
                replacement = _available_value_for_requirement(results, control)
                if replacement:
                    controls.append(replacement)
            if controls:
                payload["controls"] = _dedupe(controls)
            else:
                payload["method"] = "none"
                payload["controls"] = []
                payload["source"] = "runtime_proxy"
                payload["proxy_reason"] = "neutralization controls unavailable in resolved runtime panel"
        steps.append(payload)
    transform_spec["steps"] = steps
    if any(dev.get("category") == "transform_control" for dev in deviations):
        transform_spec["runtime_deviations"] = [dev for dev in deviations if dev.get("category") == "transform_control"]
    return transform_spec


def _resolved_neutralization_spec(case: dict[str, Any]) -> dict[str, Any]:
    spec = copy.deepcopy(case.get("neutralization_spec", {}) or {})
    if not isinstance(spec, dict) or not spec:
        return {}
    results = _support_requirement_results(case)
    controls: list[dict[str, Any]] = []
    executable_count = 0
    for raw_control in spec.get("controls", []) or []:
        if not isinstance(raw_control, dict):
            continue
        control = dict(raw_control)
        paper_field = str(control.get("paper_field") or control.get("field") or "")
        replacement = _available_value_for_requirement(results, paper_field)
        if replacement:
            control["resolved_field"] = replacement
            control["runtime_status"] = "executable"
            executable_count += 1
        elif paper_field and not _requirement_missing(results, paper_field):
            control["resolved_field"] = str(control.get("field") or paper_field)
            control["runtime_status"] = "executable"
            executable_count += 1
        else:
            control["resolved_field"] = None
            control["runtime_status"] = "unavailable"
        controls.append(control)
    spec["controls"] = controls
    spec["runtime_status"] = "executable" if executable_count else "no_executable_controls"
    return spec


def _resolved_universe_protocol(case: dict[str, Any]) -> dict[str, Any]:
    protocol = copy.deepcopy(case.get("universe_protocol", {}) or {})
    if not isinstance(protocol, dict) or not protocol:
        return {}
    results = _support_requirement_results(case)
    filters: list[dict[str, Any]] = []
    for raw_filter in protocol.get("filters", []) or []:
        if not isinstance(raw_filter, dict):
            continue
        item = dict(raw_filter)
        paper_field = str(item.get("paper_field") or item.get("field") or "")
        replacement = _available_value_for_requirement(results, paper_field)
        if replacement:
            item["resolved_field"] = replacement
            item["runtime_status"] = "executable"
        elif paper_field and not _requirement_missing(results, paper_field):
            item["resolved_field"] = str(item.get("field") or paper_field)
            item["runtime_status"] = "executable"
        else:
            item["resolved_field"] = None
            item["runtime_status"] = "unavailable"
        filters.append(item)
    protocol["filters"] = filters
    return protocol


def _resolved_controls(case: dict[str, Any]) -> list[str]:
    results = _support_requirement_results(case)
    controls: list[str] = []
    for control in _required_values(case, "controls"):
        replacement = _available_value_for_requirement(results, control)
        if replacement:
            controls.append(replacement)
        elif not _requirement_missing(results, control):
            controls.append(control)
    for control in _required_values(case, "transform_control"):
        replacement = _available_value_for_requirement(results, control)
        if replacement:
            controls.append(replacement)
    return _dedupe(controls)


def _resolved_sample_period(case: dict[str, Any]) -> str:
    for result in _support_requirement_results(case):
        if result.get("category") == "sample_period" and result.get("available_value"):
            return str(result["available_value"])
    return str(case.get("sample_period", ""))


def _tradability_filter_date(universe_protocol: dict[str, Any]) -> str:
    rules = [
        str(item.get("effective_date_rule", ""))
        for item in universe_protocol.get("filters", []) or []
        if isinstance(item, dict)
    ]
    if any(any(token in rule.lower() for token in ("t_plus_1", "t+1", "next")) for rule in rules):
        return "next_exchange_trading_day_t_plus_1"
    return "signal_date_t"


def _available_requirement_value(case: dict[str, Any], category: str) -> str:
    for result in _support_requirement_results(case):
        if (
            result.get("category") == category
            and result.get("available_value")
            and _requirement_execution_ready(result)
        ):
            return str(result["available_value"])
    return ""


def _available_value_for_requirement(results: list[dict[str, Any]], requirement: str) -> str:
    for result in results:
        if (
            result.get("requirement") == requirement
            and result.get("availability") != "missing"
            and result.get("available_value")
            and _requirement_execution_ready(result)
        ):
            return str(result.get("available_value") or requirement)
    return ""


def _requirement_missing(results: list[dict[str, Any]], requirement: str) -> bool:
    return any(
        result.get("requirement") == requirement
        and (result.get("availability") == "missing" or not _requirement_execution_ready(result))
        for result in results
    )


def _requirement_execution_ready(result: dict[str, Any]) -> bool:
    if "execution_ready" in result:
        return bool(result.get("execution_ready"))
    return result.get("availability") != "missing" and bool(result.get("available_value"))


def _support_requirement_results(case: dict[str, Any]) -> list[dict[str, Any]]:
    assessment = case.get("support_assessment", {}) if isinstance(case.get("support_assessment", {}), dict) else {}
    return [
        dict(item)
        for item in assessment.get("requirement_results", []) or []
        if isinstance(item, dict)
    ]


def _replace_required_value(required_data: dict[str, Any], category: str, value: str) -> None:
    if not value:
        return
    current = required_data.get(category, [])
    values = current if isinstance(current, list) else [current]
    if value not in values:
        values = [value, *[item for item in values if item]]
    required_data[category] = _dedupe([str(item) for item in values if str(item)])


def _first_required_value(required_data: Any, category: str) -> str:
    if not isinstance(required_data, dict):
        return ""
    values = required_data.get(category, [])
    if isinstance(values, list) and values:
        return str(values[0])
    return str(values or "")


def _required_values(case: dict[str, Any], category: str) -> list[str]:
    required_data = case.get("required_data", {}) if isinstance(case.get("required_data", {}), dict) else {}
    values = required_data.get(category, [])
    if isinstance(values, list):
        return [str(value) for value in values if str(value)]
    return [str(values)] if str(values) else []


def _regression_metrics(case: dict[str, Any]) -> list[str]:
    metrics = list((case.get("metrics", {}) or {}).keys())
    result = [metric for metric in metrics if any(token in metric for token in ("t_", "factor_return", "regression"))]
    return result or metrics


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _infer_evaluation_family(source: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(source.get("evaluation_method", "")),
            " ".join(str(metric) for metric in (source.get("metrics", {}) or {})),
        ]
    ).lower().replace("-", "_")
    if "half_life" in text or "decay" in text:
        return "ic_decay"
    if "rank_ic" in text or "ic" in text:
        return "ic_analysis"
    if "top_layer" in text or "long_short" in text or "portfolio" in text or "layer" in text:
        return "layered_portfolio_backtest"
    if "t_abs" in text or "factor_return" in text or "regression" in text:
        return "regression_t_test"
    return "custom"


def _evaluation_features(evaluation_method: str, metrics: list[str]) -> list[str]:
    text = " ".join([evaluation_method, *metrics]).lower().replace("-", "_")
    features: list[str] = []
    if "rank_ic" in text or "rank ic" in text:
        features.append("rank_ic")
    elif "ic" in text:
        features.append("pearson_ic")
    if "ir" in text:
        features.append("information_ratio")
    if "long_short" in text or "long short" in text or "spread" in text:
        features.append("long_short")
    if "sharpe" in text:
        features.append("sharpe")
    if "return" in text:
        features.append("forward_returns")
    return features or ["custom"]


def _forward_return_periods(evaluation_method: str) -> list[int]:
    text = evaluation_method.lower()
    periods = [int(match.group(1)) for match in re.finditer(r"(\d+)\s*[- ]?day", text)]
    if not periods and ("daily" in text or "1-day" in text or "1 day" in text):
        periods = [1]
    return sorted(set(periods or [1]))
