from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from pprint import pformat

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
                    "evaluation_cases": [asdict(truth) for truth in selected_truth],
                    "known_limitations": list(factor.known_limitations),
                    "truth_sources": [asdict(truth) for truth in factor.truth_sources],
                    "selected_truth_sources": [asdict(truth) for truth in selected_truth],
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
