from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from research_core.factor_lab.paper_reproduction.extraction import ExtractedFactor


@dataclass(slots=True)
class DataFrameValidationRequest:
    factor_name: str
    required_columns: list[str]
    frequency: str = ""
    required_lookback: int = 0
    date_column: str = "date"
    code_column: str = "code"

    @classmethod
    def from_factor(cls, factor: ExtractedFactor) -> DataFrameValidationRequest:
        return cls(
            factor_name=factor.factor_name,
            required_columns=["date", "code", *factor.required_fields],
            frequency=factor.frequency,
            required_lookback=_infer_required_lookback(factor.parameters),
        )


@dataclass(slots=True)
class DataFrameValidationResult:
    valid: bool
    status: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DataProfile:
    source_id: str
    row_count: int
    date_count: int
    code_count: int
    columns: list[str]
    date_min: str = ""
    date_max: str = ""
    missingness: dict[str, float] = field(default_factory=dict)
    duplicate_key_count: int = 0
    field_coverage: dict[str, dict[str, Any]] = field(default_factory=dict)
    conventions: dict[str, Any] = field(default_factory=dict)
    derived_fields: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvaluationRequirementResult:
    requirement: str
    category: str
    paper_value: Any = None
    available_value: Any = None
    availability: str = "unknown"
    substitute: Any = None
    severity: str = "minor"
    affected_metrics: list[str] = field(default_factory=list)
    recommended_action: str = "continue_with_limitation"


@dataclass(slots=True)
class EvaluationCaseSupportAssessment:
    truth_id: str
    support_score: float
    comparability: str
    requirement_results: list[EvaluationRequirementResult] = field(default_factory=list)
    deviations: list[dict[str, Any]] = field(default_factory=list)
    truth_match_eligible_metrics: list[str] = field(default_factory=list)
    diagnostic_only_metrics: list[str] = field(default_factory=list)
    lifecycle_state: str = "assessed"
    selection_reason: str = ""
    score_components: dict[str, float] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_input_frame(frame: pd.DataFrame, request: DataFrameValidationRequest) -> DataFrameValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    missing_required_columns = [column for column in request.required_columns if column not in frame.columns]
    if missing_required_columns:
        errors.append(f"missing required columns: {', '.join(missing_required_columns)}")

    diagnostics: dict[str, Any] = {
        "factor_name": request.factor_name,
        "row_count": int(len(frame)),
        "columns": list(frame.columns),
        "missing_required_columns": missing_required_columns,
    }

    if request.date_column in frame.columns:
        parsed_dates = pd.to_datetime(frame[request.date_column], errors="coerce")
        diagnostics["date_count"] = int(parsed_dates.nunique(dropna=True))
        invalid_date_count = int(parsed_dates.isna().sum())
        diagnostics["invalid_date_count"] = invalid_date_count
        if invalid_date_count:
            errors.append(f"invalid date values: {invalid_date_count}")
    else:
        parsed_dates = pd.Series(dtype="datetime64[ns]")
        diagnostics["date_count"] = 0
        diagnostics["invalid_date_count"] = 0

    if request.code_column in frame.columns:
        diagnostics["code_count"] = int(frame[request.code_column].nunique(dropna=True))
    else:
        diagnostics["code_count"] = 0

    if request.date_column in frame.columns and request.code_column in frame.columns:
        duplicate_count = int(frame.duplicated(subset=[request.date_column, request.code_column], keep=False).sum())
        diagnostics["duplicate_key_count"] = duplicate_count
        if duplicate_count:
            errors.append(f"duplicate date-code rows: {duplicate_count}")
        if not _is_sorted_by_code_date(frame, request.code_column, request.date_column):
            warnings.append("frame is not sorted by code,date")
    else:
        diagnostics["duplicate_key_count"] = 0

    if request.required_lookback > 0 and request.date_column in frame.columns and request.code_column in frame.columns:
        max_history = int(frame.groupby(request.code_column)[request.date_column].count().max()) if not frame.empty else 0
        diagnostics["max_history_per_code"] = max_history
        diagnostics["required_lookback"] = request.required_lookback
        if max_history < request.required_lookback:
            warnings.append(f"max history per code {max_history} is shorter than required lookback {request.required_lookback}")

    if errors:
        status = "failed"
    elif warnings:
        status = "needs_human_review"
    else:
        status = "passed"
    return DataFrameValidationResult(valid=not errors, status=status, errors=errors, warnings=warnings, diagnostics=diagnostics)


def build_data_profile(
    frame: pd.DataFrame,
    *,
    source_id: str = "dataframe",
    date_column: str = "date",
    code_column: str = "code",
    conventions: dict[str, Any] | None = None,
    derived_fields: list[dict[str, Any]] | None = None,
) -> DataProfile:
    parsed_dates = pd.to_datetime(frame[date_column], errors="coerce") if date_column in frame.columns else pd.Series(dtype="datetime64[ns]")
    duplicate_count = (
        int(frame.duplicated(subset=[date_column, code_column], keep=False).sum())
        if date_column in frame.columns and code_column in frame.columns
        else 0
    )
    missingness = {
        str(column): float(frame[column].isna().mean()) if len(frame) else 0.0
        for column in frame.columns
    }
    field_coverage: dict[str, dict[str, Any]] = {}
    for column in frame.columns:
        non_missing = frame[column].notna()
        field_coverage[str(column)] = {
            "non_missing_rows": int(non_missing.sum()),
            "missing_ratio": missingness[str(column)],
        }
        if date_column in frame.columns and bool(non_missing.any()):
            dates = parsed_dates[non_missing]
            valid_dates = dates.dropna()
            if not valid_dates.empty:
                field_coverage[str(column)]["date_min"] = valid_dates.min().date().isoformat()
                field_coverage[str(column)]["date_max"] = valid_dates.max().date().isoformat()

    limitations: list[str] = []
    if duplicate_count:
        limitations.append(f"duplicate {date_column}-{code_column} keys: {duplicate_count}")
    if parsed_dates.isna().any() and date_column in frame.columns:
        limitations.append(f"invalid {date_column} values: {int(parsed_dates.isna().sum())}")

    return DataProfile(
        source_id=source_id,
        row_count=int(len(frame)),
        date_count=int(parsed_dates.nunique(dropna=True)),
        code_count=int(frame[code_column].nunique(dropna=True)) if code_column in frame.columns else 0,
        columns=[str(column) for column in frame.columns],
        date_min=parsed_dates.min().date().isoformat() if not parsed_dates.dropna().empty else "",
        date_max=parsed_dates.max().date().isoformat() if not parsed_dates.dropna().empty else "",
        missingness=missingness,
        duplicate_key_count=duplicate_count,
        field_coverage=field_coverage,
        conventions=conventions or {},
        derived_fields=derived_fields or [],
        limitations=limitations,
    )


def assess_evaluation_case_support(
    truth_source: dict[str, Any],
    data_profile: DataProfile | dict[str, Any],
    evaluator_capabilities: dict[str, Any] | None = None,
) -> EvaluationCaseSupportAssessment:
    profile = data_profile if isinstance(data_profile, dict) else asdict(data_profile)
    evaluator_capabilities = evaluator_capabilities or {}
    truth_id = str(truth_source.get("truth_id", ""))
    metrics = list((truth_source.get("metrics", {}) or {}).keys())
    requirement_results: list[EvaluationRequirementResult] = []
    deviations: list[dict[str, Any]] = []

    required_data = truth_source.get("required_data", {}) if isinstance(truth_source.get("required_data", {}), dict) else {}
    for category, raw_requirements in required_data.items():
        requirements = raw_requirements if isinstance(raw_requirements, list) else [raw_requirements]
        for requirement in [str(value) for value in requirements if str(value)]:
            resolved = _resolve_requirement(requirement, profile)
            availability = resolved["availability"]
            severity = "material" if availability == "missing" else "minor"
            action = "try_alternative_truth_then_proxy" if availability == "missing" else "use_requested_field"
            affected = _affected_metrics_for_requirement(str(category), metrics)
            result = EvaluationRequirementResult(
                requirement=requirement,
                category=str(category),
                paper_value=requirement,
                available_value=resolved["available_value"],
                availability=availability,
                substitute=resolved["substitute"],
                severity=severity if availability != "constructible" else "minor",
                affected_metrics=affected,
                recommended_action=action,
            )
            requirement_results.append(result)
            if availability == "missing":
                deviations.append(
                    structured_deviation(
                        category=str(category),
                        paper_value=requirement,
                        resolved_value=None,
                        reason="required evaluation field is unavailable in the profiled data",
                        severity=severity,
                        affected_metrics=affected,
                        truth_matching_policy="proxy_or_diagnostic_only",
                    )
                )

    for result in _sample_period_requirement_results(truth_source, profile, metrics):
        requirement_results.append(result)
        if result.availability != "available":
            deviations.append(
                structured_deviation(
                    category=result.category,
                    paper_value=result.paper_value,
                    resolved_value=result.available_value,
                    reason="available data does not fully cover the paper sample period",
                    severity=result.severity,
                    affected_metrics=result.affected_metrics,
                    truth_matching_policy="proxy_or_partial_period",
                )
            )

    for result in _universe_requirement_results(truth_source, profile, metrics):
        requirement_results.append(result)
        if result.availability == "missing":
            deviations.append(
                structured_deviation(
                    category=result.category,
                    paper_value=result.paper_value,
                    resolved_value=result.available_value,
                    reason="available data does not support the requested universe filter exactly",
                    severity=result.severity,
                    affected_metrics=result.affected_metrics,
                    truth_matching_policy="proxy_or_diagnostic_only",
                )
            )

    for result in _evaluation_spec_requirement_results(truth_source, profile, metrics):
        requirement_results.append(result)
        if result.availability == "missing":
            deviations.append(
                structured_deviation(
                    category=result.category,
                    paper_value=result.paper_value,
                    resolved_value=result.available_value,
                    reason="evaluation specification requirement is unavailable in the profiled data",
                    severity=result.severity,
                    affected_metrics=result.affected_metrics,
                    truth_matching_policy="proxy_or_diagnostic_only",
                )
            )

    for result in _transform_requirement_results(truth_source, profile, metrics):
        requirement_results.append(result)
        if result.availability == "missing":
            deviations.append(
                structured_deviation(
                    category=result.category,
                    paper_value=result.paper_value,
                    resolved_value=result.available_value,
                    reason="transform step requires unavailable data or unsupported semantics",
                    severity=result.severity,
                    affected_metrics=result.affected_metrics,
                    truth_matching_policy="proxy_or_diagnostic_only",
                )
            )

    family = str(truth_source.get("evaluation_family", "") or "")
    capability_result = _assess_evaluator_capability(truth_source, evaluator_capabilities)
    requirement_results.append(capability_result)
    if capability_result.availability == "missing":
        deviations.append(
            structured_deviation(
                category="evaluator_capability",
                paper_value=family or truth_source.get("evaluation_method", ""),
                resolved_value=None,
                reason="no registered evaluator supports the requested protocol",
                severity="material",
                affected_metrics=metrics or ["*"],
                truth_matching_policy="not_evaluated",
            )
        )

    missing_count = sum(1 for result in requirement_results if result.availability == "missing")
    partial_count = sum(1 for result in requirement_results if result.availability in {"partially_available", "available_with_quality_warning"})
    data_coverage = 1.0 if not requirement_results else max(0.0, 1.0 - missing_count / len(requirement_results) - partial_count * 0.2 / len(requirement_results))
    evaluator_coverage = 0.0 if capability_result.availability == "missing" else 1.0
    metric_coverage = 1.0 if metrics else 0.0
    support_score = round(0.45 * data_coverage + 0.35 * evaluator_coverage + 0.20 * metric_coverage, 6)
    comparability = _comparability_from_support(missing_count, partial_count, capability_result.availability)
    diagnostic = sorted(
        {
            metric
            for dev in deviations
            if dev.get("truth_matching_policy") != "proxy_or_partial_period"
            for metric in dev.get("affected_metrics", [])
            if metric != "*"
        }
    )
    eligible = [metric for metric in metrics if metric not in diagnostic and comparability != "not_comparable"]
    if "*" in {
        metric
        for dev in deviations
        if dev.get("truth_matching_policy") != "proxy_or_partial_period"
        for metric in dev.get("affected_metrics", [])
    }:
        eligible = [] if comparability in {"not_comparable", "directional_only"} else eligible
        diagnostic = metrics
    return EvaluationCaseSupportAssessment(
        truth_id=truth_id,
        support_score=support_score,
        comparability=comparability,
        requirement_results=requirement_results,
        deviations=deviations,
        truth_match_eligible_metrics=eligible,
        diagnostic_only_metrics=diagnostic,
        score_components={
            "required_data_coverage": round(data_coverage, 6),
            "evaluator_capability_coverage": evaluator_coverage,
            "metric_coverage": metric_coverage,
        },
        limitations=[dev["reason"] for dev in deviations],
    )


def structured_deviation(
    *,
    category: str,
    paper_value: Any,
    resolved_value: Any,
    reason: str,
    severity: str,
    affected_metrics: list[str],
    truth_matching_policy: str,
    source: str = "automatically_detected",
) -> dict[str, Any]:
    return {
        "category": category,
        "paper_value": paper_value,
        "resolved_value": resolved_value,
        "reason": reason,
        "severity": severity,
        "affected_metrics": affected_metrics,
        "truth_matching_policy": truth_matching_policy,
        "source": source,
    }


def _is_sorted_by_code_date(frame: pd.DataFrame, code_column: str, date_column: str) -> bool:
    if frame.empty:
        return True
    current = frame[[code_column, date_column]].reset_index(drop=True)
    expected = current.sort_values([code_column, date_column], kind="mergesort").reset_index(drop=True)
    return current.equals(expected)


def _infer_required_lookback(parameters: dict[str, Any]) -> int:
    candidates: list[int] = []
    for key, value in parameters.items():
        if "window" not in str(key).lower() and "lookback" not in str(key).lower():
            continue
        try:
            candidates.append(int(value))
        except (TypeError, ValueError):
            continue
    return max(candidates, default=0)


def _field_availability(field: str, profile: dict[str, Any]) -> str:
    return _resolve_requirement(field, profile)["availability"]


def _resolve_requirement(field: str, profile: dict[str, Any]) -> dict[str, Any]:
    columns = set(str(column) for column in (profile.get("columns", []) or []))
    candidates = _requirement_candidates(field)
    for candidate in candidates:
        if candidate in columns:
            missing_ratio = float((profile.get("missingness", {}) or {}).get(candidate, 0.0) or 0.0)
            if missing_ratio == 0:
                availability = "available"
            elif missing_ratio < 0.2:
                availability = "available_with_quality_warning"
            else:
                availability = "partially_available"
            return {
                "availability": availability,
                "available_value": candidate,
                "substitute": candidate if candidate != field else None,
            }
    if field in columns:
        missing_ratio = float((profile.get("missingness", {}) or {}).get(field, 0.0) or 0.0)
        if missing_ratio == 0:
            availability = "available"
        elif missing_ratio < 0.2:
            availability = "available_with_quality_warning"
        else:
            availability = "partially_available"
        return {"availability": availability, "available_value": field, "substitute": None}
    derived = profile.get("derived_fields", []) or []
    for candidate in candidates:
        if any(isinstance(item, dict) and item.get("field") == candidate for item in derived):
            return {
                "availability": "constructible",
                "available_value": candidate,
                "substitute": candidate if candidate != field else None,
            }
    return {"availability": "missing", "available_value": None, "substitute": None}


def _requirement_candidates(field: str) -> list[str]:
    normalized = field.strip()
    lowered = normalized.lower()
    candidates = [normalized]
    aliases = {
        "market_cap_or_log_market_cap": ["log_market_cap", "market_cap"],
        "sqrt_free_float_market_cap": ["sqrt_free_float_market_cap", "free_float_market_cap", "market_cap"],
        "free_float_market_cap": ["free_float_market_cap", "market_cap"],
        "st_or_pt_status": ["is_st", "st_status", "status_code"],
        "next_day_suspension_status": ["next_is_suspended", "is_suspended"],
        "suspension_status": ["is_suspended", "next_is_suspended"],
        "tradability_status": ["is_trading", "next_is_suspended"],
        "industry_classification": ["industry", "industry_code"],
        "industry_or_sector": ["industry", "sector"],
    }
    candidates.extend(aliases.get(lowered, []))
    match = re.fullmatch(r"forward_return_(\d+)d", lowered)
    if match:
        candidates.append(f"forward_return_t{match.group(1)}")
    match = re.fullmatch(r"forward_return_t(\d+)", lowered)
    if match:
        candidates.append(f"forward_return_{match.group(1)}d")
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def _affected_metrics_for_requirement(category: str, metrics: list[str]) -> list[str]:
    lowered = category.lower()
    if "control" in lowered or "weight" in lowered or "regression" in lowered:
        affected = [metric for metric in metrics if any(token in metric for token in ("t_", "factor_return", "regression"))]
        return affected or metrics or ["*"]
    return metrics or ["*"]


def _assess_evaluator_capability(
    truth_source: dict[str, Any],
    evaluator_capabilities: dict[str, Any],
) -> EvaluationRequirementResult:
    family = str(truth_source.get("evaluation_family", "") or "")
    supported_families = set(evaluator_capabilities.get("evaluation_families", []) or [])
    capabilities = evaluator_capabilities.get("capabilities", {}) or {}
    metrics = list((truth_source.get("metrics", {}) or {}).keys())
    evaluation_spec = truth_source.get("evaluation_spec", {}) if isinstance(truth_source.get("evaluation_spec", {}), dict) else {}
    unsupported_metrics = [metric for metric in metrics if metric not in set(capabilities.get("metrics", []) or metrics)]
    unsupported_protocol: list[str] = []
    ic_type = str(evaluation_spec.get("ic_type", "") or "").lower()
    if ic_type and ic_type not in set(capabilities.get("ic_types", []) or []):
        unsupported_protocol.append(f"ic_type={ic_type}")
    regression_type = str(evaluation_spec.get("regression_type", "") or "").lower()
    if regression_type and regression_type not in set(capabilities.get("regression_types", []) or []):
        unsupported_protocol.append(f"regression_type={regression_type}")
    if regression_type == "wls" and not (evaluation_spec.get("weight_col") or evaluation_spec.get("regression_weight")):
        unsupported_protocol.append("wls_missing_weight_col")
    available = bool(not family or family in supported_families) and not unsupported_metrics and not unsupported_protocol
    affected_metrics = unsupported_metrics
    if not affected_metrics and unsupported_protocol:
        affected_metrics = _affected_metrics_for_requirement("regression", metrics)
    if not affected_metrics:
        affected_metrics = metrics or ["*"]
    return EvaluationRequirementResult(
        requirement=family or "evaluation_method",
        category="evaluator_capability",
        paper_value=family or truth_source.get("evaluation_method", ""),
        available_value=evaluator_capabilities.get("evaluator_id") if available else None,
        availability="available" if available else "missing",
        severity="material" if not available else "minor",
        affected_metrics=affected_metrics,
        recommended_action="execute_selected_case" if available else "try_alternative_truth_then_proxy",
    )


def _comparability_from_support(missing_count: int, partial_count: int, capability_availability: str) -> str:
    if capability_availability == "missing":
        return "not_comparable"
    if missing_count:
        return "proxy"
    if partial_count:
        return "materially_comparable"
    return "exact"


def _sample_period_requirement_results(
    truth_source: dict[str, Any],
    profile: dict[str, Any],
    metrics: list[str],
) -> list[EvaluationRequirementResult]:
    sample_period = str(truth_source.get("sample_period", "") or "").strip()
    if not sample_period:
        return []
    paper_start, paper_end = _parse_period_bounds(sample_period)
    data_start = str(profile.get("date_min", "") or "")
    data_end = str(profile.get("date_max", "") or "")
    if not paper_start or not paper_end or not data_start or not data_end:
        return [
            EvaluationRequirementResult(
                requirement="sample_period",
                category="sample_period",
                paper_value=sample_period,
                available_value=f"{data_start}/{data_end}".strip("/"),
                availability="unknown",
                severity="minor",
                affected_metrics=metrics or ["*"],
            )
        ]
    covers = data_start <= paper_start and data_end >= paper_end
    overlaps = data_end >= paper_start and data_start <= paper_end
    if covers:
        availability = "available"
        severity = "minor"
    elif overlaps:
        availability = "partially_available"
        severity = "material"
    else:
        availability = "missing"
        severity = "fundamental"
    return [
        EvaluationRequirementResult(
            requirement="sample_period",
            category="sample_period",
            paper_value=f"{paper_start}/{paper_end}",
            available_value=f"{max(data_start, paper_start)}/{min(data_end, paper_end)}" if overlaps else f"{data_start}/{data_end}",
            availability=availability,
            severity=severity,
            affected_metrics=metrics or ["*"],
            recommended_action="use_available_overlap" if overlaps else "try_alternative_truth_then_proxy",
        )
    ]


def _universe_requirement_results(
    truth_source: dict[str, Any],
    profile: dict[str, Any],
    metrics: list[str],
) -> list[EvaluationRequirementResult]:
    universe = str(truth_source.get("universe", "") or "").lower()
    if not universe:
        return []
    if not any(token in universe for token in ("a-share", "a share", "a股", "全a")):
        return []
    requirements = [
        ("st_or_pt_status", "universe_filter"),
        ("next_day_suspension_status", "universe_filter"),
    ]
    results: list[EvaluationRequirementResult] = []
    for requirement, category in requirements:
        resolved = _resolve_requirement(requirement, profile)
        results.append(
            EvaluationRequirementResult(
                requirement=requirement,
                category=category,
                paper_value=requirement,
                available_value=resolved["available_value"],
                availability=resolved["availability"],
                substitute=resolved["substitute"],
                severity="material" if resolved["availability"] == "missing" else "minor",
                affected_metrics=metrics or ["*"],
                recommended_action="apply_filter" if resolved["availability"] != "missing" else "proxy_or_report_gap",
            )
        )
    return results


def _evaluation_spec_requirement_results(
    truth_source: dict[str, Any],
    profile: dict[str, Any],
    metrics: list[str],
) -> list[EvaluationRequirementResult]:
    evaluation_spec = truth_source.get("evaluation_spec", {}) if isinstance(truth_source.get("evaluation_spec", {}), dict) else {}
    results: list[EvaluationRequirementResult] = []
    weight = str(evaluation_spec.get("weight_col") or evaluation_spec.get("regression_weight") or "").strip()
    if weight:
        resolved = _resolve_requirement(weight, profile)
        results.append(
            EvaluationRequirementResult(
                requirement=weight,
                category="regression_weight",
                paper_value=weight,
                available_value=resolved["available_value"],
                availability=resolved["availability"],
                substitute=resolved["substitute"],
                severity="material" if resolved["availability"] == "missing" else "minor",
                affected_metrics=_affected_metrics_for_requirement("regression_weight", metrics),
                recommended_action="use_weight" if resolved["availability"] != "missing" else "try_alternative_truth_then_proxy",
            )
        )
    return_col = str(evaluation_spec.get("return_col") or "").strip()
    horizon = evaluation_spec.get("return_horizon")
    if not return_col and horizon:
        return_col = f"forward_return_{horizon}d"
    if return_col:
        resolved = _resolve_requirement(return_col, profile)
        results.append(
            EvaluationRequirementResult(
                requirement=return_col,
                category="return",
                paper_value=return_col,
                available_value=resolved["available_value"],
                availability=resolved["availability"],
                substitute=resolved["substitute"],
                severity="fundamental" if resolved["availability"] == "missing" else "minor",
                affected_metrics=metrics or ["*"],
                recommended_action="use_return_column" if resolved["availability"] != "missing" else "cannot_evaluate_case",
            )
        )
    return results


def _transform_requirement_results(
    truth_source: dict[str, Any],
    profile: dict[str, Any],
    metrics: list[str],
) -> list[EvaluationRequirementResult]:
    transform_spec = truth_source.get("transform_spec", {}) if isinstance(truth_source.get("transform_spec", {}), dict) else {}
    results: list[EvaluationRequirementResult] = []
    for step in transform_spec.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        if str(step.get("name", "")).lower() != "neutralization":
            continue
        controls = [str(control) for control in step.get("controls", []) or []]
        for control in controls:
            resolved = _resolve_requirement(control, profile)
            results.append(
                EvaluationRequirementResult(
                    requirement=control,
                    category="transform_control",
                    paper_value=control,
                    available_value=resolved["available_value"],
                    availability=resolved["availability"],
                    substitute=resolved["substitute"],
                    severity="material" if resolved["availability"] == "missing" else "minor",
                    affected_metrics=metrics or ["*"],
                    recommended_action="use_transform_control" if resolved["availability"] != "missing" else "drop_or_defer_transform_control",
                )
            )
    return results


def _parse_period_bounds(value: str) -> tuple[str, str]:
    dates = re.findall(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", value)
    if len(dates) >= 2:
        return _normalize_date(dates[0]), _normalize_date(dates[1])
    return "", ""


def _normalize_date(value: str) -> str:
    parsed = pd.to_datetime(value.replace("/", "-").replace(".", "-"), errors="coerce")
    return parsed.date().isoformat() if pd.notna(parsed) else ""
