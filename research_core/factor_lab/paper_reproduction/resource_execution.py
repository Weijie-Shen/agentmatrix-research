from __future__ import annotations

import hashlib
import json
import resource
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
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


@dataclass(frozen=True, slots=True)
class SecurityPartitionSpec:
    """One bounded partition that retains the full requested date history.

    Security partitions are safe for rolling factors because a security is never
    split across date boundaries. Workers should load and execute one spec in a
    fresh process, persist its certified factor output, and release the process
    before starting the next spec.
    """

    partition_id: str
    securities: tuple[str, ...]
    requested_start: str
    requested_end: str
    schema_version: str = "security_partition_spec/v1"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["securities"] = list(self.securities)
        return payload


@dataclass(slots=True)
class SecurityPartitionRecord:
    """Hash and coverage evidence for one completed security partition."""

    partition_id: str
    requested_securities: list[str]
    observed_securities: list[str]
    missing_securities: list[str]
    requested_start: str
    requested_end: str
    observed_start: str | None
    observed_end: str | None
    calculation_row_count: int
    evaluation_row_count: int
    signal_date_count: int
    calculation_hash: str
    evaluation_hash: str
    coverage_complete: bool
    schema_version: str = "security_partition_record/v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def plan_security_partitions(
    securities: list[str],
    *,
    requested_start: str | date | pd.Timestamp,
    requested_end: str | date | pd.Timestamp,
    max_securities_per_partition: int,
) -> list[SecurityPartitionSpec]:
    """Plan deterministic full-history partitions without changing the sample.

    The same requested date bounds are attached to every partition. This is
    intentionally different from calendar-year partitioning, which can sever
    rolling history and change factor values at partition boundaries.
    """

    if max_securities_per_partition <= 0:
        raise ValueError("max_securities_per_partition must be positive")
    start = pd.Timestamp(requested_start)
    end = pd.Timestamp(requested_end)
    if pd.isna(start) or pd.isna(end) or start > end:
        raise ValueError("requested_start and requested_end must define a valid inclusive range")
    unique = sorted({str(value) for value in securities if str(value)})
    if not unique:
        raise ValueError("at least one security is required")
    width = max_securities_per_partition
    return [
        SecurityPartitionSpec(
            partition_id=f"security-{index:05d}",
            securities=tuple(unique[offset : offset + width]),
            requested_start=start.date().isoformat(),
            requested_end=end.date().isoformat(),
        )
        for index, offset in enumerate(range(0, len(unique), width), start=1)
    ]


def certify_security_partition(
    spec: SecurityPartitionSpec,
    calculation_frame: pd.DataFrame,
    evaluation_frame: pd.DataFrame,
    *,
    signal_dates: list[str | date | pd.Timestamp],
    date_col: str = "date",
    security_col: str = "code",
    hash_chunk_rows: int = 100_000,
    source_identity: dict[str, Any] | None = None,
) -> SecurityPartitionRecord:
    """Validate one partition and record bounded lineage before concatenation.

    ``calculation_frame`` must contain only the assigned securities and the full
    requested date slice supplied to the loader. ``evaluation_frame`` may contain
    only signal/evaluation rows and must be a key-subset of the calculation frame.
    Missing requested securities remain explicit in the record rather than being
    silently dropped from the requested universe.
    """

    _require_partition_keys(calculation_frame, date_col=date_col, security_col=security_col)
    _require_partition_keys(evaluation_frame, date_col=date_col, security_col=security_col)
    calculation = calculation_frame.copy(deep=False)
    evaluation = evaluation_frame.copy(deep=False)
    calculation_dates = pd.to_datetime(calculation[date_col], errors="raise")
    evaluation_dates = pd.to_datetime(evaluation[date_col], errors="raise")
    start = pd.Timestamp(spec.requested_start)
    end = pd.Timestamp(spec.requested_end)
    if ((calculation_dates < start) | (calculation_dates > end)).any():
        raise ValueError(f"partition {spec.partition_id} contains calculation rows outside its requested date range")
    requested = set(spec.securities)
    observed = set(calculation[security_col].astype(str))
    unexpected = sorted(observed - requested)
    if unexpected:
        raise ValueError(f"partition {spec.partition_id} contains unassigned securities: {unexpected}")
    allowed_signal_dates = {pd.Timestamp(value) for value in signal_dates}
    unexpected_dates = sorted(set(evaluation_dates) - allowed_signal_dates)
    if unexpected_dates:
        raise ValueError(f"partition {spec.partition_id} contains non-signal evaluation dates: {unexpected_dates}")
    calculation_keys = pd.MultiIndex.from_frame(
        pd.DataFrame({date_col: calculation_dates, security_col: calculation[security_col].astype(str)})
    )
    evaluation_keys = pd.MultiIndex.from_frame(
        pd.DataFrame({date_col: evaluation_dates, security_col: evaluation[security_col].astype(str)})
    )
    if not evaluation_keys.isin(calculation_keys).all():
        raise ValueError(f"partition {spec.partition_id} evaluation keys are not a subset of calculation keys")
    identity = {
        **(source_identity or {}),
        "partition_spec": spec.to_dict(),
    }
    missing = sorted(requested - observed)
    return SecurityPartitionRecord(
        partition_id=spec.partition_id,
        requested_securities=list(spec.securities),
        observed_securities=sorted(observed),
        missing_securities=missing,
        requested_start=spec.requested_start,
        requested_end=spec.requested_end,
        observed_start=calculation_dates.min().date().isoformat() if len(calculation_dates) else None,
        observed_end=calculation_dates.max().date().isoformat() if len(calculation_dates) else None,
        calculation_row_count=len(calculation),
        evaluation_row_count=len(evaluation),
        signal_date_count=evaluation_dates.nunique(),
        calculation_hash=incremental_data_hash(
            [("calculation", calculation)], chunk_rows=hash_chunk_rows, source_identity=identity
        ),
        evaluation_hash=incremental_data_hash(
            [("evaluation", evaluation)], chunk_rows=hash_chunk_rows, source_identity=identity
        ),
        coverage_complete=not missing,
    )


def combine_partition_evaluation_rows(
    frames: list[pd.DataFrame],
    *,
    signal_dates: list[str | date | pd.Timestamp],
    date_col: str = "date",
    security_col: str = "code",
) -> pd.DataFrame:
    """Combine only signal/evaluation rows for the cross-sectional phase."""

    if not frames:
        return pd.DataFrame(columns=[date_col, security_col])
    allowed = {pd.Timestamp(value) for value in signal_dates}
    selected: list[pd.DataFrame] = []
    for frame in frames:
        _require_partition_keys(frame, date_col=date_col, security_col=security_col)
        dates = pd.to_datetime(frame[date_col], errors="raise")
        selected.append(frame.loc[dates.isin(allowed)].copy())
    combined = pd.concat(selected, ignore_index=True)
    if combined.duplicated([date_col, security_col]).any():
        raise ValueError("partition evaluation rows contain duplicate date/security keys")
    return combined.sort_values([date_col, security_col], kind="stable").reset_index(drop=True)


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
            "projected execution still exceeds the configured budget; use verified full-history security partitions rather than shortening the sample"
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


def _require_partition_keys(frame: pd.DataFrame, *, date_col: str, security_col: str) -> None:
    missing = [column for column in (date_col, security_col) if column not in frame.columns]
    if missing:
        raise ValueError(f"partition frame is missing key columns: {missing}")
    if frame.duplicated([date_col, security_col]).any():
        raise ValueError("partition frame contains duplicate date/security keys")


def _key_bytes_per_row(frame: pd.DataFrame, calculation_columns: list[str]) -> int:
    key_columns = [
        column
        for column in calculation_columns
        if column.lower() in {"date", "datetime", "trade_date", "code", "symbol", "security"}
    ]
    if not key_columns or not len(frame):
        return 16
    return max(int(frame_memory_bytes(frame, columns=key_columns) / len(frame)), 1)
