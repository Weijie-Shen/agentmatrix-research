from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


DEFAULT_DATE_COL = "date"
DEFAULT_CODE_COL = "code"
PROCESSED_FACTOR_COL = "processed_factor"


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
        if name in {"winsorization", "winsorize"} and method == "median_mad":
            threshold = float(step.get("threshold", 5.0))
            result[output_col] = result.groupby(date_col, group_keys=False)[output_col].apply(
                lambda series: _median_mad_winsorize(series, threshold=threshold)
            )
        elif name == "neutralization" and method == "cross_sectional_regression_residual":
            controls = [str(control) for control in step.get("controls", [])]
            _require_columns(result, controls)
            result[output_col] = result.groupby(date_col, group_keys=False).apply(
                lambda group: _neutralize_group(group, value_col=output_col, controls=controls), include_groups=False
            )
            if isinstance(result[output_col].index, pd.MultiIndex):
                result[output_col] = result[output_col].reset_index(level=0, drop=True).sort_index()
        elif name in {"standardization", "standardize"} and method in {"cross_section_zscore", "zscore"}:
            result[output_col] = result.groupby(date_col, group_keys=False)[output_col].apply(_zscore)
        elif name in {"missing_value_policy", "missing_values"} and method in {"do_not_fill", "none", ""}:
            continue
        elif name == "neutralization" and method in {"none", ""}:
            continue
        else:
            raise ValueError(f"Unsupported transform step: name={name!r}, method={method!r}")
    return result


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
    return {
        "rank_ic_mean" if method in {"spearman", "rank_ic", "spearman_rank_ic"} else "ic_mean": mean,
        "rank_ic_std" if method in {"spearman", "rank_ic", "spearman_rank_ic"} else "ic_std": std,
        "ic_ir": float(mean / std) if pd.notna(mean) and pd.notna(std) and std != 0 else float("nan"),
        "ic_positive_ratio": float(sum(value > 0 for value in ic_values) / len(ic_values)) if ic_values else float("nan"),
        "cross_section_count": len(ic_values),
        "ic_values": ic_values,
    }


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

    family = str(evaluation_case.get("evaluation_family", ""))
    if family not in {"ic_analysis", "ic_regression"}:
        raise NotImplementedError(f"Generic evaluator not implemented for evaluation_family={family!r}")
    transform_spec = evaluation_case.get("transform_spec") or {}
    transformed = apply_transform_spec(frame, value_col=factor_col, transform_spec=transform_spec, date_col=date_col)
    evaluation_spec = evaluation_case.get("evaluation_spec") or {}
    required_data = evaluation_case.get("required_data") or {}
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
        "case_id": evaluation_case.get("case_id") or evaluation_case.get("truth_id", ""),
        "evaluation_family": family,
        "status": "passed",
        "metrics": metrics,
        "transform_applied": bool(transform_spec.get("steps")),
        "factor_col": factor_col,
        "processed_factor_col": PROCESSED_FACTOR_COL,
        "return_col": return_col,
    }


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
