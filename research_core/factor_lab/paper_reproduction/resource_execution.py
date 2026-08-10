from __future__ import annotations

import hashlib
import json
import resource
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd


@dataclass(slots=True)
class ResourceExecutionConfig:
    """Resource policy for one canonical evaluation scenario."""

    memory_budget_bytes: int | None = None
    standard_copy_amplification: float = 4.0
    projected_copy_amplification: float = 1.75
    hash_chunk_rows: int = 100_000

    def __post_init__(self) -> None:
        if self.memory_budget_bytes is not None and self.memory_budget_bytes <= 0:
            raise ValueError("memory_budget_bytes must be positive when configured")
        if self.standard_copy_amplification < 1.0 or self.projected_copy_amplification < 1.0:
            raise ValueError("copy amplification estimates must be at least 1.0")
        if self.projected_copy_amplification > self.standard_copy_amplification:
            raise ValueError("projected copy amplification cannot exceed the standard estimate")
        if self.hash_chunk_rows <= 0:
            raise ValueError("hash_chunk_rows must be positive")


@dataclass(slots=True)
class ResourcePreflightResult:
    execution_mode: str
    within_budget: bool
    partition_required: bool
    memory_budget_bytes: int | None
    base_resident_bytes: int
    calculation_source_bytes: int
    evaluation_source_bytes: int
    projected_calculation_bytes: int
    projected_evaluation_bytes: int
    estimated_factor_frame_bytes: int
    estimated_standard_peak_bytes: int
    estimated_projected_peak_bytes: int
    calculation_columns: list[str] = field(default_factory=list)
    evaluation_columns: list[str] = field(default_factory=list)
    selected_case_count: int = 0
    active_scenario_count: int = 1
    resource_adaptations: list[str] = field(default_factory=list)
    methodological_deviations: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    schema_version: str = "resource_preflight/v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResourceBudgetExceededError(RuntimeError):
    """Raised before factor execution when safe partitioning is required."""

    def __init__(self, preflight: ResourcePreflightResult):
        self.preflight = preflight
        super().__init__(
            "projected execution exceeds the configured memory budget; "
            "partitioned factor/label execution is required without changing methodology"
        )


def estimate_resource_preflight(
    calculation_panel: pd.DataFrame,
    evaluation_inputs: pd.DataFrame,
    *,
    calculation_columns: list[str],
    evaluation_columns: list[str],
    factor_output_columns: list[str],
    selected_case_count: int,
    config: ResourceExecutionConfig | None = None,
    methodological_deviations: list[str] | None = None,
) -> ResourcePreflightResult:
    """Estimate standard and projected execution without copying full frames."""

    policy = config or ResourceExecutionConfig()
    calculation_columns = _existing_unique_columns(calculation_panel, calculation_columns)
    evaluation_columns = _existing_unique_columns(evaluation_inputs, evaluation_columns)
    calculation_source_bytes = frame_memory_bytes(calculation_panel)
    evaluation_source_bytes = frame_memory_bytes(evaluation_inputs)
    shared_source = calculation_panel is evaluation_inputs
    base_resident_bytes = calculation_source_bytes + (0 if shared_source else evaluation_source_bytes)
    projected_calculation_bytes = frame_memory_bytes(calculation_panel, columns=calculation_columns)
    projected_evaluation_bytes = frame_memory_bytes(evaluation_inputs, columns=evaluation_columns)
    key_bytes_per_row = _key_bytes_per_row(calculation_panel, calculation_columns)
    estimated_factor_frame_bytes = int(
        len(calculation_panel) * (key_bytes_per_row + 8 * max(len(factor_output_columns), 1))
    )
    standard_working_set = calculation_source_bytes + evaluation_source_bytes + estimated_factor_frame_bytes
    projected_working_set = projected_calculation_bytes + projected_evaluation_bytes + estimated_factor_frame_bytes
    estimated_standard_peak_bytes = int(
        base_resident_bytes + standard_working_set * max(policy.standard_copy_amplification, 1.0)
    )
    estimated_projected_peak_bytes = int(
        base_resident_bytes + projected_working_set * max(policy.projected_copy_amplification, 1.0)
    )
    budget = policy.memory_budget_bytes
    standard_over_budget = budget is not None and estimated_standard_peak_bytes > budget
    projected_over_budget = budget is not None and estimated_projected_peak_bytes > budget
    if projected_over_budget:
        execution_mode = "partition_required"
    elif standard_over_budget:
        execution_mode = "resource_bounded_projected"
    else:
        execution_mode = "projected_in_memory"

    adaptations = [
        "logical calculation/evaluation separation without duplicate full-panel copies",
        "required-column projection at factor and evaluator boundaries",
        "incremental order-sensitive data hashing without full-frame sorting",
        "one active price scenario per canonical execution context",
    ]
    limitations: list[str] = []
    if projected_over_budget:
        limitations.append(
            "projected execution still exceeds the configured budget; use verified date partitions rather than shortening the sample"
        )
    deviations = list(methodological_deviations or [])
    return ResourcePreflightResult(
        execution_mode=execution_mode,
        within_budget=not projected_over_budget,
        partition_required=projected_over_budget,
        memory_budget_bytes=budget,
        base_resident_bytes=base_resident_bytes,
        calculation_source_bytes=calculation_source_bytes,
        evaluation_source_bytes=evaluation_source_bytes,
        projected_calculation_bytes=projected_calculation_bytes,
        projected_evaluation_bytes=projected_evaluation_bytes,
        estimated_factor_frame_bytes=estimated_factor_frame_bytes,
        estimated_standard_peak_bytes=estimated_standard_peak_bytes,
        estimated_projected_peak_bytes=estimated_projected_peak_bytes,
        calculation_columns=calculation_columns,
        evaluation_columns=evaluation_columns,
        selected_case_count=selected_case_count,
        resource_adaptations=adaptations,
        methodological_deviations=deviations,
        limitations=limitations,
    )


def frame_memory_bytes(frame: pd.DataFrame, *, columns: list[str] | None = None) -> int:
    selected = frame if columns is None else frame.loc[:, _existing_unique_columns(frame, columns)]
    return int(selected.memory_usage(index=True, deep=True).sum())


def incremental_data_hash(
    named_frames: list[tuple[str, pd.DataFrame]],
    *,
    chunk_rows: int = 100_000,
    source_identity: dict[str, Any] | None = None,
) -> str:
    """Hash relevant frame content in bounded chunks, preserving input row order."""

    digest = hashlib.sha256()
    if source_identity:
        digest.update(
            json.dumps(source_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode(
                "utf-8"
            )
        )
    safe_chunk_rows = max(int(chunk_rows), 1)
    for label, frame in named_frames:
        digest.update(label.encode("utf-8"))
        digest.update(json.dumps(list(frame.columns), ensure_ascii=False).encode("utf-8"))
        digest.update(json.dumps([str(dtype) for dtype in frame.dtypes]).encode("utf-8"))
        digest.update(str(len(frame)).encode("utf-8"))
        for start in range(0, len(frame), safe_chunk_rows):
            chunk = frame.iloc[start : start + safe_chunk_rows]
            digest.update(pd.util.hash_pandas_object(chunk, index=False, categorize=True).values.tobytes())
    return digest.hexdigest()


def process_peak_rss_bytes() -> int:
    measured = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return measured if sys.platform == "darwin" else measured * 1024


def _existing_unique_columns(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    return list(dict.fromkeys(column for column in columns if column in frame.columns))


def _key_bytes_per_row(frame: pd.DataFrame, calculation_columns: list[str]) -> int:
    key_columns = [
        column
        for column in calculation_columns
        if column.lower() in {"date", "datetime", "trade_date", "code", "symbol", "security"}
    ]
    if not key_columns or not len(frame):
        return 16
    return max(int(frame_memory_bytes(frame, columns=key_columns) / len(frame)), 1)
