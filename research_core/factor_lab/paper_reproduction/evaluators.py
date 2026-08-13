from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from research_core.factor_lab.paper_reproduction.methodology import canonical_transform_method


DEFAULT_DATE_COL = "date"
DEFAULT_CODE_COL = "code"
PROCESSED_FACTOR_COL = "processed_factor"
GENERIC_IC_REGRESSION_EVALUATOR_ID = "generic_ic_regression_v1"


GENERIC_EVALUATOR_CAPABILITIES: dict[str, dict[str, Any]] = {
    GENERIC_IC_REGRESSION_EVALUATOR_ID: {
        "evaluator_id": GENERIC_IC_REGRESSION_EVALUATOR_ID,
        "evaluation_families": ["ic_analysis", "ic_regression"],
        "capabilities": {
            "ic_types": ["spearman_rank_ic", "pearson_ic"],
            "regression_types": ["ols", "wls"],
            "categorical_controls": True,
            "continuous_controls": True,
            "weighting": True,
            "return_horizon_units": ["trading_day"],
            "standard_errors": ["classical"],
            "transform_steps": [
                "median_mad",
                "log",
                "cross_sectional_regression_residual",
                "cross_section_zscore",
                "do_not_fill",
                "none",
            ],
            "neutralization_methods": ["cross_sectional_regression_residual", "none"],
            "input_transform_methods": ["median_mad", "log", "cross_section_zscore", "do_not_fill", "none"],
            "control_encodings": ["continuous", "categorical", "dummy"],
            "metrics": [
                "rank_ic_mean",
                "rank_ic_std",
                "ic_mean",
                "ic_std",
                "ic_ir",
                "ic_positive_ratio",
                "rank_ic_positive_ratio",
                "factor_return_mean",
                "t_abs_mean",
                "t_abs_gt_2_ratio",
                "t_mean",
            ],
        },
    }
}


def get_generic_evaluator_capabilities(evaluator_id: str = GENERIC_IC_REGRESSION_EVALUATOR_ID) -> dict[str, Any]:
    try:
        return GENERIC_EVALUATOR_CAPABILITIES[evaluator_id]
    except KeyError as exc:
        raise KeyError(f"Unknown generic evaluator: {evaluator_id}") from exc


def evaluator_capabilities_for_case(evaluation_case: dict[str, Any]) -> dict[str, Any] | None:
    family = str(evaluation_case.get("evaluation_family", ""))
    for descriptor in GENERIC_EVALUATOR_CAPABILITIES.values():
        if family in set(descriptor.get("evaluation_families", []) or []):
            return descriptor
    return None


def apply_transform_spec(
    frame: pd.DataFrame,
    *,
    value_col: str,
    transform_spec: dict[str, Any] | None = None,
    date_col: str = DEFAULT_DATE_COL,
    output_col: str = PROCESSED_FACTOR_COL,
) -> pd.DataFrame:
    """Apply a conservative cross-sectional transform pipeline to a factor frame."""

    _require_columns(frame, [date_col, value_col])
    result = frame.copy()
    result[output_col] = pd.to_numeric(result[value_col], errors="coerce")
    for step in (transform_spec or {}).get("steps", []):
        if not isinstance(step, dict):
            raise ValueError("transform_spec steps must be dictionaries")
        name = str(step.get("name", "")).lower()
        method = str(step.get("method", "")).lower()
        if name == "neutralization" and method == "cross_sectional_regression_residual":
            controls = [str(control) for control in step.get("controls", [])]
            _require_columns(result, controls)
            result[output_col] = _neutralize_by_date(
                result,
                date_col=date_col,
                value_col=output_col,
                controls=controls,
            )
        elif name == "neutralization" and method in {"none", ""}:
            continue
        else:
            result[output_col], _ = _apply_input_transforms(
                result[output_col],
                frame=result,
                transforms=[step],
                date_col=date_col,
            )
    return result


def apply_neutralization_spec(
    frame: pd.DataFrame,
    *,
    value_col: str,
    neutralization_spec: dict[str, Any] | None,
    date_col: str = DEFAULT_DATE_COL,
    output_col: str = PROCESSED_FACTOR_COL,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Execute ordered factor/control transforms and cross-sectional neutralization."""

    _require_columns(frame, [date_col, value_col])
    result = frame.copy()
    result[output_col] = pd.to_numeric(result[value_col], errors="coerce")
    spec = neutralization_spec or {}
    diagnostics: dict[str, Any] = {
        "method": str(spec.get("method", "") or "none"),
        "dependent_transforms": [],
        "control_transforms": [],
        "output_transforms": [],
        "used_controls": [],
        "skipped_controls": [],
    }
    dependent = spec.get("dependent_variable", {}) or {}
    dependent_transforms = dependent.get("transforms", []) if isinstance(dependent, dict) else []
    result[output_col], applied = _apply_input_transforms(
        result[output_col],
        frame=result,
        transforms=dependent_transforms or [],
        date_col=date_col,
    )
    diagnostics["dependent_transforms"] = applied

    working_controls: list[str] = []
    for index, control in enumerate(spec.get("controls", []) or []):
        if not isinstance(control, dict):
            continue
        paper_field = str(control.get("paper_field") or control.get("field") or f"control_{index}")
        source_field = str(control.get("resolved_field") or control.get("field") or "")
        if str(control.get("runtime_status", "")) == "unavailable" or not source_field or source_field not in result.columns:
            diagnostics["skipped_controls"].append(
                {"paper_field": paper_field, "field": source_field or None, "reason": "unavailable"}
            )
            continue
        encoding = str(control.get("encoding", "continuous") or "continuous").lower()
        internal_field = f"__neutralization_control_{index}"
        if encoding in {"categorical", "dummy"} and not control.get("transforms"):
            result[internal_field] = result[source_field].astype("string")
            applied_transforms: list[str] = []
        else:
            base = pd.to_numeric(result[source_field], errors="coerce")
            result[internal_field], applied_transforms = _apply_input_transforms(
                base,
                frame=result,
                transforms=control.get("transforms", []) or [],
                date_col=date_col,
            )
        working_controls.append(internal_field)
        diagnostics["used_controls"].append(
            {
                "paper_field": paper_field,
                "source_field": source_field,
                "runtime_field": internal_field,
                "encoding": encoding,
            }
        )
        diagnostics["control_transforms"].append(
            {"paper_field": paper_field, "source_field": source_field, "methods": applied_transforms}
        )

    method = str(spec.get("method", "") or "none").lower()
    if method == "cross_sectional_regression_residual" and working_controls:
        result[output_col] = _neutralize_by_date(
            result,
            date_col=date_col,
            value_col=output_col,
            controls=working_controls,
        )
    elif method in {"none", ""}:
        pass
    elif method == "cross_sectional_regression_residual":
        diagnostics["neutralization_skipped_reason"] = "no_executable_controls"
    else:
        raise ValueError(f"Unsupported neutralization method: {method}")

    result[output_col], output_applied = _apply_input_transforms(
        result[output_col],
        frame=result,
        transforms=spec.get("output_transforms", []) or [],
        date_col=date_col,
    )
    diagnostics["output_transforms"] = output_applied
    return result, diagnostics


def compute_ic_analysis(
    frame: pd.DataFrame,
    *,
    factor_col: str,
    return_col: str,
    method: str = "spearman",
    date_col: str = DEFAULT_DATE_COL,
) -> dict[str, Any]:
    """Compute cross-sectional IC metrics by date."""

    _require_columns(frame, [date_col, factor_col, return_col])
    ic_values: list[float] = []
    for _, group in frame[[date_col, factor_col, return_col]].dropna().groupby(date_col):
        if len(group) < 2:
            continue
        factor = group[factor_col]
        returns = group[return_col]
        if method in {"spearman", "rank_ic", "spearman_rank_ic"}:
            value = factor.rank(method="average").corr(returns.rank(method="average"))
        elif method in {"pearson", "ic", "pearson_ic"}:
            value = factor.corr(returns)
        else:
            raise ValueError(f"Unsupported IC method: {method}")
        if pd.notna(value):
            ic_values.append(float(value))
    mean = _mean_or_nan(ic_values)
    std = _std_or_nan(ic_values)
    positive_ratio = float(sum(value > 0 for value in ic_values) / len(ic_values)) if ic_values else float("nan")
    result = {
        "rank_ic_mean" if method in {"spearman", "rank_ic", "spearman_rank_ic"} else "ic_mean": mean,
        "rank_ic_std" if method in {"spearman", "rank_ic", "spearman_rank_ic"} else "ic_std": std,
        "ic_ir": float(mean / std) if pd.notna(mean) and pd.notna(std) and std != 0 else float("nan"),
        "ic_positive_ratio": positive_ratio,
        "cross_section_count": len(ic_values),
        "ic_values": ic_values,
    }
    if method in {"spearman", "rank_ic", "spearman_rank_ic"}:
        result["rank_ic_positive_ratio"] = positive_ratio
    return result


def compute_cross_sectional_regression(
    frame: pd.DataFrame,
    *,
    factor_col: str,
    return_col: str,
    controls: list[str] | None = None,
    date_col: str = DEFAULT_DATE_COL,
    regression_type: str = "ols",
    weight_col: str | None = None,
) -> dict[str, Any]:
    """Run per-date cross-sectional regressions and summarize factor coefficient/t-stat series."""

    controls = controls or []
    required = [date_col, factor_col, return_col, *controls]
    if regression_type == "wls" and weight_col:
        required.append(weight_col)
    _require_columns(frame, required)

    coefficients: list[float] = []
    t_values: list[float] = []
    for _, group in frame[required].dropna().groupby(date_col):
        if len(group) < 2:
            continue
        coefficient, t_value = _fit_cross_sectional_regression(
            group,
            factor_col=factor_col,
            return_col=return_col,
            controls=controls,
            regression_type=regression_type,
            weight_col=weight_col,
        )
        if pd.notna(coefficient):
            coefficients.append(float(coefficient))
        if pd.notna(t_value):
            t_values.append(float(t_value))

    abs_t = [abs(value) for value in t_values]
    return {
        "factor_return_mean": _mean_or_nan(coefficients),
        "t_abs_mean": _mean_or_nan(abs_t),
        "t_abs_gt_2_ratio": float(sum(value > 2 for value in abs_t) / len(abs_t)) if abs_t else float("nan"),
        "t_mean": _mean_or_nan(t_values),
        "cross_section_count": len(coefficients),
        "factor_returns": coefficients,
        "t_values": t_values,
        "regression_type": regression_type,
        "controls": list(controls),
        "weight_col": weight_col,
    }


def evaluate_paper_case(
    evaluation_case: dict[str, Any],
    frame: pd.DataFrame,
    *,
    factor_col: str,
    date_col: str = DEFAULT_DATE_COL,
) -> dict[str, Any]:
    """Evaluate a supported paper evaluation case on a prepared frame."""

    runtime_case = _runtime_case(evaluation_case)
    family = str(runtime_case.get("evaluation_family", ""))
    if family not in {"ic_analysis", "ic_regression"}:
        raise NotImplementedError(f"Generic evaluator not implemented for evaluation_family={family!r}")
    evaluator_descriptor = evaluator_capabilities_for_case(runtime_case) or get_generic_evaluator_capabilities()
    transform_spec = runtime_case.get("transform_spec") or {}
    neutralization_spec = runtime_case.get("neutralization_spec") or {}
    if neutralization_spec:
        legacy_factor_spec = dict(transform_spec)
        legacy_factor_spec["steps"] = [
            step
            for step in transform_spec.get("steps", []) or []
            if not isinstance(step, dict) or str(step.get("name", "")).lower() != "neutralization"
        ]
        transformed = apply_transform_spec(frame, value_col=factor_col, transform_spec=legacy_factor_spec, date_col=date_col)
        transformed, neutralization_diagnostics = apply_neutralization_spec(
            transformed,
            value_col=PROCESSED_FACTOR_COL,
            neutralization_spec=neutralization_spec,
            date_col=date_col,
            output_col=PROCESSED_FACTOR_COL,
        )
    else:
        transformed = apply_transform_spec(frame, value_col=factor_col, transform_spec=transform_spec, date_col=date_col)
        neutralization_diagnostics = {}
    evaluation_spec = runtime_case.get("evaluation_spec") or {}
    required_data = runtime_case.get("required_data") or {}
    return_col = str(evaluation_spec.get("return_col") or _first_required(required_data, "evaluation") or "forward_return_1d")
    ic_type = str(evaluation_spec.get("ic_type", "spearman_rank_ic")).lower()
    method = _ic_method_from_type(ic_type)
    ic_metrics = compute_ic_analysis(transformed, factor_col=PROCESSED_FACTOR_COL, return_col=return_col, method=method, date_col=date_col)
    if family == "ic_regression":
        controls = [str(control) for control in evaluation_spec.get("regression_controls", []) or required_data.get("controls", [])]
        regression_metrics = compute_cross_sectional_regression(
            transformed,
            factor_col=PROCESSED_FACTOR_COL,
            return_col=return_col,
            controls=controls,
            regression_type=str(evaluation_spec.get("regression_type", "ols")),
            weight_col=evaluation_spec.get("weight_col"),
            date_col=date_col,
        )
        metrics: dict[str, Any] = {"ic": ic_metrics, "regression": regression_metrics}
    else:
        metrics = ic_metrics
    return {
        "execution_mode": "low_level_noncanonical",
        "case_id": evaluation_case.get("case_id") or evaluation_case.get("truth_id", ""),
        "source_truth_id": evaluation_case.get("source_truth_id") or evaluation_case.get("truth_id", ""),
        "evaluator_id": evaluator_descriptor["evaluator_id"],
        "evaluation_family": family,
        "status": "passed",
        "metrics": metrics,
        "resolved_parameters": {
            "evaluation_spec": evaluation_spec,
            "required_data": required_data,
            "neutralization_spec": neutralization_spec,
            "return_col": return_col,
            "date_col": date_col,
        },
        "transform_applied": bool(transform_spec.get("steps") or neutralization_spec),
        "neutralization_diagnostics": neutralization_diagnostics,
        "factor_col": factor_col,
        "processed_factor_col": PROCESSED_FACTOR_COL,
        "return_col": return_col,
    }


def _runtime_case(evaluation_case: dict[str, Any]) -> dict[str, Any]:
    resolved_protocol = evaluation_case.get("resolved_protocol", {})
    if not isinstance(resolved_protocol, dict) or not resolved_protocol:
        return evaluation_case
    runtime = dict(evaluation_case)
    for key in (
        "evaluation_family",
        "evaluation_method",
        "evaluation_spec",
        "required_data",
        "transform_spec",
        "neutralization_spec",
        "universe_protocol",
    ):
        if key in resolved_protocol:
            runtime[key] = resolved_protocol[key]
    return runtime


def _median_mad_winsorize(series: pd.Series, *, threshold: float) -> pd.Series:
    median = series.median(skipna=True)
    mad = (series - median).abs().median(skipna=True)
    if pd.isna(median) or pd.isna(mad) or mad == 0:
        return series
    return series.clip(lower=median - threshold * mad, upper=median + threshold * mad)


def _zscore(series: pd.Series) -> pd.Series:
    std = series.std(skipna=True, ddof=0)
    if pd.isna(std) or std == 0:
        return series * np.nan
    return (series - series.mean(skipna=True)) / std


def _apply_input_transforms(
    series: pd.Series,
    *,
    frame: pd.DataFrame,
    transforms: list[Any],
    date_col: str,
) -> tuple[pd.Series, list[str]]:
    result = series.copy()
    applied: list[str] = []
    for raw_transform in transforms:
        if not isinstance(raw_transform, dict):
            raise ValueError("input transform entries must be dictionaries")
        method = canonical_transform_method(str(raw_transform.get("method") or raw_transform.get("name") or ""))
        if method == "median_mad":
            threshold = float(raw_transform.get("threshold", 5.0))
            result = result.groupby(frame[date_col], group_keys=False).apply(
                lambda values: _median_mad_winsorize(values, threshold=threshold)
            )
        elif method == "log":
            numeric = pd.to_numeric(result, errors="coerce")
            result = np.log(numeric.where(numeric > 0))
        elif method == "cross_section_zscore":
            result = result.groupby(frame[date_col], group_keys=False).apply(_zscore)
        elif method in {"do_not_fill", "none", ""}:
            pass
        else:
            raise ValueError(f"Unsupported input transform method: {method}")
        applied.append(method)
    return pd.Series(result, index=series.index), applied


def _neutralize_group(group: pd.DataFrame, *, value_col: str, controls: list[str]) -> pd.Series:
    cols = [value_col, *controls]
    data = group[cols].copy()
    for control in controls:
        if not pd.api.types.is_numeric_dtype(data[control]):
            dummies = pd.get_dummies(data[control], prefix=control, dtype=float)
            data = pd.concat([data.drop(columns=[control]), dummies], axis=1)
    data = data.apply(pd.to_numeric, errors="coerce")
    valid = data.dropna()
    residuals = pd.Series(np.nan, index=group.index, dtype=float)
    if len(valid) <= 1:
        return residuals
    y = valid[value_col].to_numpy(dtype=float)
    x = valid.drop(columns=[value_col]).to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    try:
        beta = np.linalg.lstsq(x, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        return residuals
    residuals.loc[valid.index] = y - x @ beta
    return residuals


def _neutralize_by_date(
    frame: pd.DataFrame,
    *,
    date_col: str,
    value_col: str,
    controls: list[str],
) -> pd.Series:
    residuals = pd.Series(np.nan, index=frame.index, dtype=float)
    for _, group in frame.groupby(date_col, sort=False):
        residuals.loc[group.index] = _neutralize_group(group, value_col=value_col, controls=controls)
    return residuals


def _fit_cross_sectional_regression(
    group: pd.DataFrame,
    *,
    factor_col: str,
    return_col: str,
    controls: list[str],
    regression_type: str,
    weight_col: str | None,
) -> tuple[float, float]:
    design = _regression_design(group, factor_col=factor_col, controls=controls)
    y = pd.to_numeric(group[return_col], errors="coerce")
    data = pd.concat([y.rename(return_col), design], axis=1).dropna()
    if len(data) < 2 or factor_col not in data.columns:
        return float("nan"), float("nan")
    y_values = data[return_col].to_numpy(dtype=float)
    x_values = data.drop(columns=[return_col]).to_numpy(dtype=float)

    if regression_type == "wls":
        if not weight_col:
            raise ValueError("weight_col is required for wls regression")
        weights = pd.to_numeric(group.loc[data.index, weight_col], errors="coerce").to_numpy(dtype=float)
        valid_weights = np.isfinite(weights) & (weights > 0)
        y_values = y_values[valid_weights]
        x_values = x_values[valid_weights]
        weights = weights[valid_weights]
        sqrt_weights = np.sqrt(weights)
        y_values = y_values * sqrt_weights
        x_values = x_values * sqrt_weights[:, None]
    elif regression_type != "ols":
        raise ValueError(f"Unsupported regression_type: {regression_type}")

    if len(y_values) <= 1:
        return float("nan"), float("nan")
    try:
        beta, *_ = np.linalg.lstsq(x_values, y_values, rcond=None)
    except np.linalg.LinAlgError:
        return float("nan"), float("nan")
    column_names = list(data.drop(columns=[return_col]).columns)
    factor_index = column_names.index(factor_col)
    coefficient = float(beta[factor_index])
    residuals = y_values - x_values @ beta
    dof = len(y_values) - x_values.shape[1]
    if dof <= 0:
        return coefficient, float("nan")
    rss = float(np.square(residuals).sum())
    sigma2 = rss / dof
    if sigma2 <= 1e-24:
        t_value = float("inf") if coefficient > 0 else float("-inf") if coefficient < 0 else 0.0
        return coefficient, t_value
    covariance = sigma2 * np.linalg.pinv(x_values.T @ x_values)
    se = float(np.sqrt(max(covariance[factor_index, factor_index], 0.0)))
    if se == 0:
        return coefficient, float("nan")
    return coefficient, float(coefficient / se)


def _regression_design(group: pd.DataFrame, *, factor_col: str, controls: list[str]) -> pd.DataFrame:
    parts = [pd.Series(1.0, index=group.index, name="const"), pd.to_numeric(group[factor_col], errors="coerce").rename(factor_col)]
    for control in controls:
        series = group[control]
        if pd.api.types.is_numeric_dtype(series):
            parts.append(pd.to_numeric(series, errors="coerce").rename(control))
        else:
            parts.append(pd.get_dummies(series, prefix=control, drop_first=True, dtype=float))
    return pd.concat(parts, axis=1)


def _mean_or_nan(values: list[float]) -> float:
    return float(np.mean(values)) if values else float("nan")


def _std_or_nan(values: list[float]) -> float:
    return float(np.std(values, ddof=1)) if len(values) >= 2 else float("nan")


def _first_required(required_data: Any, key: str) -> str | None:
    if not isinstance(required_data, dict):
        return None
    values = required_data.get(key, [])
    if isinstance(values, list) and values:
        return str(values[0])
    return None


def _ic_method_from_type(ic_type: str) -> str:
    if ic_type in {"spearman", "rank_ic", "spearman_rank_ic"}:
        return "spearman"
    if ic_type in {"pearson", "ic", "pearson_ic"}:
        return "pearson"
    raise ValueError(f"Unsupported IC type: {ic_type}")


def _require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    missing = [column for column in columns if column and column not in frame.columns]
    if missing:
        raise ValueError(f"Missing required column(s): {', '.join(missing)}")
