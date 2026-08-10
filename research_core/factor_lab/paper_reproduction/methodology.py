from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


METHODOLOGY_SOURCES = {"explicit", "inferred", "defaulted", "not_specified"}
UNIVERSE_FILTER_STAGES = {
    "raw_data",
    "factor_time_series",
    "factor_cross_section",
    "portfolio_formation",
    "return_realization",
}
EVALUATION_FILTER_STAGES = {"factor_cross_section", "portfolio_formation", "return_realization"}


@dataclass(slots=True)
class MethodologySpecValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UniverseFilterApplicationResult:
    frame: pd.DataFrame = field(repr=False)
    stage: str = "factor_cross_section"
    applied_filters: list[dict[str, Any]] = field(default_factory=list)
    skipped_filters: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def validate_neutralization_spec(spec: dict[str, Any] | None, *, prefix: str = "neutralization_spec") -> MethodologySpecValidationResult:
    if not spec:
        return MethodologySpecValidationResult(True)
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(spec, dict):
        return MethodologySpecValidationResult(False, [f"{prefix} must be an object"])
    if not str(spec.get("method", "")).strip():
        errors.append(f"{prefix}.method is required")
    _validate_provenance(spec, prefix=prefix, warnings=warnings)

    dependent = spec.get("dependent_variable", {}) or {}
    if not isinstance(dependent, dict):
        errors.append(f"{prefix}.dependent_variable must be an object")
    else:
        _validate_transformed_input(dependent, prefix=f"{prefix}.dependent_variable", errors=errors, warnings=warnings, require_field=False)

    controls = spec.get("controls", []) or []
    if not isinstance(controls, list):
        errors.append(f"{prefix}.controls must be a list")
    else:
        for index, control in enumerate(controls):
            control_prefix = f"{prefix}.controls[{index}]"
            if not isinstance(control, dict):
                errors.append(f"{control_prefix} must be an object")
                continue
            _validate_transformed_input(control, prefix=control_prefix, errors=errors, warnings=warnings, require_field=True)

    _validate_transform_list(
        spec.get("output_transforms", []) or [],
        prefix=f"{prefix}.output_transforms",
        errors=errors,
        warnings=warnings,
    )
    return MethodologySpecValidationResult(not errors, errors, warnings)


def validate_universe_protocol(protocol: dict[str, Any] | None, *, prefix: str = "universe_protocol") -> MethodologySpecValidationResult:
    if not protocol:
        return MethodologySpecValidationResult(True)
    if not isinstance(protocol, dict):
        return MethodologySpecValidationResult(False, [f"{prefix} must be an object"])
    errors: list[str] = []
    warnings: list[str] = []
    for universe_name in ("calculation_universe", "evaluation_universe"):
        value = protocol.get(universe_name)
        if isinstance(value, dict):
            _validate_provenance(value, prefix=f"{prefix}.{universe_name}", warnings=warnings)
        elif value not in (None, "") and not isinstance(value, str):
            errors.append(f"{prefix}.{universe_name} must be text or an object")

    filters = protocol.get("filters", []) or []
    if not isinstance(filters, list):
        errors.append(f"{prefix}.filters must be a list")
        return MethodologySpecValidationResult(False, errors, warnings)
    for index, item in enumerate(filters):
        item_prefix = f"{prefix}.filters[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_prefix} must be an object")
            continue
        if not str(item.get("filter_name", "")).strip():
            errors.append(f"{item_prefix}.filter_name is required")
        stage = str(item.get("application_stage", "")).strip()
        if stage not in UNIVERSE_FILTER_STAGES:
            errors.append(f"{item_prefix}.application_stage must be one of {sorted(UNIVERSE_FILTER_STAGES)}")
        if not any(str(item.get(key, "")).strip() for key in ("paper_field", "field", "resolved_field")):
            errors.append(f"{item_prefix} requires paper_field, field, or resolved_field")
        _validate_provenance(item, prefix=item_prefix, warnings=warnings)
        effective_rule = str(item.get("effective_date_rule", "")).lower()
        future_state = any(token in effective_rule for token in ("t+1", "next", "future"))
        if future_state and stage in {"raw_data", "factor_time_series"} and str(item.get("source", "")) != "explicit":
            errors.append(
                f"{item_prefix} applies a future-state filter before factor calculation without explicit paper support"
            )
    return MethodologySpecValidationResult(not errors, errors, warnings)


def apply_universe_protocol(
    frame: pd.DataFrame,
    universe_protocol: dict[str, Any] | None,
    *,
    stage: str = "factor_cross_section",
) -> UniverseFilterApplicationResult:
    """Apply only executable filters declared for one universe stage."""

    if stage not in UNIVERSE_FILTER_STAGES:
        raise ValueError(f"unsupported universe filter stage: {stage}")
    result = frame.copy()
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    limitations: list[str] = []
    input_rows = len(result)
    protocol = universe_protocol or {}
    for item in protocol.get("filters", []) or []:
        if not isinstance(item, dict) or str(item.get("application_stage", "")) != stage:
            continue
        filter_name = str(item.get("filter_name", "") or "unnamed_filter")
        field_name = str(item.get("resolved_field") or item.get("field") or "")
        if str(item.get("runtime_status", "")) == "unavailable" or not field_name:
            skipped.append({"filter_name": filter_name, "reason": "unresolved_filter_field"})
            limitations.append(f"universe filter {filter_name} was not applied because its field is unresolved")
            continue
        if field_name not in result.columns:
            skipped.append({"filter_name": filter_name, "field": field_name, "reason": "missing_filter_field"})
            limitations.append(f"universe filter {filter_name} was not applied because {field_name} is unavailable")
            continue
        try:
            mask = _filter_mask(result[field_name], item)
        except ValueError as exc:
            skipped.append({"filter_name": filter_name, "field": field_name, "reason": str(exc)})
            limitations.append(f"universe filter {filter_name} was not applied: {exc}")
            continue
        before = len(result)
        result = result.loc[mask].copy()
        applied.append(
            {
                "filter_name": filter_name,
                "field": field_name,
                "application_stage": stage,
                "input_rows": before,
                "output_rows": len(result),
                "removed_rows": before - len(result),
            }
        )
    return UniverseFilterApplicationResult(
        frame=result,
        stage=stage,
        applied_filters=applied,
        skipped_filters=skipped,
        limitations=limitations,
        diagnostics={
            "input_rows": input_rows,
            "output_rows": len(result),
            "removed_rows": input_rows - len(result),
        },
    )


def transformed_input_methods(spec: dict[str, Any] | None) -> list[str]:
    if not spec:
        return []
    methods: list[str] = []
    dependent = spec.get("dependent_variable", {}) or {}
    if isinstance(dependent, dict):
        methods.extend(_transform_methods(dependent.get("transforms", []) or []))
    for control in spec.get("controls", []) or []:
        if isinstance(control, dict):
            methods.extend(_transform_methods(control.get("transforms", []) or []))
    methods.extend(_transform_methods(spec.get("output_transforms", []) or []))
    return list(dict.fromkeys(methods))


def canonical_transform_method(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "winsorization": "median_mad",
        "winsorize": "median_mad",
        "median_mad_winsorization": "median_mad",
        "standardization": "cross_section_zscore",
        "standardize": "cross_section_zscore",
        "zscore": "cross_section_zscore",
        "zscore_standardization": "cross_section_zscore",
        "natural_log": "log",
        "ln": "log",
        "missing_value_policy": "do_not_fill",
    }
    return aliases.get(normalized, normalized)


def _validate_transformed_input(
    value: dict[str, Any],
    *,
    prefix: str,
    errors: list[str],
    warnings: list[str],
    require_field: bool,
) -> None:
    if require_field and not any(str(value.get(key, "")).strip() for key in ("paper_field", "field", "resolved_field")):
        errors.append(f"{prefix} requires paper_field, field, or resolved_field")
    _validate_provenance(value, prefix=prefix, warnings=warnings)
    _validate_transform_list(value.get("transforms", []) or [], prefix=f"{prefix}.transforms", errors=errors, warnings=warnings)


def _validate_transform_list(
    transforms: Any,
    *,
    prefix: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    if not isinstance(transforms, list):
        errors.append(f"{prefix} must be a list")
        return
    for index, transform in enumerate(transforms):
        transform_prefix = f"{prefix}[{index}]"
        if not isinstance(transform, dict):
            errors.append(f"{transform_prefix} must be an object")
            continue
        if not str(transform.get("method") or transform.get("name") or "").strip():
            errors.append(f"{transform_prefix}.method is required")
        _validate_provenance(transform, prefix=transform_prefix, warnings=warnings)


def _validate_provenance(value: dict[str, Any], *, prefix: str, warnings: list[str]) -> None:
    source = str(value.get("source", "")).strip()
    if not source:
        warnings.append(f"{prefix}.source is missing; record explicit, inferred, or defaulted provenance")
    elif source not in METHODOLOGY_SOURCES:
        warnings.append(f"{prefix}.source is unrecognized: {source}")
    confidence = value.get("confidence")
    if confidence is not None:
        try:
            numeric = float(confidence)
        except (TypeError, ValueError):
            warnings.append(f"{prefix}.confidence must be numeric")
        else:
            if not 0.0 <= numeric <= 1.0:
                warnings.append(f"{prefix}.confidence must be between 0 and 1")


def _transform_methods(transforms: list[Any]) -> list[str]:
    return [
        canonical_transform_method(str(item.get("method") or item.get("name") or ""))
        for item in transforms
        if isinstance(item, dict) and str(item.get("method") or item.get("name") or "").strip()
    ]


def _filter_mask(series: pd.Series, item: dict[str, Any]) -> pd.Series:
    operator = str(item.get("operator", "equals") or "equals").lower()
    value = item.get("value", False)
    missing_policy = str(item.get("missing_policy", "exclude") or "exclude").lower()
    if operator in {"equals", "eq"}:
        mask = series.eq(value)
    elif operator in {"not_equals", "ne"}:
        mask = series.ne(value)
    elif operator == "in":
        mask = series.isin(value if isinstance(value, list) else [value])
    elif operator == "not_in":
        mask = ~series.isin(value if isinstance(value, list) else [value])
    elif operator in {"falsy", "is_false"}:
        mask = ~series.fillna(False).astype(bool)
    elif operator in {"truthy", "is_true"}:
        mask = series.fillna(False).astype(bool)
    else:
        raise ValueError(f"unsupported filter operator {operator!r}")
    if missing_policy == "include":
        mask = mask | series.isna()
    elif missing_policy == "exclude":
        mask = mask & series.notna()
    else:
        raise ValueError(f"unsupported missing_policy {missing_policy!r}")
    return mask.fillna(False)
