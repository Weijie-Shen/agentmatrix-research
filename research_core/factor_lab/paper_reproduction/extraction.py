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
class ExtractionValidationResult:
    valid: bool
    status: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def validate_paper_extraction(extraction: PaperExtraction) -> ExtractionValidationResult:
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
    extraction: PaperExtraction,
    *,
    config: FactorLabWorkspaceConfig | None = None,
) -> Path:
    workspace = config or FactorLabWorkspaceConfig()
    workspace.ensure_directories()
    output_dir = workspace.runtime_root / "paper_specs"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{extraction.paper_id}_extracted.json"
    path.write_text(json.dumps(asdict(extraction), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_paper_extraction(path: str | Path) -> PaperExtraction:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
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
