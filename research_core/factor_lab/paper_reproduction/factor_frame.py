from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(slots=True)
class FactorFrameValidationResult:
    valid: bool
    execution_status: str
    errors: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FactorFrameAlignmentResult:
    valid: bool
    execution_status: str
    aligned_frame: pd.DataFrame | None = field(default=None, repr=False)
    errors: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "execution_status": self.execution_status,
            "errors": list(self.errors),
            "limitations": list(self.limitations),
            "diagnostics": dict(self.diagnostics),
        }


def validate_factor_frame(
    frame: pd.DataFrame,
    *,
    key_columns: list[str],
    factor_columns: list[str],
) -> FactorFrameValidationResult:
    """Validate the canonical keyed FactorFrame contract."""

    errors: list[str] = []
    diagnostics: dict[str, Any] = {"row_count": len(frame), "columns": list(frame.columns)}
    required = [*key_columns, *factor_columns]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        errors.append(f"factor frame is missing declared columns: {missing}")
        return FactorFrameValidationResult(False, "failed", errors, [], diagnostics)

    normalized = normalize_key_columns(frame, key_columns=key_columns)
    null_key_rows = int(normalized[key_columns].isna().any(axis=1).sum())
    duplicate_key_rows = int(normalized.duplicated(key_columns, keep=False).sum())
    diagnostics["null_key_rows"] = null_key_rows
    diagnostics["duplicate_key_rows"] = duplicate_key_rows
    if null_key_rows:
        errors.append(f"factor frame contains {null_key_rows} rows with null keys")
    if duplicate_key_rows:
        errors.append(f"factor frame contains {duplicate_key_rows} rows with duplicate keys")

    nonnumeric = [column for column in factor_columns if not pd.api.types.is_numeric_dtype(frame[column])]
    diagnostics["factor_null_ratios"] = {
        column: float(pd.to_numeric(frame[column], errors="coerce").isna().mean()) for column in factor_columns
    }
    if nonnumeric:
        errors.append(f"factor frame contains nonnumeric factor columns: {nonnumeric}")
    return FactorFrameValidationResult(
        valid=not errors,
        execution_status="completed" if not errors else "failed",
        errors=errors,
        diagnostics=diagnostics,
    )


def align_factor_frame(
    evaluation_inputs: pd.DataFrame,
    factor_frame: pd.DataFrame,
    *,
    key_columns: list[str],
    factor_columns: list[str],
) -> FactorFrameAlignmentResult:
    """Align factor values one-to-one by normalized semantic keys."""

    validation = validate_factor_frame(factor_frame, key_columns=key_columns, factor_columns=factor_columns)
    errors = list(validation.errors)
    limitations: list[str] = []
    diagnostics = {"factor_frame_validation": validation.diagnostics}
    missing_left_keys = [column for column in key_columns if column not in evaluation_inputs.columns]
    if missing_left_keys:
        errors.append(f"evaluation inputs are missing key columns: {missing_left_keys}")
    colliding_factor_columns = [column for column in factor_columns if column in evaluation_inputs.columns]
    if colliding_factor_columns:
        errors.append(
            "evaluation inputs must not contain artifact factor columns: "
            f"{colliding_factor_columns}"
        )
    if errors:
        return FactorFrameAlignmentResult(False, "failed", errors=errors, limitations=limitations, diagnostics=diagnostics)

    left = normalize_key_columns(evaluation_inputs, key_columns=key_columns)
    right = normalize_key_columns(factor_frame[[*key_columns, *factor_columns]], key_columns=key_columns)
    left_null_keys = int(left[key_columns].isna().any(axis=1).sum())
    left_duplicate_keys = int(left.duplicated(key_columns, keep=False).sum())
    diagnostics["evaluation_null_key_rows"] = left_null_keys
    diagnostics["evaluation_duplicate_key_rows"] = left_duplicate_keys
    if left_null_keys:
        errors.append(f"evaluation inputs contain {left_null_keys} rows with null keys")
    if left_duplicate_keys:
        errors.append(f"evaluation inputs contain {left_duplicate_keys} rows with duplicate keys")
    if errors:
        return FactorFrameAlignmentResult(False, "failed", errors=errors, limitations=limitations, diagnostics=diagnostics)

    key_comparison = left[key_columns].merge(
        right[key_columns],
        on=key_columns,
        how="outer",
        indicator=True,
        validate="one_to_one",
    )
    left_only = int((key_comparison["_merge"] == "left_only").sum())
    right_only = int((key_comparison["_merge"] == "right_only").sum())
    matched = int((key_comparison["_merge"] == "both").sum())
    denominator = max(len(left), 1)
    diagnostics.update(
        {
            "evaluation_row_count": len(left),
            "factor_row_count": len(right),
            "matched_rows": matched,
            "left_only_rows": left_only,
            "right_only_rows": right_only,
            "matched_row_ratio": float(matched / denominator),
        }
    )
    if left_only or right_only:
        limitations.append(f"key coverage is incomplete: evaluation-only={left_only}, factor-only={right_only}")

    if len(left) == len(right) and left[key_columns].reset_index(drop=True).equals(right[key_columns].reset_index(drop=True)):
        aligned = pd.concat(
            [left.reset_index(drop=True), right[factor_columns].reset_index(drop=True)],
            axis=1,
        )
        diagnostics["alignment_method"] = "verified_positional_fast_path"
    else:
        aligned = left.merge(
            right,
            on=key_columns,
            how="left",
            validate="one_to_one",
            sort=False,
        )
        diagnostics["alignment_method"] = "one_to_one_key_join"

    factor_null_ratios = {
        column: float(pd.to_numeric(aligned[column], errors="coerce").isna().mean()) for column in factor_columns
    }
    diagnostics["factor_null_ratios"] = factor_null_ratios
    if any(value > 0 for value in factor_null_ratios.values()):
        limitations.append("aligned factor values contain nulls; warm-up or unmatched observations remain non-blocking")
    return FactorFrameAlignmentResult(
        valid=True,
        execution_status="completed_with_limitations" if limitations else "completed",
        aligned_frame=aligned,
        errors=[],
        limitations=limitations,
        diagnostics=diagnostics,
    )


def normalize_key_columns(frame: pd.DataFrame, *, key_columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in key_columns:
        if column.lower() in {"date", "datetime", "trade_date"}:
            result[column] = pd.to_datetime(result[column], errors="coerce")
        else:
            result[column] = result[column].astype("string")
    return result
