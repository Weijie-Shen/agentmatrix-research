from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from pprint import pformat
from typing import Any

from contracts.factor_research import FactorResearchSpec, ValidationThreshold
from research_core.factor_lab.paper_reproduction.extraction import (
    ICAnalysisPaperExtraction,
    PaperExtraction,
    ExtractedFactorDefinition,
    ExtractedOperationPipeline,
    ExtractedSemanticRequirement,
    ExtractedUniverseProtocol,
    ExtractedICProtocol,
    ExtractedICTruthSource,
    selected_truth_sources,
    summarize_factor_truth_sources,
    validate_paper_extraction,
)

PAPER_REPRODUCTION_BASE_THRESHOLDS = [
    ValidationThreshold("formula_match_ratio", ">=", 1.0, "Implementation formula must match the extracted paper formula."),
    ValidationThreshold("field_mapping_match_ratio", ">=", 1.0, "Required input fields must match the extracted data requirements."),
]

PAPER_EVALUATION_THRESHOLD = ValidationThreshold(
    "paper_evaluation_metric_match_ratio",
    ">=",
    1.0,
    "Computed evaluation metrics must match evaluation results reported in the paper.",
)

COMMON_TRANSFORM_DEFAULTS: dict[str, dict[str, Any]] = {
    "winsorization": {
        "name": "winsorization",
        "method": "median_mad",
        "threshold": 5,
        "scope": "cross_section_by_date",
        "source": "default_assumed",
        "default_reason": "paper omitted a common transform detail; applied paper-reproduction default",
    },
    "standardization": {
        "name": "standardization",
        "method": "cross_section_zscore",
        "scope": "cross_section_by_date",
        "source": "default_assumed",
        "default_reason": "paper omitted a common transform detail; applied paper-reproduction default",
    },
    "missing_value_policy": {
        "name": "missing_value_policy",
        "method": "do_not_fill",
        "source": "default_assumed",
        "default_reason": "paper omitted a common transform detail; applied paper-reproduction default",
    },
}
COMMON_TRANSFORM_ORDER = ("winsorization", "standardization", "missing_value_policy")


def normalize_extraction_to_specs(
    extraction: PaperExtraction | ICAnalysisPaperExtraction,
    *,
    version: str = "v0.1",
) -> list[FactorResearchSpec]:
    if isinstance(extraction, ICAnalysisPaperExtraction):
        return _normalize_ic_analysis_extraction_to_specs(extraction, version=version)
    validation = validate_paper_extraction(extraction)
    if not validation.valid:
        raise ValueError(f"Invalid paper extraction: {validation.errors}")

    source_document = _source_document(extraction)
    ambiguities_by_category = validation.diagnostics.get("ambiguities_by_category", {})
    specs: list[FactorResearchSpec] = []
    for factor_index, factor in enumerate(extraction.target_factors):
        notes = [*factor.notes]
        if factor.ambiguous_or_missing_information:
            notes.extend(f"Ambiguity/missing info: {item}" for item in factor.ambiguous_or_missing_information)
        selected_truth = selected_truth_sources(factor)
        selected_truth_payloads = [_truth_source_payload(truth) for truth in selected_truth]
        truth_source_payloads = [_truth_source_payload(truth) for truth in factor.truth_sources]
        defaulted_transform_steps = _collect_defaulted_transform_steps(selected_truth_payloads)
        truth_summary = summarize_factor_truth_sources(factor)
        factor_ambiguities_by_category = _filter_factor_ambiguities(
            ambiguities_by_category,
            factor_index=factor_index,
        )
        spec_status = "needs_human_review" if _has_any_ambiguity(factor_ambiguities_by_category) or not selected_truth else "planned"
        validation_targets = _validation_targets_for_truth(selected_truth)

        if not selected_truth:
            notes.append("No paper-reported evaluation results were extracted; wait for human review.")
        else:
            notes.append("Paper evaluation-result truth sources extracted for matching.")
        if factor.truth_selection_rule.strip():
            notes.append(f"Truth selection rule: {factor.truth_selection_rule.strip()}")

        tags = [
            _slug(extraction.factor_family_name),
            "paper-reproduction",
            "price-volume",
        ]
        if selected_truth:
            tags.append("paper-evaluation-truth")
        if spec_status == "needs_human_review":
            tags.append("needs_human_review")

        specs.append(
            FactorResearchSpec(
                factor_name=factor.factor_name,
                library=extraction.factor_family_name,
                version=version,
                display_name=factor.factor_name,
                factor_id=f"{_slug(extraction.factor_family_name)}_{factor.factor_name}",
                source_document=source_document,
                formula=factor.formula,
                description=factor.description,
                frequency=factor.frequency,
                sample_scope=_sample_scope(factor),
                required_fields=list(factor.required_fields),
                parameters=dict(factor.parameters),
                preprocessing=[],
                neutralization=[],
                validation_targets=validation_targets,
                tags=tags,
                notes=notes,
                metadata={
                    "paper_id": extraction.paper_id,
                    "authors": list(extraction.authors),
                    "source": extraction.source,
                    "year": extraction.year,
                    "extraction_scope": extraction.extraction_scope,
                    "extraction_validation": {
                        "status": validation.status,
                        "warnings": list(validation.warnings),
                    },
                    "data_requirements": {
                        "formula_required_fields": list(factor.required_fields),
                    },
                    "evaluation_cases": selected_truth_payloads,
                    "defaulted_transform_steps": defaulted_transform_steps,
                    "known_limitations": list(factor.known_limitations),
                    "truth_sources": truth_source_payloads,
                    "selected_truth_sources": selected_truth_payloads,
                    "truth_source_summary": truth_summary,
                    "ambiguities_by_category": ambiguities_by_category,
                    "factor_ambiguities_by_category": factor_ambiguities_by_category,
                    "selected_truth_source_ids": list(factor.selected_truth_source_ids),
                    "truth_selection_rule": factor.truth_selection_rule,
                    "truth_match_required": bool(selected_truth),
                    "proof_status_ceiling": "paper_evaluation_match" if selected_truth else "needs_human_review",
                    "status": spec_status,
                    "implementation_stage": "spec",
                },
            )
        )
    return specs


def default_transform_spec(
    transform_spec: dict[str, Any],
    *,
    paper_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a transform spec with executable defaults for common omitted steps."""

    del paper_context
    payload = dict(transform_spec or {})
    raw_steps = payload.get("steps", [])
    steps = [dict(step) for step in raw_steps if isinstance(step, dict)]
    present: set[str] = set()
    defaulted: list[str] = []
    normalized_steps: list[dict[str, Any]] = []

    for step in steps:
        name = _canonical_transform_name(str(step.get("name", "")))
        if name in COMMON_TRANSFORM_DEFAULTS:
            present.add(name)
            method = str(step.get("method", "")).strip().lower()
            source = str(step.get("source", "")).strip().lower()
            if method == "unknown" and source == "not_specified":
                replacement = _default_transform_step(name)
                replacement["original_method"] = step.get("method")
                replacement["original_source"] = step.get("source")
                normalized_steps.append(replacement)
                defaulted.append(name)
            else:
                normalized_steps.append(step)
        else:
            normalized_steps.append(step)

    for name in COMMON_TRANSFORM_ORDER:
        if name not in present:
            normalized_steps.append(_default_transform_step(name))
            defaulted.append(name)

    payload["steps"] = normalized_steps
    payload["defaulted_transform_steps"] = defaulted
    return payload


def _normalize_ic_analysis_extraction_to_specs(
    extraction: ICAnalysisPaperExtraction,
    *,
    version: str,
) -> list[FactorResearchSpec]:
    """Project shared v2 evidence registries into factor runtime candidates.

    This is a reference-preserving compilation step.  It does not select a
    truth source, resolve a local field, or add a paper assumption.
    """

    validation = validate_paper_extraction(extraction)
    if not validation.valid:
        raise ValueError(f"Invalid IC-analysis paper extraction: {validation.errors}")

    semantic_by_id = {item.semantic_field_id: item for item in extraction.semantic_requirements}
    universe_by_id = {item.universe_protocol_id: item for item in extraction.universe_protocols}
    sample_by_id = {str(item.get("sample_period_id")): item for item in extraction.sample_periods}
    pipeline_by_id = {item.operation_pipeline_id: item for item in extraction.operation_pipelines}
    protocol_by_id = {item.protocol_id: item for item in extraction.ic_protocols}
    metric_by_id = {item.metric_id: item for item in extraction.metric_definitions}
    default_universe_id = str(extraction.ic_analysis_contract.get("universe_protocol_id", ""))
    if not default_universe_id and len(universe_by_id) == 1:
        default_universe_id = next(iter(universe_by_id))
    unresolved_conflicts = {
        str(item.get("conflict_group_id"))
        for item in extraction.paper_evidence_conflicts
        if item.get("resolution_status") == "unresolved_paper_internal_conflict"
    }
    paper_id = str(extraction.paper.get("paper_id") or extraction.artifact_id)
    source_document = _v2_source_document(extraction)
    shared_ref = {
        "schema_version": extraction.schema_version,
        "artifact_id": extraction.artifact_id,
        "paper_id": paper_id,
        "artifact_role": extraction.artifact_role,
    }

    specs: list[FactorResearchSpec] = []
    for factor in extraction.factor_definitions:
        canonical_fields = [
            _canonical_formula_field(semantic_by_id.get(field_id), fallback=field_id)
            for field_id in factor.required_semantic_fields
        ]
        candidate_cases: list[dict[str, Any]] = []
        for truth_source in extraction.truth_sources:
            if factor.factor_id not in truth_source.reported_results:
                continue
            protocol = protocol_by_id[truth_source.protocol_id]
            pipeline = pipeline_by_id[protocol.operation_pipeline_id]
            universe_id = protocol.universe_protocol_id or default_universe_id
            universe = universe_by_id[universe_id]
            sample = sample_by_id[protocol.sample_period_id]
            candidate_cases.append(
                _project_v2_truth_source_for_factor(
                    extraction,
                    factor=factor,
                    truth_source=truth_source,
                    protocol=protocol,
                    pipeline=pipeline,
                    universe=universe,
                    sample_period=sample,
                    semantic_by_id=semantic_by_id,
                    metric_by_id=metric_by_id,
                    unresolved_conflicts=unresolved_conflicts,
                )
            )

        factor_has_unconflicted_truth = any(not case.get("paper_truth_conflict") for case in candidate_cases)
        needs_formula_review = bool(factor.formula_gap_ids)
        status = "needs_human_review" if needs_formula_review or not factor_has_unconflicted_truth else "planned"
        notes = [
            "IC-analysis truth-source support is assessed in Stage 3; final selection is deferred to Stage 6 evaluation planning.",
            "Projected evaluation cases compile shared protocol references for runtime use; the Stage-1 registries remain immutable.",
        ]
        if factor.formula_gap_ids:
            notes.append(f"Formula gaps requiring explicit Stage-2 semantics: {factor.formula_gap_ids}")
        if any(case.get("paper_truth_conflict") for case in candidate_cases):
            notes.append("At least one candidate belongs to an unresolved paper-evidence conflict and is not exact-match eligible.")

        specs.append(
            FactorResearchSpec(
                factor_name=factor.factor_id,
                library=extraction.factor_family_name,
                version=version,
                display_name=factor.paper_label or factor.factor_id,
                factor_id=f"{_slug(extraction.factor_family_name)}_{factor.factor_id}",
                source_document=source_document,
                formula=factor.formula,
                description=factor.description,
                frequency=factor.native_frequency,
                sample_scope="candidate IC protocols; selected after Stage 3 support assessment",
                required_fields=canonical_fields,
                semantic_required_fields=list(factor.required_semantic_fields),
                paper_evidence_ref={
                    **shared_ref,
                    "factor_definition_id": factor.factor_id,
                    "factor_evidence": factor.evidence,
                },
                evaluation_case_refs=[case["truth_source_id"] for case in candidate_cases],
                parameters=dict(factor.parameters),
                preprocessing=[],
                neutralization=[],
                validation_targets=[*PAPER_REPRODUCTION_BASE_THRESHOLDS, PAPER_EVALUATION_THRESHOLD],
                tags=[
                    _slug(extraction.factor_family_name),
                    "paper-reproduction",
                    "price-volume",
                    "ic-analysis-only",
                    "paper-evaluation-truth",
                    *( ["needs_human_review"] if status == "needs_human_review" else [] ),
                ],
                notes=notes,
                metadata={
                    "paper_id": paper_id,
                    "authors": list(extraction.paper.get("authors", []) or []),
                    "source": extraction.paper.get("publisher", ""),
                    "year": _v2_publication_year(extraction),
                    "extraction_scope": extraction.scope,
                    "extraction_schema_version": extraction.schema_version,
                    "extraction_validation": {
                        "status": validation.status,
                        "warnings": list(validation.warnings),
                        "diagnostics": dict(validation.diagnostics),
                    },
                    "paper_evidence_ref": shared_ref,
                    "data_requirements": {
                        "formula_required_fields": canonical_fields,
                        "formula_semantic_field_ids": list(factor.required_semantic_fields),
                    },
                    "evaluation_cases": [],
                    "truth_sources": candidate_cases,
                    "selected_truth_sources": [],
                    "truth_source_summary": {
                        "available_truth_count": len(candidate_cases),
                        "available_truth_ids": [case["truth_source_id"] for case in candidate_cases],
                        "available_truth_types": ["evaluation_results"],
                        "selected_truth_ids": [],
                        "selected_truth_types": [],
                        "support_assessment_stage": 3,
                        "selection_stage": 6,
                        "unresolved_conflict_truth_ids": [
                            case["truth_source_id"] for case in candidate_cases if case.get("paper_truth_conflict")
                        ],
                    },
                    "known_limitations": [
                        item for item in extraction.known_gaps if factor.factor_id in set(item.get("affects", []) or [])
                    ],
                    "operator_semantics": list(extraction.operator_semantics),
                    "ambiguities_by_category": {},
                    "factor_ambiguities_by_category": {
                        "formula": list(factor.formula_gap_ids),
                        "field_mapping": [],
                        "evaluation": [],
                        "other": [],
                    },
                    "selected_truth_source_ids": [],
                    "truth_selection_rule": extraction.truth_selection_policy,
                    "truth_match_required": bool(candidate_cases),
                    "proof_status_ceiling": "needs_human_review" if not factor_has_unconflicted_truth else "paper_evaluation_match",
                    "status": status,
                    "implementation_stage": "spec",
                },
            )
        )
    return specs


def _project_v2_truth_source_for_factor(
    extraction: ICAnalysisPaperExtraction,
    *,
    factor: ExtractedFactorDefinition,
    truth_source: ExtractedICTruthSource,
    protocol: ExtractedICProtocol,
    pipeline: ExtractedOperationPipeline,
    universe: ExtractedUniverseProtocol,
    sample_period: dict[str, Any],
    semantic_by_id: dict[str, ExtractedSemanticRequirement],
    metric_by_id: dict[str, Any],
    unresolved_conflicts: set[str],
) -> dict[str, Any]:
    compiled = _compile_v2_operation_pipeline(pipeline, semantic_by_id=semantic_by_id)
    horizon = int(protocol.forward_horizon_trading_days)
    horizon_unit = str(protocol.attributes.get("forward_horizon_unit") or "trading_day").strip().lower()
    if horizon_unit == "calendar_month":
        horizon_unit = "natural_month"
    return_field = f"forward_return_{horizon}{'m' if horizon_unit == 'natural_month' else 'd'}"
    controls = list(compiled["required_controls"])
    filter_fields = [
        str(item.get("paper_field", ""))
        for item in universe.filters
        if isinstance(item, dict) and item.get("paper_field")
    ]
    required_semantic_ids = list(
        dict.fromkeys([*factor.required_semantic_fields, "forward_stock_return", *controls, *filter_fields])
    )
    semantic_payloads = [
        _semantic_requirement_payload(semantic_by_id[item])
        if item in semantic_by_id
        else {"semantic_field_id": item, "kind": "universe_filter", "concept": item}
        for item in required_semantic_ids
    ]
    correlation_method = str(extraction.ic_analysis_contract.get("cross_sectional_statistic", "Spearman rank correlation"))
    ic_type = "spearman_rank_ic" if "spearman" in correlation_method.lower() else "pearson_ic"
    conflict = bool(truth_source.conflict_group_id in unresolved_conflicts)
    metric_definitions = {
        metric_id: asdict(metric_by_id[metric_id])
        for metric_id in truth_source.reported_metric_ids
        if metric_id in metric_by_id
    }
    ic_ir_definition = metric_definitions.get("ic_ir", {})
    ic_ir_text = " ".join(
        str(ic_ir_definition.get(key, ""))
        for key in ("paper_label", "definition")
    ).lower()
    ic_ir_convention = "absolute" if any(token in ic_ir_text for token in ("absolute", "绝对值", "abs(")) else "signed"
    return {
        "truth_id": truth_source.truth_source_id,
        "truth_source_id": truth_source.truth_source_id,
        "truth_type": "evaluation_results",
        "description": f"{factor.paper_label} results from {truth_source.truth_source_id}",
        "source_location": _format_source_location(truth_source.source),
        "source": dict(truth_source.source),
        "sample_period": _format_sample_period(sample_period),
        "universe": str(universe.evaluation_universe.get("description") or universe.evaluation_universe.get("base_universe", "")),
        "frequency": factor.native_frequency,
        "evaluation_method": correlation_method,
        "evaluation_family": "ic_analysis",
        "evaluation_spec": {
            "return_horizon": horizon,
            "return_horizon_unit": horizon_unit,
            "return_col": return_field,
            "ic_type": ic_type,
            "ic_ir_convention": ic_ir_convention,
            "signal_schedule": extraction.ic_analysis_contract.get("signal_frequency", "every_trading_day"),
            "sign_convention": extraction.ic_analysis_contract.get("sign_convention", "positive_rank_ic_is_favorable"),
        },
        "transform_spec": compiled["transform_spec"],
        "neutralization_spec": compiled["neutralization_spec"],
        "operation_pipeline": asdict(pipeline),
        "operation_capability_requirements": compiled["capability_requirements"],
        "universe_protocol": {
            "universe_protocol_id": universe.universe_protocol_id,
            "calculation_universe": dict(universe.calculation_universe),
            "evaluation_universe": dict(universe.evaluation_universe),
            "filters": [dict(item) for item in universe.filters],
            "evidence": universe.evidence,
        },
        "required_data": {
            "evaluation": [return_field],
            "controls": controls,
            "universe_filter": filter_fields,
            **(
                {"joint_factor_controls": compiled["joint_factor_controls"]}
                if compiled["joint_factor_controls"]
                else {}
            ),
        },
        "semantic_requirements": semantic_payloads,
        "metrics": dict(truth_source.reported_results[factor.factor_id]),
        "metric_definitions": metric_definitions,
        "protocol_id": protocol.protocol_id,
        "protocol_ref": asdict(protocol),
        "operation_pipeline_id": pipeline.operation_pipeline_id,
        "universe_protocol_id": universe.universe_protocol_id,
        "paper_protocol_refs": {
            "ic_analysis_contract_id": extraction.ic_analysis_contract.get("contract_id", ""),
            "protocol_id": protocol.protocol_id,
            "operation_pipeline_id": pipeline.operation_pipeline_id,
            "universe_protocol_id": universe.universe_protocol_id,
            "sample_period_id": protocol.sample_period_id,
            "truth_source_id": truth_source.truth_source_id,
        },
        "conflict_group_id": truth_source.conflict_group_id or None,
        "paper_truth_conflict": conflict,
        "paper_truth_conflict_status": "unresolved_paper_internal_conflict" if conflict else "none",
        "truth_match_eligible_by_extraction": not conflict,
        "notes": list(truth_source.notes),
        "defaulted_transform_steps": [],
    }


def _compile_v2_operation_pipeline(
    pipeline: ExtractedOperationPipeline,
    *,
    semantic_by_id: dict[str, ExtractedSemanticRequirement],
) -> dict[str, Any]:
    operations = sorted(pipeline.operations, key=lambda item: int(item.get("order", 0)))
    if any(str(item.get("type", "")) == "joint_sequential_orthogonalization" for item in operations):
        factor_controls = list(
            dict.fromkeys(
                value
                for values in (pipeline.attributes.get("additional_factor_controls_by_target", {}) or {}).values()
                for value in (values or [])
            )
        )
        return {
            "transform_spec": {},
            "neutralization_spec": {},
            "required_controls": [],
            "joint_factor_controls": factor_controls,
            "capability_requirements": ["joint_sequential_orthogonalization"],
        }

    neutralize_index = next(
        (index for index, item in enumerate(operations) if str(item.get("type", "")) == "neutralize"),
        None,
    )
    if neutralize_index is None:
        transform_steps = [
            step
            for item in operations
            if (step := _factor_transform_step(item)) is not None
        ]
        return {
            "transform_spec": {
                "steps": transform_steps,
                "compiled_from_operation_pipeline_id": pipeline.operation_pipeline_id,
            },
            "neutralization_spec": {},
            "required_controls": [],
            "joint_factor_controls": [],
            "capability_requirements": [],
        }

    neutralize = operations[neutralize_index]
    declared_controls = [str(item) for item in neutralize.get("controls", []) or []]
    transforms_by_output: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    for item in operations[:neutralize_index]:
        if str(item.get("type", "")) == "transform":
            target = str(item.get("target", ""))
            output = str(item.get("output", target))
            method = _runtime_transform_method(item)
            transforms_by_output[output] = (
                target,
                [{"method": method, "source": "compiled_from_operation_pipeline"}],
            )
        elif str(item.get("type", "")) == "winsorize":
            target = str(item.get("target", ""))
            if target in transforms_by_output:
                transforms_by_output[target][1].append(_runtime_winsor_step(item))

    controls: list[dict[str, Any]] = []
    required_controls: list[str] = []
    for control in declared_controls:
        source_field, transforms = transforms_by_output.get(control, (control, []))
        requirement = semantic_by_id.get(source_field)
        encoding = "categorical" if requirement and requirement.kind == "classification" else "continuous"
        controls.append(
            {
                "paper_field": source_field,
                "semantic_role": requirement.kind if requirement else "control",
                "encoding": encoding,
                "transforms": transforms,
                "source": "compiled_from_operation_pipeline",
            }
        )
        required_controls.append(source_field)

    dependent_transforms = [
        step
        for item in operations[:neutralize_index]
        if str(item.get("target", "factor")) == "factor"
        and (step := _factor_transform_step(item)) is not None
    ]
    output_transforms = [
        step
        for item in operations[neutralize_index + 1 :]
        if (step := _factor_transform_step(item)) is not None
    ]
    return {
        "transform_spec": {},
        "neutralization_spec": {
            "method": "cross_sectional_regression_residual",
            "source": "compiled_from_operation_pipeline",
            "compiled_from_operation_pipeline_id": pipeline.operation_pipeline_id,
            "dependent_variable": {
                "field": "factor_value",
                "transforms": dependent_transforms,
                "source": "compiled_from_operation_pipeline",
            },
            "controls": controls,
            "output_transforms": output_transforms,
        },
        "required_controls": list(dict.fromkeys(required_controls)),
        "joint_factor_controls": [],
        "capability_requirements": [],
    }


def _factor_transform_step(operation: dict[str, Any]) -> dict[str, Any] | None:
    operation_type = str(operation.get("type", ""))
    target = str(operation.get("target", "factor"))
    if target not in {"factor", "factor_residual"} and operation_type not in {"missing_values"}:
        return None
    if operation_type == "winsorize":
        return _runtime_winsor_step(operation)
    if operation_type == "standardize":
        return {"name": "standardization", "method": "cross_section_zscore", "source": "compiled_from_operation_pipeline"}
    if operation_type == "missing_values":
        return {
            "name": "missing_value_policy",
            "method": _runtime_missing_value_method(operation),
            "source": "compiled_from_operation_pipeline",
        }
    if operation_type == "transform":
        return {"name": "transform", "method": _runtime_transform_method(operation), "source": "compiled_from_operation_pipeline"}
    return None


def _runtime_winsor_step(operation: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": "winsorization",
        "method": "median_mad",
        "threshold": float(operation.get("threshold_mad", 5)),
        "source": "compiled_from_operation_pipeline",
    }


def _runtime_transform_method(operation: dict[str, Any]) -> str:
    method = str(operation.get("method", ""))
    return "log" if method in {"natural_log", "ln"} else method


def _runtime_missing_value_method(operation: dict[str, Any]) -> str:
    method = str(operation.get("method", "")).strip().lower()
    aliases = {
        "fill_mean_to_zero": "fill_zero",
        "fill_standardized_mean": "fill_zero",
        "impute_zero": "fill_zero",
        "zero_fill": "fill_zero",
        "do_not_impute": "do_not_fill",
        "leave_missing": "do_not_fill",
    }
    return aliases.get(method, method or "do_not_fill")


def _canonical_formula_field(requirement: ExtractedSemanticRequirement | None, *, fallback: str) -> str:
    concept = requirement.concept if requirement is not None else fallback
    aliases = {
        "daily_open_price": "open",
        "daily_close_price": "close",
        "daily_high_price": "high",
        "daily_low_price": "low",
        "daily_trading_volume": "volume",
        "daily_volume_weighted_average_price": "vwap",
    }
    return aliases.get(concept, fallback.removeprefix("daily_"))


def _semantic_requirement_payload(requirement: ExtractedSemanticRequirement) -> dict[str, Any]:
    return {
        "semantic_field_id": requirement.semantic_field_id,
        "kind": requirement.kind,
        "concept": requirement.concept,
        **dict(requirement.attributes),
        "evidence": requirement.evidence,
    }


def _format_source_location(source: dict[str, Any]) -> str:
    parts = []
    if source.get("page") is not None:
        parts.append(f"page {source['page']}")
    for key in ("table", "section", "column_group", "locator"):
        if source.get(key):
            parts.append(str(source[key]))
    return " / ".join(parts)


def _format_sample_period(sample: dict[str, Any]) -> str:
    start = str(sample.get("start", ""))
    end = str(sample.get("end", ""))
    return f"{start} to {end}" if start or end else ""


def _v2_source_document(extraction: ICAnalysisPaperExtraction) -> str:
    title = str(extraction.paper.get("title", ""))
    publisher = str(extraction.paper.get("publisher", ""))
    year = _v2_publication_year(extraction)
    return f"{title} ({publisher}, {year})"


def _v2_publication_year(extraction: ICAnalysisPaperExtraction) -> int | None:
    publication_date = str(extraction.paper.get("publication_date", ""))
    try:
        return int(publication_date[:4])
    except (TypeError, ValueError):
        return None


def write_specs_module(
    family_dir: str | Path,
    specs: list[FactorResearchSpec],
    *,
    function_name: str = "paper_factor_specs",
) -> Path:
    output_dir = Path(family_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    init_path = output_dir / "__init__.py"
    if not init_path.exists():
        init_path.write_text("from __future__ import annotations\n", encoding="utf-8")

    spec_dicts = [asdict(spec) for spec in specs]
    content = f'''from __future__ import annotations

from contracts.factor_research import FactorResearchSpec, ValidationThreshold

_SPEC_DATA = {pformat(spec_dicts, width=100)}


def {function_name}() -> list[FactorResearchSpec]:
    specs: list[FactorResearchSpec] = []
    for item in _SPEC_DATA:
        payload = dict(item)
        payload["validation_targets"] = [ValidationThreshold(**threshold) for threshold in payload["validation_targets"]]
        specs.append(FactorResearchSpec(**payload))
    return specs
'''
    module_path = output_dir / "specs.py"
    module_path.write_text(content, encoding="utf-8")
    return module_path


def _validation_targets_for_truth(truth_sources: Sequence[object]) -> list[ValidationThreshold]:
    targets = list(PAPER_REPRODUCTION_BASE_THRESHOLDS)
    if truth_sources:
        targets.append(PAPER_EVALUATION_THRESHOLD)
    return targets


def _truth_source_payload(truth_source: object) -> dict[str, Any]:
    payload = asdict(truth_source)
    transform_spec = payload.get("transform_spec", {})
    has_structured_neutralization = bool(payload.get("neutralization_spec"))
    if has_structured_neutralization:
        payload["transform_spec"] = dict(transform_spec) if isinstance(transform_spec, dict) else {}
        payload["defaulted_transform_steps"] = []
        return payload
    if isinstance(transform_spec, dict):
        payload["transform_spec"] = default_transform_spec(transform_spec)
        payload["defaulted_transform_steps"] = list(payload["transform_spec"].get("defaulted_transform_steps", []))
    else:
        payload["transform_spec"] = default_transform_spec({})
        payload["defaulted_transform_steps"] = list(payload["transform_spec"].get("defaulted_transform_steps", []))
    return payload


def _collect_defaulted_transform_steps(truth_sources: Sequence[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for source in truth_sources:
        for step in source.get("defaulted_transform_steps", []):
            if isinstance(step, str) and step not in result:
                result.append(step)
    return result


def _default_transform_step(name: str) -> dict[str, Any]:
    return dict(COMMON_TRANSFORM_DEFAULTS[name])


def _canonical_transform_name(name: str) -> str:
    normalized = name.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "winsorize": "winsorization",
        "median_mad_winsorization": "winsorization",
        "standardize": "standardization",
        "zscore": "standardization",
        "missing_values": "missing_value_policy",
    }
    return aliases.get(normalized, normalized)


def _filter_factor_ambiguities(ambiguities_by_category: dict[str, object], *, factor_index: int) -> dict[str, list[str]]:
    prefix = f"target_factors[{factor_index}]:"
    result: dict[str, list[str]] = {}
    for category in ("formula", "field_mapping", "evaluation", "other"):
        items = ambiguities_by_category.get(category, [])
        if isinstance(items, list):
            result[category] = [item for item in items if isinstance(item, str) and item.startswith(prefix)]
        else:
            result[category] = []
    return result


def _has_any_ambiguity(ambiguities_by_category: dict[str, list[str]]) -> bool:
    return any(ambiguities_by_category.get(category) for category in ambiguities_by_category)


def _source_document(extraction: PaperExtraction) -> str:
    year = extraction.year if extraction.year is not None else "year unknown"
    return f"{extraction.title} ({extraction.source}, {year})"


def _sample_scope(factor: object) -> str:
    parts = []
    sample_period = getattr(factor, "sample_period", "")
    universe = getattr(factor, "universe", "")
    if sample_period.strip():
        parts.append(sample_period.strip())
    if universe.strip():
        parts.append(f"universe: {universe.strip()}")
    return "; ".join(parts)


def _slug(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "_" for character in value).strip("_")
