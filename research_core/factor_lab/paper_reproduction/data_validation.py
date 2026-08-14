from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from research_core.factor_lab.paper_reproduction.extraction import ExtractedFactor, ExtractedFactorDefinition
from research_core.factor_lab.paper_reproduction.methodology import canonical_transform_method, transformed_input_methods


FIELD_RELATIONSHIP_TYPES = {
    "exact_alias",
    "derived_equivalent",
    "proxy_substitute",
    "unsupported_substitute",
}


@dataclass(slots=True)
class FieldRelationship:
    """A declared semantic relationship between a paper field and a physical field.

    Relationships describe semantics only.  A derivation is not considered
    executable until its output column has actually been materialized in the
    profiled frame.
    """

    paper_field: str
    physical_field: str
    relationship: str
    reason: str = ""
    expected_effect: str = ""
    derivation: dict[str, Any] = field(default_factory=dict)
    requires_reporting: bool = False
    selection_mode: str = "automatic"
    source: str = "built_in"

    def __post_init__(self) -> None:
        if self.relationship not in FIELD_RELATIONSHIP_TYPES:
            raise ValueError(f"Unsupported field relationship: {self.relationship}")


DEFAULT_FIELD_RELATIONSHIPS: tuple[FieldRelationship, ...] = (
    FieldRelationship(
        "market_cap_or_log_market_cap",
        "log_market_cap",
        "exact_alias",
        reason="The semantic requirement explicitly permits log market capitalization.",
    ),
    FieldRelationship(
        "market_cap_or_log_market_cap",
        "market_cap",
        "exact_alias",
        reason="The semantic requirement explicitly permits market capitalization.",
    ),
    FieldRelationship(
        "free_float_market_cap",
        "market_cap",
        "proxy_substitute",
        reason="Total market capitalization is available but free-float capitalization is not.",
        expected_effect="Capitalization definition differs and may change weighted or controlled regression results.",
        requires_reporting=True,
    ),
    FieldRelationship(
        "sqrt_free_float_market_cap",
        "sqrt_total_market_cap",
        "proxy_substitute",
        reason="Square-root total capitalization differs from square-root free-float capitalization.",
        expected_effect="Regression weights differ from the paper definition.",
        requires_reporting=True,
    ),
    FieldRelationship(
        "sqrt_free_float_market_cap",
        "free_float_market_cap",
        "derived_equivalent",
        reason="The requested weight can be derived by taking the square root.",
        derivation={"method": "sqrt", "inputs": ["free_float_market_cap"]},
        requires_reporting=True,
    ),
    FieldRelationship(
        "sqrt_free_float_market_cap",
        "market_cap",
        "proxy_substitute",
        reason="Only total capitalization is available and a square-root transform would still be required.",
        expected_effect="Both capitalization definition and regression-weight transform differ until materialized.",
        derivation={"method": "sqrt", "inputs": ["market_cap"]},
        requires_reporting=True,
    ),
    FieldRelationship(
        "st_or_pt_status",
        "is_st",
        "proxy_substitute",
        reason="The provider flag may not encode every ST/PT distinction required by the paper.",
        expected_effect="Universe membership may differ on affected dates.",
        requires_reporting=True,
    ),
    FieldRelationship(
        "next_day_suspension_status",
        "next_is_suspended",
        "exact_alias",
        reason="The physical field uses the same next-trading-day suspension semantics.",
    ),
    FieldRelationship(
        "next_day_suspension_status",
        "is_suspended",
        "unsupported_substitute",
        reason="Same-day suspension cannot stand in for next-trading-day suspension without an explicit timing rule.",
        expected_effect="Using the field would apply the universe filter on the wrong date.",
        requires_reporting=True,
    ),
    FieldRelationship(
        "suspension_status",
        "is_suspended",
        "exact_alias",
        reason="The physical field represents same-day suspension status.",
    ),
    FieldRelationship(
        "tradability_status",
        "is_trading",
        "proxy_substitute",
        reason="A provider trading flag may not implement the paper's complete tradability rule.",
        expected_effect="The evaluation universe may differ from the paper.",
        requires_reporting=True,
    ),
    FieldRelationship(
        "industry_classification",
        "industry",
        "proxy_substitute",
        reason="The available taxonomy and point-in-time semantics may differ from the paper.",
        expected_effect="Neutralization controls and residual factor exposures may differ.",
        requires_reporting=True,
    ),
    FieldRelationship(
        "industry_classification",
        "industry_code",
        "proxy_substitute",
        reason="The available taxonomy and point-in-time semantics may differ from the paper.",
        expected_effect="Neutralization controls and residual factor exposures may differ.",
        requires_reporting=True,
    ),
    FieldRelationship("industry_or_sector", "industry", "exact_alias"),
    FieldRelationship("industry_or_sector", "sector", "exact_alias"),
    FieldRelationship("trading_calendar", "trade_date", "exact_alias"),
    FieldRelationship("benchmark_index_level", "close", "exact_alias"),
    FieldRelationship("benchmark_return", "benchmark_return", "exact_alias"),
    FieldRelationship("market_benchmark_return", "benchmark_return", "exact_alias"),
    FieldRelationship("index_membership", "component_code", "exact_alias"),
    FieldRelationship("index_constituents", "component_code", "exact_alias"),
    FieldRelationship("index_weight", "weight", "exact_alias"),
    FieldRelationship("risk_free_rate", "risk_free_rate", "exact_alias"),
)


@dataclass(slots=True)
class DataFrameValidationRequest:
    factor_name: str
    required_columns: list[str]
    frequency: str = ""
    required_lookback: int = 0
    date_column: str = "date"
    code_column: str = "code"

    @classmethod
    def from_factor(cls, factor: ExtractedFactor | ExtractedFactorDefinition) -> DataFrameValidationRequest:
        if isinstance(factor, ExtractedFactorDefinition):
            return cls(
                factor_name=factor.factor_id,
                required_columns=["date", "code", *[_canonical_formula_field_id(item) for item in factor.required_semantic_fields]],
                frequency=factor.native_frequency,
                required_lookback=_infer_required_lookback(factor.parameters),
            )
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
    field_relationships: list[dict[str, Any]] = field(default_factory=list)


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
    candidate_field: str = ""
    relationship: str = "exact_alias"
    semantic_availability: str = "not_assessed"
    coverage_ratio: float | None = None
    execution_ready: bool = False
    pipeline_blocking: bool = False
    source_contexts: list[str] = field(default_factory=list)
    semantic_definition: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvaluationCaseSupportAssessment:
    truth_id: str
    support_score: float
    comparability: str
    assessment_id: str = ""
    assessment_scope: str = ""
    evaluator_capability_fingerprint: str = ""
    requirement_results: list[EvaluationRequirementResult] = field(default_factory=list)
    deviations: list[dict[str, Any]] = field(default_factory=list)
    truth_match_eligible_metrics: list[str] = field(default_factory=list)
    diagnostic_only_metrics: list[str] = field(default_factory=list)
    lifecycle_state: str = "assessed"
    selection_reason: str = ""
    score_components: dict[str, float] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    replacement_records: list[dict[str, Any]] = field(default_factory=list)
    case_executable: bool = True

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
    field_relationships: list[FieldRelationship | dict[str, Any]] | None = None,
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

    resolved_conventions = dict(conventions or {})
    for attribute in (
        "market_cap_fields",
        "market_cap_lineage",
        "industry_classification",
        "financial_statement_selection",
        "valuation_selection",
        "dividend_history_selection",
        "trading_calendar_selection",
        "index_reference_selection",
        "yield_curve_selection",
        "forward_return_lineage",
    ):
        if attribute in frame.attrs:
            resolved_conventions.setdefault(attribute, frame.attrs[attribute])
    if "price_adjustment" in frame.columns:
        price_views = [str(value) for value in frame["price_adjustment"].dropna().unique()]
        resolved_conventions.setdefault("price_adjustment", price_views[0] if len(price_views) == 1 else price_views)
    if "adjustment_anchor_date" in frame.columns:
        anchor_dates = pd.to_datetime(frame["adjustment_anchor_date"], errors="coerce").dropna().unique()
        if len(anchor_dates) == 1:
            resolved_conventions.setdefault("adjustment_anchor_date", pd.Timestamp(anchor_dates[0]).date().isoformat())

    resolved_derived_fields = [dict(item) for item in (derived_fields or [])]
    market_cap_lineage = resolved_conventions.get("market_cap_lineage", {})
    if isinstance(market_cap_lineage, dict):
        for field_name, raw_lineage in market_cap_lineage.items():
            if not isinstance(raw_lineage, dict) or not raw_lineage.get("derived"):
                continue
            if any(item.get("field") == field_name for item in resolved_derived_fields):
                continue
            resolved_derived_fields.append(
                {
                    "field": field_name,
                    "sources": ["free_circulation", "implied_unadjusted_close"],
                    "formula": "free_circulation * implied_unadjusted_close",
                    "source_field": raw_lineage.get("source_field", field_name),
                    "price_basis": raw_lineage.get("price_basis", "unadjusted"),
                    "source": "recommended_data_v2",
                    "reason": "RQData free-float capitalization is materialized from PIT share history and implied unadjusted close.",
                }
            )
            limitations.append(
                "free-float capitalization retains provider missing values and documented free-circulation share inconsistencies"
            )
    forward_lineage = resolved_conventions.get("forward_return_lineage", {})
    if isinstance(forward_lineage, dict) and forward_lineage.get("field"):
        if not any(item.get("field") == forward_lineage["field"] for item in resolved_derived_fields):
            resolved_derived_fields.append(dict(forward_lineage))

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
        conventions=resolved_conventions,
        derived_fields=resolved_derived_fields,
        field_relationships=[asdict(item) if isinstance(item, FieldRelationship) else dict(item) for item in (field_relationships or [])],
        limitations=limitations,
    )


def materialize_forward_return(
    frame: pd.DataFrame,
    horizon: int,
    *,
    price_col: str = "close",
    output_col: str | None = None,
    date_col: str = "date",
    security_col: str = "code",
    copy: bool = True,
) -> pd.DataFrame:
    """Materialize a trading-observation forward return without changing row order."""

    if horizon <= 0:
        raise ValueError("horizon must be a positive integer")
    required = [date_col, security_col, price_col]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"forward return inputs are missing columns: {missing}")
    result = frame.copy() if copy else frame
    row_order_col = "__paper_reproduction_row_order__"
    while row_order_col in result.columns:
        row_order_col += "_"
    result[row_order_col] = range(len(result))
    ordered = result.sort_values([security_col, date_col], kind="stable")
    future_price = ordered.groupby(security_col, sort=False)[price_col].shift(-horizon)
    column = output_col or f"forward_return_{horizon}d"
    ordered[column] = future_price.div(ordered[price_col]).sub(1)
    result[column] = ordered.sort_values(row_order_col, kind="stable")[column].to_numpy()
    result.drop(columns=[row_order_col], inplace=True)
    result.attrs["forward_return_lineage"] = {
        "field": column,
        "horizon": horizon,
        "horizon_unit": "security_trading_observations",
        "target_rule": "per-security shift(-horizon)",
        "price_col": price_col,
    }
    return result


def assess_evaluation_case_support(
    truth_source: dict[str, Any],
    data_profile: DataProfile | dict[str, Any],
    evaluator_capabilities: dict[str, Any] | None = None,
    *,
    field_relationships: list[FieldRelationship | dict[str, Any]] | None = None,
    assessment_scope: str = "",
) -> EvaluationCaseSupportAssessment:
    profile = dict(data_profile) if isinstance(data_profile, dict) else asdict(data_profile)
    if field_relationships is not None:
        profile["field_relationships"] = [
            asdict(item) if isinstance(item, FieldRelationship) else dict(item)
            for item in field_relationships
        ]
    evaluator_capabilities = evaluator_capabilities or {}
    capability_fingerprint = _stable_payload_hash(evaluator_capabilities)
    truth_id = str(truth_source.get("truth_id", ""))
    metrics = list((truth_source.get("metrics", {}) or {}).keys())
    requirement_results: list[EvaluationRequirementResult] = []
    methodology_deviations = _methodology_uncertainty_deviations(truth_source, metrics)
    deviations: list[dict[str, Any]] = list(methodology_deviations)
    semantic_definitions = {
        str(item.get("semantic_field_id")): dict(item)
        for item in truth_source.get("semantic_requirements", []) or []
        if isinstance(item, dict) and item.get("semantic_field_id")
    }

    required_data = truth_source.get("required_data", {}) if isinstance(truth_source.get("required_data", {}), dict) else {}
    for category, raw_requirements in required_data.items():
        requirements = raw_requirements if isinstance(raw_requirements, list) else [raw_requirements]
        for requirement in [str(value) for value in requirements if str(value)]:
            semantic_definition = semantic_definitions.get(requirement, {})
            resolved = (
                _resolve_semantic_requirement(semantic_definition, profile)
                if semantic_definition
                else _resolve_requirement(requirement, profile)
            )
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
                source_contexts=[f"required_data.{category}"],
                severity=severity if availability != "constructible" else "minor",
                affected_metrics=affected,
                recommended_action=action,
                semantic_definition=semantic_definition,
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

    referenced_requirements = {
        result.requirement for result in requirement_results
    }
    for semantic_id, definition in semantic_definitions.items():
        if semantic_id in referenced_requirements or str(definition.get("kind", "")) == "evaluation_input":
            continue
        resolved = _resolve_semantic_requirement(definition, profile)
        requirement_results.append(
            EvaluationRequirementResult(
                requirement=semantic_id,
                category="formula_semantic" if str(definition.get("kind", "")) == "market_data" else str(definition.get("kind", "semantic_input")),
                paper_value=definition,
                available_value=resolved["available_value"],
                availability=resolved["availability"],
                substitute=resolved["substitute"],
                severity="material" if resolved["relationship"] in {"proxy_substitute", "unsupported_substitute"} else "minor",
                affected_metrics=metrics or ["*"],
                recommended_action="use_requested_field" if resolved["execution_ready"] else "resolve_semantic_requirement",
                semantic_definition=definition,
                source_contexts=["semantic_requirements"],
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

    supported_operation_capabilities = set(
        evaluator_capabilities.get("capabilities", {}).get("operation_pipeline_capabilities", []) or []
    )
    for capability in truth_source.get("operation_capability_requirements", []) or []:
        available = str(capability) in supported_operation_capabilities
        requirement_results.append(
            EvaluationRequirementResult(
                requirement=str(capability),
                category="operation_capability",
                paper_value=str(capability),
                available_value=str(capability) if available else None,
                availability="available" if available else "missing",
                severity="fundamental" if not available else "minor",
                affected_metrics=metrics or ["*"],
                recommended_action="execute" if available else "paper_local_joint_evaluator_or_select_alternative_truth",
                relationship="exact_alias" if available else "unsupported_substitute",
                semantic_availability="exactly_available" if available else "missing",
                execution_ready=available,
                pipeline_blocking=False,
                source_contexts=["operation_capability_requirements"],
            )
        )
        if not available:
            deviations.append(
                structured_deviation(
                    category="operation_capability",
                    paper_value=str(capability),
                    resolved_value=None,
                    reason="The generic evaluator cannot execute this joint operation pipeline.",
                    severity="fundamental",
                    affected_metrics=metrics or ["*"],
                    truth_matching_policy="not_evaluated",
                )
            )

    requirement_results = _deduplicate_requirement_results(requirement_results)
    for result in requirement_results:
        _enrich_requirement_result(result, profile)

    replacement_records = [
        record
        for result in requirement_results
        if (record := _replacement_record(result, profile)) is not None
    ]
    deviations.extend(_relationship_deviations(requirement_results, replacement_records))
    capitalization_deviations = _capitalization_inference_deviations(
        requirement_results,
        profile,
    )
    deviations.extend(capitalization_deviations)
    deviations = _deduplicate_deviations(deviations)

    missing_count = sum(1 for result in requirement_results if result.availability == "missing")
    partial_count = sum(
        1
        for result in requirement_results
        if result.availability in {"partially_available", "available_with_quality_warning", "constructible"}
    )
    proxy_count = sum(1 for result in requirement_results if result.relationship == "proxy_substitute" and result.execution_ready)
    methodology_proxy_count = len(methodology_deviations) + len(capitalization_deviations)
    constructible_count = sum(1 for result in requirement_results if result.semantic_availability == "constructible")
    data_coverage = (
        1.0
        if not requirement_results
        else max(
            0.0,
            1.0
            - missing_count / len(requirement_results)
            - partial_count * 0.2 / len(requirement_results)
            - (proxy_count + constructible_count + methodology_proxy_count) * 0.35 / max(len(requirement_results), 1),
        )
    )
    evaluator_coverage = 0.0 if capability_result.availability == "missing" else 1.0
    metric_coverage = 1.0 if metrics else 0.0
    support_score = round(0.45 * data_coverage + 0.35 * evaluator_coverage + 0.20 * metric_coverage, 6)
    comparability = _comparability_from_support(
        missing_count,
        partial_count,
        capability_result.availability,
        proxy_count=proxy_count + constructible_count + methodology_proxy_count,
    )
    case_executable = _case_is_executable(requirement_results)
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
    if truth_source.get("paper_truth_conflict"):
        eligible = []
        diagnostic = list(metrics)
        deviations.append(
            structured_deviation(
                category="paper_truth_conflict",
                paper_value=truth_source.get("conflict_group_id"),
                resolved_value=None,
                reason="Conflicting paper result blocks share this semantic protocol; extraction review has not established precedence.",
                severity="fundamental",
                affected_metrics=metrics or ["*"],
                truth_matching_policy="not_evaluated",
                source="paper_extraction_review",
            )
        )
    return EvaluationCaseSupportAssessment(
        truth_id=truth_id,
        support_score=support_score,
        comparability=comparability,
        assessment_id="support-"
        + _stable_payload_hash(
            {
                "truth_source": truth_source,
                "data_profile": profile,
                "evaluator_capability_fingerprint": capability_fingerprint,
                "assessment_scope": assessment_scope,
            }
        )[:20],
        assessment_scope=assessment_scope,
        evaluator_capability_fingerprint=capability_fingerprint,
        requirement_results=requirement_results,
        deviations=deviations,
        truth_match_eligible_metrics=eligible,
        diagnostic_only_metrics=diagnostic,
        replacement_records=replacement_records,
        case_executable=case_executable,
        score_components={
            "required_data_coverage": round(data_coverage, 6),
            "evaluator_capability_coverage": evaluator_coverage,
            "metric_coverage": metric_coverage,
            "proxy_substitution_count": float(proxy_count),
            "inferred_methodology_count": float(methodology_proxy_count),
            "capitalization_inference_count": float(len(capitalization_deviations)),
            "constructible_not_materialized_count": float(constructible_count),
        },
        limitations=[dev["reason"] for dev in deviations],
    )


def _stable_payload_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    relationship: str = "",
) -> dict[str, Any]:
    payload = {
        "category": category,
        "paper_value": paper_value,
        "resolved_value": resolved_value,
        "reason": reason,
        "severity": severity,
        "affected_metrics": affected_metrics,
        "truth_matching_policy": truth_matching_policy,
        "source": source,
    }
    if relationship:
        payload["relationship"] = relationship
    return payload


def _methodology_uncertainty_deviations(
    truth_source: dict[str, Any],
    metrics: list[str],
) -> list[dict[str, Any]]:
    pipeline = truth_source.get("operation_pipeline", {}) or {}
    operations = pipeline.get("operations", []) if isinstance(pipeline, dict) else []
    deviations: list[dict[str, Any]] = []
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        source = str(operation.get("source", "")).strip().lower()
        if source not in {"inferred", "default_assumed", "defaulted", "not_specified"}:
            continue
        operation_type = str(operation.get("type", "operation") or "operation")
        method = str(operation.get("method", "") or "unspecified")
        deviations.append(
            structured_deviation(
                category="methodology_inference",
                paper_value={"operation_type": operation_type, "method": "not_explicitly_stated"},
                resolved_value={"operation_type": operation_type, "method": method},
                reason=(
                    f"{operation_type} method {method} is {source} rather than explicit paper methodology"
                ),
                severity="material",
                affected_metrics=metrics or ["*"],
                truth_matching_policy="proxy_or_partial_period",
                source="paper_operation_pipeline",
                relationship="proxy_substitute",
            )
        )
    return deviations


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


def _resolve_semantic_requirement(definition: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    semantic_id = str(definition.get("semantic_field_id", ""))
    kind = str(definition.get("kind", ""))
    concept = str(definition.get("concept", ""))
    columns = set(str(column) for column in profile.get("columns", []) or [])
    conventions = profile.get("conventions", {}) if isinstance(profile.get("conventions", {}), dict) else {}

    # Stage 3 may explicitly bind an otherwise paper-specific semantic ID to a
    # materialized field. Preserve the declared relationship class verbatim:
    # proxies stay proxies and unsupported substitutes stay unavailable. Exact
    # aliases for typed classification/capitalization still pass through their
    # dedicated semantic checks below.
    declared_relationships = _profile_declared_relationships(semantic_id, profile)
    relationship_candidates: list[dict[str, Any]] = []
    for relationship in declared_relationships:
        if relationship.relationship == "exact_alias" and kind in {"classification", "capitalization"}:
            continue
        physical_available = relationship.physical_field in columns
        if relationship.relationship == "unsupported_substitute":
            if physical_available:
                relationship_candidates.append(
                    _relationship_resolution(
                        relationship,
                        availability="missing",
                        semantic_availability="not_assessed",
                        execution_ready=False,
                        profile=profile,
                    )
                )
        elif physical_available and relationship.derivation:
            relationship_candidates.append(
                _relationship_resolution(
                    relationship,
                    availability="constructible",
                    semantic_availability="constructible",
                    execution_ready=False,
                    profile=profile,
                )
            )
        elif physical_available:
            relationship_candidates.append(
                _available_field_resolution(
                    relationship.physical_field,
                    profile,
                    relationship=relationship.relationship,
                    paper_field=semantic_id,
                    relationship_record=relationship,
                )
            )
    if relationship_candidates:
        return min(relationship_candidates, key=_resolution_priority)

    if kind == "classification":
        physical = "industry" if "industry" in columns else "industry_code" if "industry_code" in columns else ""
        if not physical:
            return _missing_semantic_resolution()
        selected = conventions.get("industry_classification", {}) or {}
        selected_source = str(selected.get("source", "")).lower()
        selected_level = selected.get("level")
        expected_family = str(definition.get("taxonomy_family", "")).lower()
        expected_level = definition.get("taxonomy_level")
        expected_revision = str(definition.get("taxonomy_revision", "not_specified")).lower()
        family_match = (
            expected_family == "citic" and selected_source in {"citics", "citics_2019"}
        ) or expected_family in {"", selected_source}
        level_match = expected_level in (None, "") or int(selected_level or -1) == int(expected_level)
        revision_match = (
            expected_revision in {"", "not_specified"}
            or ("2019" in expected_revision and selected_source == "citics_2019")
            or ("2019" not in expected_revision and selected_source == "citics")
        )
        interval_rule = str(selected.get("interval_rule", ""))
        timing_match = not interval_rule or interval_rule == "start_date <= date < cancel_date"
        exact = family_match and level_match and revision_match and timing_match
        relationship = FieldRelationship(
            semantic_id,
            physical,
            "exact_alias" if exact else "proxy_substitute",
            reason=(
                "Local point-in-time industry source, level, and interval timing match the paper semantic requirement."
                if exact
                else "Local industry taxonomy source, revision, level, or effective-date semantics differ from the paper requirement."
            ),
            expected_effect="Industry residualization cross-sections may differ." if not exact else "",
            requires_reporting=not exact,
            source="semantic_requirement_resolver",
        )
        return _available_field_resolution(
            physical,
            profile,
            relationship=relationship.relationship,
            paper_field=semantic_id,
            relationship_record=relationship,
        )

    if kind == "capitalization":
        basis = str(definition.get("cap_basis", ""))
        physical_by_basis = {
            "total_company": "market_cap",
            "total_a_share": "a_share_market_cap",
            "circulating_a": "circulating_market_cap",
            "free_float": "free_float_market_cap",
        }
        physical = physical_by_basis.get(basis, "")
        if not physical or physical not in columns:
            return _missing_semantic_resolution(candidate_field=physical)
        relationship = FieldRelationship(
            semantic_id,
            physical,
            "exact_alias",
            reason=f"Local capitalization field preserves the paper's {basis} basis.",
            source="semantic_requirement_resolver",
        )
        return _available_field_resolution(
            physical,
            profile,
            relationship="exact_alias",
            paper_field=semantic_id,
            relationship_record=relationship,
        )

    if kind in {"market_data", "derived_style_control"}:
        physical = _canonical_semantic_physical_field(semantic_id, concept)
        if physical in columns:
            relationship = FieldRelationship(
                semantic_id,
                physical,
                "exact_alias",
                reason="Canonical local field matches the extracted semantic concept.",
                source="semantic_requirement_resolver",
            )
            return _available_field_resolution(
                physical,
                profile,
                relationship="exact_alias",
                paper_field=semantic_id,
                relationship_record=relationship,
            )
        return _missing_semantic_resolution(candidate_field=physical)

    if kind == "evaluation_universe_filter":
        return _resolve_requirement(semantic_id, profile)

    return _resolve_requirement(semantic_id, profile)


def _missing_semantic_resolution(*, candidate_field: str = "") -> dict[str, Any]:
    return {
        "availability": "missing",
        "semantic_availability": "missing",
        "available_value": None,
        "candidate_field": candidate_field,
        "substitute": None,
        "relationship": "unsupported_substitute",
        "relationship_record": None,
        "coverage_ratio": 0.0,
        "execution_ready": False,
    }


def _canonical_semantic_physical_field(semantic_id: str, concept: str) -> str:
    aliases = {
        "daily_open_price": "open",
        "daily_close_price": "close",
        "daily_high_price": "high",
        "daily_low_price": "low",
        "daily_trading_volume": "volume",
        "daily_volume_weighted_average_price": "vwap",
        "past_20_trading_day_return": "style_return_20d",
        "past_20_trading_day_average_turnover": "style_average_turnover_20d",
        "past_20_trading_day_volatility": "style_volatility_20d",
    }
    return aliases.get(concept, semantic_id)


def _canonical_formula_field_id(semantic_id: str) -> str:
    aliases = {
        "daily_open": "open",
        "daily_close": "close",
        "daily_high": "high",
        "daily_low": "low",
        "daily_volume": "volume",
        "daily_vwap": "vwap",
    }
    return aliases.get(semantic_id, semantic_id.removeprefix("daily_"))


def _resolve_requirement(field: str, profile: dict[str, Any]) -> dict[str, Any]:
    columns = set(str(column) for column in (profile.get("columns", []) or []))
    derived_fields = {
        str(item.get("field")): dict(item)
        for item in (profile.get("derived_fields", []) or [])
        if isinstance(item, dict) and item.get("field")
    }
    relationships = _relationships_for_requirement(field, profile)
    custom_self_relationship = next(
        (
            relationship
            for relationship in relationships
            if relationship.physical_field == field and relationship.source != "built_in"
        ),
        None,
    )
    if field in columns and field in derived_fields and custom_self_relationship is None:
        lineage = derived_fields[field]
        return _available_field_resolution(
            field,
            profile,
            relationship="derived_equivalent",
            paper_field=field,
            relationship_record=FieldRelationship(
                field,
                field,
                "derived_equivalent",
                reason=str(lineage.get("reason", "The required field was materialized from declared source fields.")),
                derivation=lineage,
                requires_reporting=True,
                source=str(lineage.get("source", "data_profile")),
            ),
        )
    if field in columns and custom_self_relationship is None:
        return _available_field_resolution(
            field,
            profile,
            relationship="exact_alias",
            paper_field=field,
        )

    candidates: list[dict[str, Any]] = []
    for relationship in relationships:
        physical_available = relationship.physical_field in columns
        derivation_declared = bool(relationship.derivation)
        if relationship.relationship == "unsupported_substitute" and physical_available:
            candidates.append(
                _relationship_resolution(
                    relationship,
                    availability="missing",
                    semantic_availability="not_assessed",
                    execution_ready=False,
                    profile=profile,
                )
            )
        elif physical_available and derivation_declared:
            candidates.append(
                _relationship_resolution(
                    relationship,
                    availability="constructible",
                    semantic_availability="constructible",
                    execution_ready=False,
                    profile=profile,
                )
            )
        elif physical_available:
            candidates.append(
                _available_field_resolution(
                    relationship.physical_field,
                    profile,
                    relationship=relationship.relationship,
                    paper_field=field,
                    relationship_record=relationship,
                )
            )
        elif field in derived_fields or relationship.physical_field in derived_fields:
            candidates.append(
                _relationship_resolution(
                    relationship,
                    availability="constructible",
                    semantic_availability="constructible",
                    execution_ready=False,
                    profile=profile,
                )
            )

    if candidates:
        return min(candidates, key=_resolution_priority)
    if field in derived_fields:
        return {
            "availability": "constructible",
            "semantic_availability": "constructible",
            "available_value": None,
            "candidate_field": field,
            "substitute": None,
            "relationship": "derived_equivalent",
            "relationship_record": None,
            "coverage_ratio": None,
            "execution_ready": False,
        }
    return {
        "availability": "missing",
        "semantic_availability": "missing",
        "available_value": None,
        "candidate_field": "",
        "substitute": None,
        "relationship": "unsupported_substitute",
        "relationship_record": None,
        "coverage_ratio": 0.0,
        "execution_ready": False,
    }


def _relationships_for_requirement(field: str, profile: dict[str, Any]) -> list[FieldRelationship]:
    custom = _profile_declared_relationships(field, profile)

    dynamic: list[FieldRelationship] = []
    lowered = field.lower()
    match = re.fullmatch(r"forward_return_(\d+)d", lowered)
    if match:
        dynamic.append(FieldRelationship(field, f"forward_return_t{match.group(1)}", "exact_alias"))
    match = re.fullmatch(r"forward_return_t(\d+)", lowered)
    if match:
        dynamic.append(FieldRelationship(field, f"forward_return_{match.group(1)}d", "exact_alias"))

    overridden_pairs = {(item.paper_field, item.physical_field) for item in custom}
    built_in = [
        item
        for item in DEFAULT_FIELD_RELATIONSHIPS
        if item.paper_field == field and (item.paper_field, item.physical_field) not in overridden_pairs
    ]
    return [*custom, *dynamic, *built_in]


def _profile_declared_relationships(field: str, profile: dict[str, Any]) -> list[FieldRelationship]:
    """Return only relationships explicitly persisted in this data profile."""

    custom: list[FieldRelationship] = []
    for item in profile.get("field_relationships", []) or []:
        if isinstance(item, FieldRelationship):
            relationship = item
        elif isinstance(item, dict):
            try:
                relationship = FieldRelationship(**item)
            except (TypeError, ValueError):
                continue
        else:
            continue
        if relationship.paper_field == field:
            custom.append(relationship)
    return custom


def _available_field_resolution(
    physical_field: str,
    profile: dict[str, Any],
    *,
    relationship: str,
    paper_field: str,
    relationship_record: FieldRelationship | None = None,
) -> dict[str, Any]:
    missing_ratio = float((profile.get("missingness", {}) or {}).get(physical_field, 0.0) or 0.0)
    if missing_ratio == 0:
        availability = "available"
    elif missing_ratio < 0.2:
        availability = "available_with_quality_warning"
    else:
        availability = "partially_available"
    semantic_availability = (
        "replacement_available"
        if relationship == "proxy_substitute"
        else "exactly_available" if missing_ratio == 0 else "available_with_missingness"
    )
    return {
        "availability": availability,
        "semantic_availability": semantic_availability,
        "available_value": physical_field,
        "candidate_field": physical_field,
        "substitute": physical_field if physical_field != paper_field else None,
        "relationship": relationship,
        "relationship_record": relationship_record,
        "coverage_ratio": max(0.0, 1.0 - missing_ratio),
        "execution_ready": True,
    }


def _relationship_resolution(
    relationship: FieldRelationship,
    *,
    availability: str,
    semantic_availability: str,
    execution_ready: bool,
    profile: dict[str, Any],
) -> dict[str, Any]:
    missing_ratio = float((profile.get("missingness", {}) or {}).get(relationship.physical_field, 0.0) or 0.0)
    return {
        "availability": availability,
        "semantic_availability": semantic_availability,
        "available_value": relationship.physical_field if execution_ready else None,
        "candidate_field": relationship.physical_field,
        "substitute": relationship.physical_field,
        "relationship": relationship.relationship,
        "relationship_record": relationship,
        "coverage_ratio": max(0.0, 1.0 - missing_ratio) if relationship.physical_field in set(profile.get("columns", []) or []) else None,
        "execution_ready": execution_ready,
    }


def _resolution_priority(resolution: dict[str, Any]) -> tuple[int, int, str]:
    relationship_rank = {
        "exact_alias": 0,
        "derived_equivalent": 1,
        "proxy_substitute": 2,
        "unsupported_substitute": 3,
    }
    return (
        0 if resolution.get("execution_ready") else 1,
        relationship_rank.get(str(resolution.get("relationship", "")), 4),
        str(resolution.get("candidate_field", "")),
    )


def _enrich_requirement_result(result: EvaluationRequirementResult, profile: dict[str, Any]) -> None:
    if result.category == "sample_period":
        result.semantic_availability = _semantic_availability_from_legacy(result.availability)
        result.execution_ready = result.availability != "missing"
        result.source_contexts = result.source_contexts or ["truth_source.sample_period"]
        return
    if result.category in {"evaluator_capability", "operation_capability"}:
        result.semantic_availability = "exactly_available" if result.availability == "available" else "missing"
        result.execution_ready = result.availability == "available"
        result.relationship = "exact_alias" if result.execution_ready else "unsupported_substitute"
        result.source_contexts = result.source_contexts or [result.category]
        return

    resolved = (
        _resolve_semantic_requirement(result.semantic_definition, profile)
        if result.semantic_definition
        else _resolve_requirement(result.requirement, profile)
    )
    result.availability = str(resolved["availability"])
    result.semantic_availability = str(resolved["semantic_availability"])
    result.available_value = resolved["available_value"]
    result.candidate_field = str(resolved.get("candidate_field", "") or "")
    result.substitute = resolved["substitute"]
    result.relationship = str(resolved["relationship"])
    result.coverage_ratio = resolved.get("coverage_ratio")
    result.execution_ready = bool(resolved["execution_ready"])
    result.pipeline_blocking = False
    result.source_contexts = result.source_contexts or [f"evaluation_case.{result.category}"]
    if result.relationship in {"proxy_substitute", "unsupported_substitute"}:
        result.severity = "material"
    if not result.execution_ready:
        result.recommended_action = (
            "construct_before_execution"
            if result.semantic_availability == "constructible"
            else "reject_substitute_and_degrade"
        )
    elif result.relationship == "proxy_substitute":
        result.recommended_action = "use_proxy_and_report_limitation"


def _semantic_availability_from_legacy(availability: str) -> str:
    if availability == "available":
        return "exactly_available"
    if availability in {"partially_available", "available_with_quality_warning"}:
        return "available_with_missingness"
    if availability == "constructible":
        return "constructible"
    if availability == "missing":
        return "missing"
    return "not_assessed"


def _deduplicate_requirement_results(
    results: list[EvaluationRequirementResult],
) -> list[EvaluationRequirementResult]:
    merged: dict[tuple[str, str], EvaluationRequirementResult] = {}
    severity_rank = {"cosmetic": 0, "minor": 1, "material": 2, "fundamental": 3}
    for result in results:
        key = (result.category, result.requirement)
        if key not in merged:
            merged[key] = result
            continue
        current = merged[key]
        current.affected_metrics = _dedupe_strings([*current.affected_metrics, *result.affected_metrics])
        current.source_contexts = _dedupe_strings([*current.source_contexts, *result.source_contexts])
        if severity_rank.get(result.severity, 0) > severity_rank.get(current.severity, 0):
            current.severity = result.severity
        if current.available_value is None and result.available_value is not None:
            current.available_value = result.available_value
        if not current.substitute and result.substitute:
            current.substitute = result.substitute
    return list(merged.values())


def _replacement_record(
    result: EvaluationRequirementResult,
    profile: dict[str, Any],
) -> dict[str, Any] | None:
    if result.category in {"sample_period", "evaluator_capability"}:
        return None
    if result.relationship not in {"derived_equivalent", "proxy_substitute", "unsupported_substitute"}:
        return None
    if result.relationship == "unsupported_substitute" and not (result.candidate_field or result.substitute):
        return None
    resolved = (
        _resolve_semantic_requirement(result.semantic_definition, profile)
        if result.semantic_definition
        else _resolve_requirement(result.requirement, profile)
    )
    relationship = resolved.get("relationship_record")
    if isinstance(relationship, FieldRelationship):
        relationship_payload = asdict(relationship)
    else:
        relationship_payload = {}
    if result.relationship == "proxy_substitute" and result.execution_ready:
        status = "accepted_proxy"
        accepted = True
        comparability = "proxy"
    elif result.relationship == "derived_equivalent" and result.execution_ready:
        status = "constructed_equivalent"
        accepted = True
        comparability = "exact"
    elif result.semantic_availability == "constructible":
        status = "constructible_not_materialized"
        accepted = False
        comparability = "not_yet_comparable"
    else:
        status = "rejected_candidate"
        accepted = False
        comparability = "not_comparable"
    return {
        "required_semantic_role": result.category,
        "paper_definition": result.requirement,
        "replacement_field": result.available_value or result.candidate_field or result.substitute,
        "relationship": result.relationship,
        "status": status,
        "accepted": accepted,
        "execution_ready": result.execution_ready,
        "replacement_reason": relationship_payload.get("reason", "No exact semantic field is available."),
        "selection_basis": relationship_payload.get("source", "automatic_resolver"),
        "expected_effect": relationship_payload.get("expected_effect", ""),
        "derivation": relationship_payload.get("derivation", {}),
        "comparability_after_replacement": comparability,
        "selection_mode": relationship_payload.get("selection_mode", "automatic"),
        "coverage_ratio": result.coverage_ratio,
        "affected_metrics": list(result.affected_metrics),
        "pipeline_blocking": False,
        "source_contexts": list(result.source_contexts),
    }


def _relationship_deviations(
    results: list[EvaluationRequirementResult],
    replacements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result_by_key = {(item.category, item.requirement): item for item in results}
    deviations: list[dict[str, Any]] = []
    for replacement in replacements:
        if replacement["status"] in {"rejected_candidate", "constructed_equivalent"}:
            continue
        result = result_by_key[(replacement["required_semantic_role"], replacement["paper_definition"])]
        deviations.append(
            structured_deviation(
                category=result.category,
                paper_value=result.requirement,
                resolved_value=result.available_value,
                reason=str(replacement["replacement_reason"]),
                severity="material" if result.relationship == "proxy_substitute" else "minor",
                affected_metrics=list(result.affected_metrics),
                truth_matching_policy="proxy_or_diagnostic_only",
                relationship=result.relationship,
            )
        )
    return deviations


def _capitalization_inference_deviations(
    results: list[EvaluationRequirementResult],
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    deviations: list[dict[str, Any]] = []
    derived_fields = {
        str(item.get("field")): dict(item)
        for item in profile.get("derived_fields", []) or []
        if isinstance(item, dict) and item.get("field")
    }
    profile_conventions = profile.get("conventions", {}) or {}
    market_cap_control = profile_conventions.get("market_cap_control", {}) or {}

    def _basis_from_text(value: Any) -> str:
        lowered = str(value or "").lower().replace("-", "_").replace(" ", "_")
        if "free_float" in lowered or "freefloat" in lowered:
            return "free_float_market_capitalization"
        if "circulating" in lowered:
            return "circulating_market_capitalization"
        if "a_share" in lowered or "ashare" in lowered:
            return "a_share_market_capitalization"
        if "total" in lowered:
            return "total_market_capitalization"
        return ""

    for result in results:
        definition = result.semantic_definition or {}
        cap_basis = str(definition.get("cap_basis", "") or "").lower()
        concept = str(definition.get("concept", "") or "").lower()
        generic_requirement = result.requirement in {
            "market_cap",
            "market_cap_or_log_market_cap",
            "market_cap_control",
        } or (
            str(definition.get("kind", "")).lower() == "capitalization"
            and cap_basis in {"", "generic", "unspecified", "not_specified"}
            and concept in {"", "market_cap", "market_capitalization"}
        )
        physical_field = str(result.available_value or "")
        if not generic_requirement or not physical_field or not result.execution_ready:
            continue
        lowered = physical_field.lower()
        basis = _basis_from_text(physical_field)
        if not basis and result.requirement == "market_cap_control":
            basis = _basis_from_text(market_cap_control.get("basis"))
            if not basis:
                basis = _basis_from_text(market_cap_control.get("physical_field"))
        if not basis and lowered.startswith(("log_market_cap", "sqrt_market_cap")):
            basis = "basis_under_transformed_market_cap_not_declared"
        if basis:
            deviations.append(
                structured_deviation(
                    category="capitalization_basis_inference",
                    paper_value="generic_market_cap_basis_not_specified",
                    resolved_value=basis,
                    reason=(
                        "The paper evidence does not resolve a capitalization basis; the selected "
                        "runtime field therefore introduces a separate basis inference."
                    ),
                    severity="material",
                    affected_metrics=list(result.affected_metrics) or ["*"],
                    truth_matching_policy="proxy_or_diagnostic_only",
                    source="semantic_field_resolution",
                )
            )
        lineage = derived_fields.get(physical_field, {})
        derivation_method = str(
            lineage.get("method")
            or (lineage.get("derivation", {}) or {}).get("method")
            or ""
        ).lower()
        if lowered.startswith("log_") or derivation_method in {"log", "ln", "natural_log"}:
            deviations.append(
                structured_deviation(
                    category="capitalization_transform_inference",
                    paper_value="untransformed_generic_market_cap",
                    resolved_value="natural_log_market_cap",
                    reason=(
                        "The paper evidence does not resolve a log transform; the selected runtime "
                        "field therefore introduces a separate transform inference."
                    ),
                    severity="material",
                    affected_metrics=list(result.affected_metrics) or ["*"],
                    truth_matching_policy="proxy_or_diagnostic_only",
                    source="semantic_field_resolution",
                )
            )
    return deviations


def _deduplicate_deviations(deviations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for deviation in deviations:
        key = (
            str(deviation.get("category", "")),
            str(deviation.get("paper_value", "")),
            str(deviation.get("resolved_value", "")),
            str(deviation.get("reason", "")),
        )
        if key not in seen:
            seen.add(key)
            result.append(deviation)
    return result


def _case_is_executable(results: list[EvaluationRequirementResult]) -> bool:
    for result in results:
        if result.relationship == "unsupported_substitute" and result.candidate_field:
            return False
        if result.category in {"evaluator_capability", "operation_capability"} and not result.execution_ready:
            return False
        if result.category in {"evaluation", "return"} and not result.execution_ready:
            return False
    return True


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


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
    return_horizon_unit = str(evaluation_spec.get("return_horizon_unit") or "").lower()
    supported_horizon_units = set(capabilities.get("return_horizon_units", []) or [])
    if return_horizon_unit and return_horizon_unit not in supported_horizon_units:
        unsupported_protocol.append(f"return_horizon_unit={return_horizon_unit}")
    transform_spec = truth_source.get("transform_spec", {}) if isinstance(truth_source.get("transform_spec", {}), dict) else {}
    supported_transform_steps = set(capabilities.get("transform_steps", []) or [])
    for step in transform_spec.get("steps", []) or []:
        if not isinstance(step, dict):
            unsupported_protocol.append("transform_step=invalid")
            continue
        name = str(step.get("name", "") or "").lower()
        method_name = canonical_transform_method(str(step.get("method") or step.get("name") or ""))
        if name == "neutralization":
            method_name = str(step.get("method", "") or "none").lower()
        if method_name and method_name not in supported_transform_steps:
            unsupported_protocol.append(f"transform_step={method_name}")
    neutralization_spec = (
        truth_source.get("neutralization_spec", {})
        if isinstance(truth_source.get("neutralization_spec", {}), dict)
        else {}
    )
    if neutralization_spec:
        neutralization_method = str(neutralization_spec.get("method", "") or "").lower()
        supported_neutralization = set(capabilities.get("neutralization_methods", []) or [])
        if neutralization_method and neutralization_method not in supported_neutralization:
            unsupported_protocol.append(f"neutralization_method={neutralization_method}")
        supported_input_transforms = set(capabilities.get("input_transform_methods", []) or [])
        for method_name in transformed_input_methods(neutralization_spec):
            if method_name not in supported_input_transforms:
                unsupported_protocol.append(f"input_transform={method_name}")
        supported_encodings = set(capabilities.get("control_encodings", []) or [])
        for control in neutralization_spec.get("controls", []) or []:
            if not isinstance(control, dict):
                continue
            encoding = str(control.get("encoding", "continuous") or "continuous").lower()
            if encoding not in supported_encodings:
                unsupported_protocol.append(f"control_encoding={encoding}")
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
        source_contexts=["evaluator_capabilities"],
    )


def _comparability_from_support(
    missing_count: int,
    partial_count: int,
    capability_availability: str,
    *,
    proxy_count: int = 0,
) -> str:
    if capability_availability == "missing":
        return "not_comparable"
    if missing_count or proxy_count:
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
                source_contexts=["truth_source.sample_period"],
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
            source_contexts=["truth_source.sample_period"],
        )
    ]


def _universe_requirement_results(
    truth_source: dict[str, Any],
    profile: dict[str, Any],
    metrics: list[str],
) -> list[EvaluationRequirementResult]:
    universe = str(truth_source.get("universe", "") or "").lower()
    requirements: list[tuple[str, str, str]] = []
    exclusion_declared = any(token in universe for token in ("exclude", "exclusion", "remove", "剔除", "排除", "不含"))
    if exclusion_declared and ("st" in universe or "pt" in universe):
        requirements.append(("st_or_pt_status", "universe_filter", "truth_source.universe"))
    if exclusion_declared and any(token in universe for token in ("suspend", "suspension", "停牌")):
        next_day = any(token in universe for token in ("next-day", "next day", "next trading day", "次日", "下一交易日"))
        requirements.append(
            (
                "next_day_suspension_status" if next_day else "suspension_status",
                "universe_filter",
                "truth_source.universe",
            )
        )
    universe_protocol = (
        truth_source.get("universe_protocol", {})
        if isinstance(truth_source.get("universe_protocol", {}), dict)
        else {}
    )
    for item in universe_protocol.get("filters", []) or []:
        if not isinstance(item, dict):
            continue
        requirement = str(item.get("paper_field") or item.get("field") or "")
        if requirement:
            requirements.append((requirement, "universe_filter", "universe_protocol.filters"))
    results: list[EvaluationRequirementResult] = []
    for requirement, category, source_context in requirements:
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
                source_contexts=[source_context],
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
                source_contexts=["evaluation_spec.regression_weight"],
            )
        )
    return_col = str(evaluation_spec.get("return_col") or "").strip()
    horizon = evaluation_spec.get("return_horizon")
    if not return_col and horizon:
        unit = str(evaluation_spec.get("return_horizon_unit") or "trading_day").strip().lower()
        suffix = "m" if unit == "natural_month" else "d"
        return_col = f"forward_return_{horizon}{suffix}"
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
                source_contexts=["evaluation_spec.return"],
            )
        )
    return results


def _transform_requirement_results(
    truth_source: dict[str, Any],
    profile: dict[str, Any],
    metrics: list[str],
) -> list[EvaluationRequirementResult]:
    transform_spec = truth_source.get("transform_spec", {}) if isinstance(truth_source.get("transform_spec", {}), dict) else {}
    semantic_definitions = {
        str(item.get("semantic_field_id")): dict(item)
        for item in truth_source.get("semantic_requirements", []) or []
        if isinstance(item, dict) and item.get("semantic_field_id")
    }
    results: list[EvaluationRequirementResult] = []
    for step in transform_spec.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        if str(step.get("name", "")).lower() != "neutralization":
            continue
        controls = [str(control) for control in step.get("controls", []) or []]
        for control in controls:
            semantic_definition = semantic_definitions.get(control, {})
            resolved = (
                _resolve_semantic_requirement(semantic_definition, profile)
                if semantic_definition
                else _resolve_requirement(control, profile)
            )
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
                    source_contexts=["transform_spec.neutralization.controls"],
                    semantic_definition=semantic_definition,
                )
            )
    neutralization_spec = (
        truth_source.get("neutralization_spec", {})
        if isinstance(truth_source.get("neutralization_spec", {}), dict)
        else {}
    )
    for control in neutralization_spec.get("controls", []) or []:
        if not isinstance(control, dict):
            continue
        paper_field = str(control.get("paper_field") or control.get("field") or "")
        if not paper_field:
            continue
        semantic_definition = semantic_definitions.get(paper_field, {})
        resolved = (
            _resolve_semantic_requirement(semantic_definition, profile)
            if semantic_definition
            else _resolve_requirement(paper_field, profile)
        )
        results.append(
            EvaluationRequirementResult(
                requirement=paper_field,
                category="transform_control",
                paper_value=paper_field,
                available_value=resolved["available_value"],
                availability=resolved["availability"],
                substitute=resolved["substitute"],
                severity="material" if resolved["availability"] == "missing" else "minor",
                affected_metrics=metrics or ["*"],
                recommended_action=(
                    "transform_and_use_control" if resolved["availability"] != "missing" else "drop_or_defer_transform_control"
                ),
                source_contexts=["neutralization_spec.controls"],
                semantic_definition=semantic_definition,
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
