from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from pprint import pformat
from typing import Any

from contracts.factor_research import FactorResearchSpec, ValidationThreshold
from research_core.factor_lab.paper_reproduction.extraction import (
    PaperExtraction,
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
    extraction: PaperExtraction,
    *,
    version: str = "v0.1",
) -> list[FactorResearchSpec]:
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
