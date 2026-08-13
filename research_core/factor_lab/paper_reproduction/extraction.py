from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from research_core.factor_lab.paper_reproduction.methodology import (
    validate_neutralization_spec,
    validate_universe_protocol,
)
from research_core.factor_lab.runtime import FactorLabWorkspaceConfig

TruthSourceType = Literal["evaluation_results"]
IC_EXTRACTION_SCHEMA_VERSION = "paper_extraction.ic_analysis.v2"
IC_EVALUATOR_TYPE = "ic_analysis"
FORBIDDEN_EXTRACTION_BINDING_KEYS = {
    "local_column",
    "physical_field",
    "resolved_field",
    "selected_truth_source_ids",
}
STANDARD_FORMULA_FIELDS = {
    "open",
    "high",
    "low",
    "close",
    "vwap",
    "volume",
    "amount",
    "returns",
}


@dataclass(slots=True)
class ExtractedTruthSource:
    """Evaluation-result evidence copied from the paper itself."""

    truth_id: str
    truth_type: TruthSourceType = "evaluation_results"
    description: str = ""
    source_location: str = ""
    sample_period: str = ""
    universe: str = ""
    frequency: str = ""
    evaluation_method: str = ""
    evaluation_family: str = ""
    evaluation_spec: dict[str, Any] = field(default_factory=dict)
    transform_spec: dict[str, Any] = field(default_factory=dict)
    neutralization_spec: dict[str, Any] = field(default_factory=dict)
    universe_protocol: dict[str, Any] = field(default_factory=dict)
    required_data: dict[str, list[str]] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExtractedFactor:
    factor_name: str
    formula: str
    required_fields: list[str]
    frequency: str = ""
    description: str = ""
    sample_period: str = ""
    universe: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    truth_sources: list[ExtractedTruthSource] = field(default_factory=list)
    selected_truth_source_ids: list[str] = field(default_factory=list)
    truth_selection_rule: str = ""
    ambiguous_or_missing_information: list[str] = field(default_factory=list)
    known_limitations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PaperExtraction:
    paper_id: str
    title: str
    authors: list[str]
    source: str
    year: int | None
    factor_family_name: str
    target_factors: list[ExtractedFactor]
    extraction_scope: str = "selected_factors"
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExtractedFactorDefinition:
    """One immutable paper formula, independent of evaluation preprocessing."""

    factor_id: str
    paper_label: str
    formula: str
    required_semantic_fields: list[str]
    native_frequency: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    direction: str = ""
    description: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    formula_gap_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExtractedSemanticRequirement:
    """Paper meaning for a field; never a local physical-data selection."""

    semantic_field_id: str
    kind: str
    concept: str
    attributes: dict[str, Any] = field(default_factory=dict)
    evidence: Any = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedUniverseProtocol:
    """Separate factor history from staged evaluation eligibility."""

    universe_protocol_id: str
    calculation_universe: dict[str, Any]
    evaluation_universe: dict[str, Any]
    filters: list[dict[str, Any]] = field(default_factory=list)
    evidence: Any = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedOperationPipeline:
    operation_pipeline_id: str
    paper_label: str
    operations: list[dict[str, Any]] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    evidence: Any = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedICProtocol:
    protocol_id: str
    sample_period_id: str
    operation_pipeline_id: str
    forward_horizon_trading_days: int
    universe_protocol_id: str = ""
    evaluator_contract_id: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedMetricDefinition:
    metric_id: str
    paper_label: str
    definition: str
    stored_unit: str
    attributes: dict[str, Any] = field(default_factory=dict)
    evidence: Any = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedICTruthSource:
    """One narrow paper result block under exactly one semantic IC protocol."""

    truth_source_id: str
    protocol_id: str
    source: dict[str, Any]
    reported_metric_ids: list[str]
    reported_results: dict[str, dict[str, Any]]
    conflict_group_id: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ICAnalysisPaperExtraction:
    """Canonical Stage-1 artifact for the IC-analysis-only workflow.

    Generic evaluator rules, semantic inputs, operation pipelines, protocols,
    and result blocks are paper-level registries.  Factor rows refer to these
    registries instead of duplicating the same protocol for every factor.
    """

    artifact_id: str
    paper: dict[str, Any]
    factor_family_name: str
    factor_definitions: list[ExtractedFactorDefinition]
    semantic_requirements: list[ExtractedSemanticRequirement]
    universe_protocols: list[ExtractedUniverseProtocol]
    sample_periods: list[dict[str, Any]]
    operation_pipelines: list[ExtractedOperationPipeline]
    metric_definitions: list[ExtractedMetricDefinition]
    ic_analysis_contract: dict[str, Any]
    ic_protocols: list[ExtractedICProtocol]
    truth_sources: list[ExtractedICTruthSource]
    truth_selection_policy: dict[str, Any]
    schema_version: str = IC_EXTRACTION_SCHEMA_VERSION
    artifact_role: str = "immutable_paper_evidence"
    created_on: str = ""
    scope: dict[str, Any] = field(default_factory=dict)
    operator_semantics: list[dict[str, Any]] = field(default_factory=list)
    paper_evidence_conflicts: list[dict[str, Any]] = field(default_factory=list)
    known_gaps: list[dict[str, Any]] = field(default_factory=list)
    stage_contract: dict[str, Any] = field(default_factory=dict)
    evidence_conventions: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExtractionValidationResult:
    valid: bool
    status: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def validate_paper_extraction(
    extraction: PaperExtraction | ICAnalysisPaperExtraction,
) -> ExtractionValidationResult:
    if isinstance(extraction, ICAnalysisPaperExtraction):
        return _validate_ic_analysis_extraction(extraction)
    errors: list[str] = []
    warnings: list[str] = []
    ambiguities_by_category: dict[str, list[str]] = {
        "formula": [],
        "field_mapping": [],
        "evaluation": [],
        "other": [],
    }
    known_limitations: list[str] = []

    _require_text(extraction.paper_id, "paper_id", errors)
    _require_text(extraction.title, "title", errors)
    _require_text(extraction.factor_family_name, "factor_family_name", errors)
    if not extraction.authors:
        errors.append("authors must not be empty")
    if not extraction.target_factors:
        errors.append("target_factors must not be empty")

    needs_human_review = False
    seen_names: set[str] = set()
    for index, factor in enumerate(extraction.target_factors):
        factor_needs_review = _validate_factor(
            factor,
            index,
            seen_names,
            errors,
            warnings,
            ambiguities_by_category,
            known_limitations,
        )
        needs_human_review = needs_human_review or factor_needs_review

    if errors:
        status = "needs_human_review"
    elif needs_human_review:
        status = "needs_human_review"
    else:
        status = "implemented"
    return ExtractionValidationResult(
        valid=not errors,
        status=status,
        errors=errors,
        warnings=warnings,
        diagnostics={"ambiguities_by_category": ambiguities_by_category, "known_limitations": known_limitations},
    )


def export_paper_extraction(
    extraction: PaperExtraction | ICAnalysisPaperExtraction,
    *,
    config: FactorLabWorkspaceConfig | None = None,
) -> Path:
    workspace = config or FactorLabWorkspaceConfig()
    workspace.ensure_directories()
    output_dir = workspace.runtime_root / "paper_specs"
    output_dir.mkdir(parents=True, exist_ok=True)
    paper_id = extraction.paper_id if isinstance(extraction, PaperExtraction) else _v2_paper_id(extraction)
    path = output_dir / f"{paper_id}_extracted.json"
    path.write_text(json.dumps(asdict(extraction), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_paper_extraction(path: str | Path) -> PaperExtraction | ICAnalysisPaperExtraction:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if str(payload.get("schema_version", "")) == IC_EXTRACTION_SCHEMA_VERSION:
        return _ic_analysis_extraction_from_payload(payload)
    factors = [_factor_from_payload(item) for item in payload.pop("target_factors")]
    return PaperExtraction(target_factors=factors, **payload)


def selected_truth_sources(factor: ExtractedFactor) -> list[ExtractedTruthSource]:
    """Return explicitly selected evaluation truth sources, or all sources when no selection exists."""

    if not factor.selected_truth_source_ids:
        return list(factor.truth_sources)
    selected_ids = set(factor.selected_truth_source_ids)
    return [truth for truth in factor.truth_sources if truth.truth_id in selected_ids]


def summarize_factor_truth_sources(factor: ExtractedFactor) -> dict[str, object]:
    """Summarize paper-reported evaluation truth coverage for extraction artifacts and specs."""

    selected = selected_truth_sources(factor)
    return {
        "available_truth_count": len(factor.truth_sources),
        "available_truth_ids": [truth.truth_id for truth in factor.truth_sources],
        "available_truth_types": sorted({truth.truth_type for truth in factor.truth_sources}),
        "selected_truth_ids": [truth.truth_id for truth in selected],
        "selected_truth_types": sorted({truth.truth_type for truth in selected}),
        "has_evaluation_truth": any(truth.truth_type == "evaluation_results" for truth in selected),
    }


def _factor_from_payload(payload: dict[str, Any]) -> ExtractedFactor:
    truth_payloads = payload.pop("truth_sources", [])
    truth_sources = [ExtractedTruthSource(**item) for item in truth_payloads]
    # Backward-compatibility for older extraction artifacts produced before
    # evaluation-case-level transform specs. These fields are no longer factor
    # properties; evaluation/preprocessing/neutralization belong on truth sources.
    for legacy_key in (
        "preprocessing_required_fields",
        "neutralization_required_fields",
        "evaluation_required_fields",
        "preprocessing_rules",
        "neutralization_rules",
        "evaluation_method",
        "portfolio_construction_rules",
    ):
        payload.pop(legacy_key, None)
    return ExtractedFactor(truth_sources=truth_sources, **payload)


def _validate_factor(
    factor: ExtractedFactor,
    index: int,
    seen_names: set[str],
    errors: list[str],
    warnings: list[str],
    ambiguities_by_category: dict[str, list[str]],
    known_limitations: list[str],
) -> bool:
    prefix = f"target_factors[{index}]"
    needs_human_review = False

    if not factor.factor_name.strip():
        errors.append(f"{prefix}.factor_name is required")
    elif factor.factor_name in seen_names:
        errors.append(f"{prefix}.factor_name is duplicated: {factor.factor_name}")
    seen_names.add(factor.factor_name)

    if not factor.formula.strip():
        errors.append(f"{prefix}.formula is required")
    if not factor.required_fields:
        errors.append(f"{prefix}.required_fields must not be empty")
    else:
        formula_tokens = {token.lower() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", factor.formula)}
        unrelated_standard_fields = sorted(
            field
            for field in factor.required_fields
            if field.lower() in STANDARD_FORMULA_FIELDS and field.lower() not in formula_tokens
        )
        if unrelated_standard_fields:
            needs_human_review = True
            warnings.append(
                f"{prefix}.required_fields contains standard raw fields absent from the formula: "
                f"{unrelated_standard_fields}; keep formula requirements factor-specific"
            )
    if not factor.frequency.strip() and not _mentions_frequency_gap(factor.ambiguous_or_missing_information):
        errors.append(f"{prefix}.frequency is missing and must be recorded in factor ambiguous_or_missing_information")

    if factor.ambiguous_or_missing_information:
        needs_human_review = True
        for item in factor.ambiguous_or_missing_information:
            warnings.append(f"{prefix}.ambiguity: {item}")
            category = _classify_ambiguity(item)
            ambiguities_by_category[category].append(f"{prefix}: {item}")

    for item in factor.known_limitations:
        known_limitations.append(f"{prefix}: {item}")

    if not factor.truth_sources:
        needs_human_review = True
        warnings.append(f"{prefix}.truth_sources is missing; paper evaluation results are required")
        return needs_human_review

    truth_ids = [truth.truth_id for truth in factor.truth_sources]
    duplicate_truth_ids = sorted({truth_id for truth_id in truth_ids if truth_ids.count(truth_id) > 1})
    for truth_id in duplicate_truth_ids:
        errors.append(f"{prefix}.truth_sources contains duplicated truth_id: {truth_id}")

    for truth_index, truth_source in enumerate(factor.truth_sources):
        truth_prefix = f"{prefix}.truth_sources[{truth_index}]"
        truth_needs_review = _validate_truth_source(truth_source, truth_prefix, factor, errors, warnings)
        needs_human_review = needs_human_review or truth_needs_review

    known_truth_ids = set(truth_ids)
    duplicate_selected_ids = sorted(
        {truth_id for truth_id in factor.selected_truth_source_ids if factor.selected_truth_source_ids.count(truth_id) > 1}
    )
    for truth_id in duplicate_selected_ids:
        errors.append(f"{prefix}.selected_truth_source_ids contains duplicated truth_id: {truth_id}")

    for selected_id in factor.selected_truth_source_ids:
        if selected_id not in known_truth_ids:
            errors.append(f"{prefix}.selected_truth_source_ids contains unknown truth_id: {selected_id}")

    has_alternative_truth_sources = len(factor.truth_sources) > 1
    if has_alternative_truth_sources and not (factor.truth_selection_rule.strip() or factor.selected_truth_source_ids):
        needs_human_review = True
        warnings.append(f"{prefix}.truth_sources has multiple entries but no truth_selection_rule")

    return needs_human_review


def _validate_truth_source(
    truth_source: ExtractedTruthSource,
    prefix: str,
    factor: ExtractedFactor,
    errors: list[str],
    warnings: list[str],
) -> bool:
    needs_human_review = False
    _require_text(truth_source.truth_id, f"{prefix}.truth_id", errors)
    if not truth_source.source_location.strip():
        needs_human_review = True
        warnings.append(f"{prefix}.source_location is missing")
    elif _looks_like_broad_source_location(truth_source.source_location):
        needs_human_review = True
        warnings.append(
            f"{prefix}.source_location appears to reference multiple tables/figures; split truth sources by metric group and evaluation setting"
        )

    if truth_source.truth_type != "evaluation_results":
        errors.append(f"{prefix}.truth_type must be 'evaluation_results'")
        return needs_human_review

    if not truth_source.metrics:
        errors.append(f"{prefix}.metrics must not be empty for evaluation_results truth")
    elif not _has_recognized_evaluation_metric(truth_source.metrics):
        needs_human_review = True
        warnings.append(f"{prefix}.metrics has no recognized evaluation metric names")
    if not truth_source.evaluation_method.strip():
        errors.append(f"{prefix}.evaluation_method is required for evaluation_results truth")
    neutralization_validation = validate_neutralization_spec(
        truth_source.neutralization_spec,
        prefix=f"{prefix}.neutralization_spec",
    )
    errors.extend(neutralization_validation.errors)
    warnings.extend(neutralization_validation.warnings)
    universe_validation = validate_universe_protocol(
        truth_source.universe_protocol,
        prefix=f"{prefix}.universe_protocol",
    )
    errors.extend(universe_validation.errors)
    warnings.extend(universe_validation.warnings)
    return needs_human_review


def _has_recognized_evaluation_metric(metrics: dict[str, Any]) -> bool:
    recognized_tokens = ("rank_ic", "long_short", "t_stat", "tstat", "ic", "ir", "return", "sharpe", "half_life")
    return any(_contains_token(str(metric_name).lower(), token) for metric_name in metrics for token in recognized_tokens)


def _classify_ambiguity(item: str) -> str:
    text = item.lower()
    if "vwap" in text and any(
        _contains_token(text, token) for token in ("backtest", "rebalance", "execution", "portfolio", "layer", "layered")
    ):
        return "evaluation"
    if any(_contains_token(text, token) for token in ("evaluation", "ic", "ir", "portfolio", "return", "long-short", "metric")):
        return "evaluation"
    if any(_contains_token(text, token) for token in ("field", "mapping", "column", "volume", "price", "adjust", "vwap")):
        return "field_mapping"
    if any(_contains_token(text, token) for token in ("formula", "rank", "window", "operator", "expression")):
        return "formula"
    return "other"


def _looks_like_broad_source_location(source_location: str) -> bool:
    text = source_location.lower()
    table_mentions = text.count("table") + text.count("figure") + text.count("图表")
    has_separator = any(separator in text for separator in (";", "；", ",", "，", "/"))
    return table_mentions > 1 or (table_mentions >= 1 and has_separator)


def _contains_token(text: str, token: str) -> bool:
    normalized_text = text.replace("-", "_")
    normalized_token = token.replace("-", "_")
    parts = [part for part in normalized_text.replace("/", "_").replace(".", "_").replace(" ", "_").split("_") if part]
    if "_" in normalized_token:
        return normalized_token in normalized_text
    return normalized_token in parts


def _require_text(value: str, field_name: str, errors: list[str]) -> None:
    if not value.strip():
        errors.append(f"{field_name} is required")


def _mentions_frequency_gap(items: list[str]) -> bool:
    return "frequency" in "\n".join(items).lower()


def _validate_ic_analysis_extraction(extraction: ICAnalysisPaperExtraction) -> ExtractionValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    _require_text(extraction.artifact_id, "artifact_id", errors)
    _require_text(extraction.factor_family_name, "factor_family_name", errors)
    if extraction.schema_version != IC_EXTRACTION_SCHEMA_VERSION:
        errors.append(f"schema_version must be {IC_EXTRACTION_SCHEMA_VERSION!r}")
    if extraction.artifact_role != "immutable_paper_evidence":
        errors.append("artifact_role must be 'immutable_paper_evidence'")

    paper_id = _v2_paper_id(extraction)
    _require_text(paper_id, "paper.paper_id", errors)
    _require_text(str(extraction.paper.get("title", "")), "paper.title", errors)
    authors = extraction.paper.get("authors", []) or []
    if not isinstance(authors, list) or not authors:
        errors.append("paper.authors must not be empty")

    evaluator_types = extraction.scope.get("supported_evaluator_types", []) or []
    if evaluator_types != [IC_EVALUATOR_TYPE]:
        errors.append("scope.supported_evaluator_types must contain only 'ic_analysis'")
    if str(extraction.ic_analysis_contract.get("evaluator_type", "")) != IC_EVALUATOR_TYPE:
        errors.append("ic_analysis_contract.evaluator_type must be 'ic_analysis'")

    factor_ids = _unique_registry_ids(
        extraction.factor_definitions,
        "factor_id",
        "factor_definitions",
        errors,
    )
    semantic_ids = _unique_registry_ids(
        extraction.semantic_requirements,
        "semantic_field_id",
        "semantic_requirements",
        errors,
    )
    universe_ids = _unique_registry_ids(
        extraction.universe_protocols,
        "universe_protocol_id",
        "universe_protocols",
        errors,
    )
    pipeline_ids = _unique_registry_ids(
        extraction.operation_pipelines,
        "operation_pipeline_id",
        "operation_pipelines",
        errors,
    )
    metric_ids = _unique_registry_ids(
        extraction.metric_definitions,
        "metric_id",
        "metric_definitions",
        errors,
    )
    protocol_ids = _unique_registry_ids(extraction.ic_protocols, "protocol_id", "ic_protocols", errors)
    truth_ids = _unique_registry_ids(extraction.truth_sources, "truth_source_id", "truth_sources", errors)

    if not factor_ids:
        errors.append("factor_definitions must not be empty")
    if not extraction.truth_sources:
        errors.append("truth_sources must not be empty")
    declared_scope_ids = set(str(item) for item in extraction.scope.get("factor_ids", []) or [])
    if declared_scope_ids and declared_scope_ids != factor_ids:
        errors.append("scope.factor_ids must exactly match factor_definitions")

    for index, factor in enumerate(extraction.factor_definitions):
        prefix = f"factor_definitions[{index}]"
        _require_text(factor.formula, f"{prefix}.formula", errors)
        _require_text(factor.native_frequency, f"{prefix}.native_frequency", errors)
        if not factor.required_semantic_fields:
            errors.append(f"{prefix}.required_semantic_fields must not be empty")
        unknown = sorted(set(factor.required_semantic_fields) - semantic_ids)
        if unknown:
            errors.append(f"{prefix}.required_semantic_fields contains unknown ids: {unknown}")

    sample_ids = _unique_mapping_ids(extraction.sample_periods, "sample_period_id", "sample_periods", errors)
    for index, protocol in enumerate(extraction.ic_protocols):
        prefix = f"ic_protocols[{index}]"
        if protocol.sample_period_id not in sample_ids:
            errors.append(f"{prefix}.sample_period_id is unknown: {protocol.sample_period_id}")
        if protocol.operation_pipeline_id not in pipeline_ids:
            errors.append(f"{prefix}.operation_pipeline_id is unknown: {protocol.operation_pipeline_id}")
        if protocol.universe_protocol_id and protocol.universe_protocol_id not in universe_ids:
            errors.append(f"{prefix}.universe_protocol_id is unknown: {protocol.universe_protocol_id}")
        if protocol.forward_horizon_trading_days <= 0:
            errors.append(f"{prefix}.forward_horizon_trading_days must be positive")

    for index, pipeline in enumerate(extraction.operation_pipelines):
        operations = pipeline.operations
        if not operations:
            warnings.append(f"operation_pipelines[{index}].operations is empty")
            continue
        orders = [item.get("order") for item in operations if isinstance(item, dict)]
        if orders != list(range(1, len(operations) + 1)):
            errors.append(f"operation_pipelines[{index}].operations must have contiguous one-based order")

    for index, universe in enumerate(extraction.universe_protocols):
        payload = {
            "calculation_universe": universe.calculation_universe,
            "evaluation_universe": universe.evaluation_universe,
            "filters": universe.filters,
        }
        result = validate_universe_protocol(payload, prefix=f"universe_protocols[{index}]")
        errors.extend(result.errors)
        warnings.extend(result.warnings)
        calculation_filter_names = {
            str(item.get("filter_name", ""))
            for item in universe.filters
            if isinstance(item, dict)
            and str(item.get("application_stage", "")) in {"raw_data", "factor_time_series"}
        }
        retained = bool(universe.calculation_universe.get("retain_full_valid_security_history", False))
        if retained and calculation_filter_names:
            errors.append(
                f"universe_protocols[{index}] declares full calculation history but also calculation-stage filters: "
                f"{sorted(calculation_filter_names)}"
            )

    factors_with_truth: set[str] = set()
    for index, truth in enumerate(extraction.truth_sources):
        prefix = f"truth_sources[{index}]"
        if truth.protocol_id not in protocol_ids:
            errors.append(f"{prefix}.protocol_id is unknown: {truth.protocol_id}")
        if not truth.source:
            warnings.append(f"{prefix}.source is missing")
        if not truth.reported_metric_ids:
            errors.append(f"{prefix}.reported_metric_ids must not be empty")
        unknown_metrics = sorted(set(truth.reported_metric_ids) - metric_ids)
        if unknown_metrics:
            errors.append(f"{prefix}.reported_metric_ids contains unknown ids: {unknown_metrics}")
        for factor_id, results in truth.reported_results.items():
            if factor_id not in factor_ids:
                errors.append(f"{prefix}.reported_results contains unknown factor: {factor_id}")
                continue
            factors_with_truth.add(factor_id)
            if set(results) != set(truth.reported_metric_ids):
                errors.append(
                    f"{prefix}.reported_results[{factor_id!r}] metric ids must exactly match reported_metric_ids"
                )
    missing_truth = sorted(factor_ids - factors_with_truth)
    if missing_truth:
        errors.append(f"factors have no reported IC truth: {missing_truth}")

    conflict_ids = {
        str(item.get("conflict_group_id", ""))
        for item in extraction.paper_evidence_conflicts
        if isinstance(item, dict) and item.get("conflict_group_id")
    }
    for index, truth in enumerate(extraction.truth_sources):
        if truth.conflict_group_id and truth.conflict_group_id not in conflict_ids:
            errors.append(
                f"truth_sources[{index}].conflict_group_id is unknown: {truth.conflict_group_id}"
            )
    for index, conflict in enumerate(extraction.paper_evidence_conflicts):
        referenced = set(str(item) for item in conflict.get("truth_source_ids", []) or [])
        unknown = sorted(referenced - truth_ids)
        if unknown:
            errors.append(f"paper_evidence_conflicts[{index}] contains unknown truth_source_ids: {unknown}")
        if str(conflict.get("resolution_status", "")) == "unresolved_paper_internal_conflict":
            warnings.append(
                f"paper_evidence_conflicts[{index}] is unresolved; affected truth sources are not exact-match eligible"
            )

    support_stage = extraction.truth_selection_policy.get("support_assessment_stage")
    if support_stage not in {3, "stage_3", "data_readiness"}:
        errors.append("truth_selection_policy.support_assessment_stage must be Stage 3")
    selection_stage = extraction.truth_selection_policy.get("selection_stage")
    if selection_stage not in {6, "stage_6", "evaluation_planning"}:
        errors.append("truth_selection_policy.selection_stage must be Stage 6 evaluation planning")
    forbidden_selection = " ".join(
        str(item).lower() for item in extraction.truth_selection_policy.get("forbidden_selection_evidence", []) or []
    )
    if not any(token in forbidden_selection for token in ("closeness", "reproduced ic", "reported metric")):
        errors.append("truth_selection_policy must forbid selection by reproduced metric closeness")

    binding_hits: list[str] = []
    _find_forbidden_binding_keys(asdict(extraction), path="$", hits=binding_hits)
    errors.extend(binding_hits)
    status = "needs_human_review" if errors or warnings else "implemented"
    return ExtractionValidationResult(
        valid=not errors,
        status=status,
        errors=errors,
        warnings=warnings,
        diagnostics={
            "schema_version": extraction.schema_version,
            "factor_count": len(factor_ids),
            "protocol_count": len(protocol_ids),
            "truth_source_count": len(truth_ids),
            "result_row_count": sum(len(source.reported_results) for source in extraction.truth_sources),
            "unresolved_conflict_count": sum(
                1
                for item in extraction.paper_evidence_conflicts
                if item.get("resolution_status") == "unresolved_paper_internal_conflict"
            ),
        },
    )


def _v2_paper_id(extraction: ICAnalysisPaperExtraction) -> str:
    return str(extraction.paper.get("paper_id") or extraction.artifact_id).strip()


def _unique_registry_ids(
    values: list[Any],
    attribute: str,
    label: str,
    errors: list[str],
) -> set[str]:
    ids = [str(getattr(item, attribute, "")).strip() for item in values]
    for index, value in enumerate(ids):
        if not value:
            errors.append(f"{label}[{index}].{attribute} is required")
    duplicates = sorted({value for value in ids if value and ids.count(value) > 1})
    for value in duplicates:
        errors.append(f"{label} contains duplicated {attribute}: {value}")
    return {value for value in ids if value}


def _unique_mapping_ids(
    values: list[dict[str, Any]],
    key: str,
    label: str,
    errors: list[str],
) -> set[str]:
    ids = [str(item.get(key, "")).strip() for item in values if isinstance(item, dict)]
    if len(ids) != len(values):
        errors.append(f"{label} entries must be objects")
    for index, value in enumerate(ids):
        if not value:
            errors.append(f"{label}[{index}].{key} is required")
    duplicates = sorted({value for value in ids if value and ids.count(value) > 1})
    for value in duplicates:
        errors.append(f"{label} contains duplicated {key}: {value}")
    return {value for value in ids if value}


def _find_forbidden_binding_keys(value: Any, *, path: str, hits: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_EXTRACTION_BINDING_KEYS:
                hits.append(f"{path}.{key} is a Stage-3/runtime binding and is forbidden in extraction")
            _find_forbidden_binding_keys(child, path=f"{path}.{key}", hits=hits)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _find_forbidden_binding_keys(child, path=f"{path}[{index}]", hits=hits)


def _ic_analysis_extraction_from_payload(payload: dict[str, Any]) -> ICAnalysisPaperExtraction:
    raw = dict(payload)
    factors = [ExtractedFactorDefinition(**item) for item in raw.pop("factor_definitions", [])]
    semantics = [_semantic_requirement_from_payload(item) for item in raw.pop("semantic_requirements", [])]
    universes = [_universe_protocol_from_payload(item) for item in raw.pop("universe_protocols", [])]
    pipelines = [_operation_pipeline_from_payload(item) for item in raw.pop("operation_pipelines", [])]
    metrics = [_metric_definition_from_payload(item) for item in raw.pop("metric_definitions", [])]
    protocols = [_ic_protocol_from_payload(item) for item in raw.pop("ic_protocols", [])]
    truth_sources = [ExtractedICTruthSource(**item) for item in raw.pop("truth_sources", [])]
    allowed = {field_.name for field_ in ICAnalysisPaperExtraction.__dataclass_fields__.values()}
    constructor = {key: value for key, value in raw.items() if key in allowed}
    ignored = {key: value for key, value in raw.items() if key not in allowed}
    notes = list(constructor.get("notes", []) or [])
    if ignored:
        notes.append(f"Unmodeled top-level extraction fields preserved by source JSON only: {sorted(ignored)}")
    constructor["notes"] = notes
    return ICAnalysisPaperExtraction(
        factor_definitions=factors,
        semantic_requirements=semantics,
        universe_protocols=universes,
        operation_pipelines=pipelines,
        metric_definitions=metrics,
        ic_protocols=protocols,
        truth_sources=truth_sources,
        **constructor,
    )


def _semantic_requirement_from_payload(payload: dict[str, Any]) -> ExtractedSemanticRequirement:
    raw = dict(payload)
    core = {key: raw.pop(key) for key in ("semantic_field_id", "kind", "concept")}
    evidence = raw.pop("evidence", {})
    attributes = _extensible_attributes_from_payload(raw)
    return ExtractedSemanticRequirement(**core, attributes=attributes, evidence=evidence)


def _universe_protocol_from_payload(payload: dict[str, Any]) -> ExtractedUniverseProtocol:
    raw = dict(payload)
    protocol_id = str(raw.pop("universe_protocol_id"))
    calculation = raw.pop("calculation_universe", None)
    evaluation = raw.pop("evaluation_universe", None)
    base_universe = raw.pop("base_universe", "")
    if not isinstance(calculation, dict):
        calculation = {
            "base_universe": base_universe,
            "retain_full_valid_security_history": True,
            "source": "inferred",
        }
    if not isinstance(evaluation, dict):
        evaluation = {"base_universe": base_universe, "source": "explicit"}
    filters = list(raw.pop("filters", []) or [])
    evidence = raw.pop("evidence", {})
    return ExtractedUniverseProtocol(
        universe_protocol_id=protocol_id,
        calculation_universe=calculation,
        evaluation_universe=evaluation,
        filters=filters,
        evidence=evidence,
    )


def _operation_pipeline_from_payload(payload: dict[str, Any]) -> ExtractedOperationPipeline:
    raw = dict(payload)
    pipeline_id = str(raw.pop("operation_pipeline_id"))
    label = str(raw.pop("paper_label", ""))
    operations = list(raw.pop("operations", []) or [])
    evidence = raw.pop("evidence", {})
    attributes = _extensible_attributes_from_payload(raw)
    return ExtractedOperationPipeline(pipeline_id, label, operations, attributes, evidence)


def _metric_definition_from_payload(payload: dict[str, Any]) -> ExtractedMetricDefinition:
    raw = dict(payload)
    core = {key: raw.pop(key) for key in ("metric_id", "paper_label", "definition", "stored_unit")}
    evidence = raw.pop("evidence", {})
    attributes = _extensible_attributes_from_payload(raw)
    return ExtractedMetricDefinition(**core, attributes=attributes, evidence=evidence)


def _ic_protocol_from_payload(payload: dict[str, Any]) -> ExtractedICProtocol:
    raw = dict(payload)
    core_keys = (
        "protocol_id",
        "sample_period_id",
        "operation_pipeline_id",
        "forward_horizon_trading_days",
    )
    core = {key: raw.pop(key) for key in core_keys}
    universe_protocol_id = str(raw.pop("universe_protocol_id", ""))
    evaluator_contract_id = str(raw.pop("evaluator_contract_id", ""))
    attributes = _extensible_attributes_from_payload(raw)
    return ExtractedICProtocol(
        **core,
        universe_protocol_id=universe_protocol_id,
        evaluator_contract_id=evaluator_contract_id,
        attributes=attributes,
    )


def _extensible_attributes_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Load canonical nested attributes while accepting legacy flat extensions."""

    nested = payload.pop("attributes", {})
    attributes = dict(nested) if isinstance(nested, dict) else {}
    attributes.update(payload)
    return attributes
