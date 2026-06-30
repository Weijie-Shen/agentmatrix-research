from __future__ import annotations

from dataclasses import dataclass, field
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
