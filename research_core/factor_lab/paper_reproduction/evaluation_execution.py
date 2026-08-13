from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from research_core.factor_lab.paper_reproduction.evaluators import (
    evaluator_capabilities_for_case,
    evaluate_paper_case,
)
from research_core.factor_lab.paper_reproduction.factor_frame import align_factor_frame, validate_factor_frame
from research_core.factor_lab.paper_reproduction.implementation import (
    FactorImplementationArtifact,
    execute_factor_callable,
)
from research_core.factor_lab.paper_reproduction.methodology import apply_universe_protocol
from research_core.factor_lab.paper_reproduction.paper_evaluation import PaperEvaluationPlan
from research_core.factor_lab.paper_reproduction.resource_execution import (
    ResourceBudgetExceededError,
    ResourceExecutionConfig,
    estimate_resource_preflight,
    incremental_data_hash,
    process_peak_rss_bytes,
)


@dataclass(slots=True)
class EvaluationDataContext:
    """Separate factor-calculation history from possibly filtered evaluation inputs."""

    calculation_panel: pd.DataFrame = field(repr=False)
    evaluation_inputs: pd.DataFrame | None = field(default=None, repr=False)
    scenario_id: str = "base"
    data_snapshot_hash: str = ""
    source_identity: dict[str, Any] = field(default_factory=dict)
    resource_config: ResourceExecutionConfig = field(default_factory=ResourceExecutionConfig)
    requested_sample: dict[str, Any] = field(default_factory=dict)
    executed_sample: dict[str, Any] = field(default_factory=dict)
    requested_universe: str = ""
    executed_universe: str = ""
    methodological_deviations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvaluationExecutionRecord:
    execution_id: str
    truth_case_id: str
    source_truth_id: str
    factor_id: str
    factor_name: str
    scenario_id: str
    evaluator_id: str
    lifecycle_state: str
    implementation_source_hash: str
    factor_specification_hash: str
    data_snapshot_hash: str
    resolved_protocol: dict[str, Any] = field(default_factory=dict)
    comparability: str = "exact"
    truth_match_eligible_metrics: list[str] = field(default_factory=list)
    diagnostic_only_metrics: list[str] = field(default_factory=list)
    alignment_diagnostics: dict[str, Any] = field(default_factory=dict)
    universe_diagnostics: dict[str, Any] = field(default_factory=dict)
    scoring_sample_diagnostics: dict[str, Any] = field(default_factory=dict)
    evaluator_output: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    error: dict[str, str] | None = None
    schema_version: str = "evaluation_execution_record/v1"


@dataclass(slots=True)
class EvaluationBundle:
    library: str
    scenario_id: str
    data_snapshot_hash: str
    implementation_artifact: dict[str, Any]
    records: list[EvaluationExecutionRecord]
    limitations: list[str] = field(default_factory=list)
    resource_preflight: dict[str, Any] = field(default_factory=dict)
    resource_telemetry: dict[str, Any] = field(default_factory=dict)
    resource_adaptations: list[str] = field(default_factory=list)
    methodological_deviations: list[str] = field(default_factory=list)
    requested_execution: dict[str, Any] = field(default_factory=dict)
    executed_execution: dict[str, Any] = field(default_factory=dict)
    raw_factor_before_evaluation_filters: bool = True
    schema_version: str = "evaluation_bundle/v2"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def execute_evaluation_plan(
    plan: PaperEvaluationPlan,
    implementation_artifact: FactorImplementationArtifact,
    data_context: EvaluationDataContext,
) -> EvaluationBundle:
    """Execute selected cases through the artifact callable without mutating pipeline state."""

    if implementation_artifact.validation_status not in {"completed", "completed_with_limitations"}:
        raise ValueError("implementation artifact must be probe-validated before canonical evaluation")
    missing_inputs = [
        column
        for column in implementation_artifact.required_input_columns
        if column not in data_context.calculation_panel.columns
    ]
    if missing_inputs:
        raise ValueError(f"calculation panel is missing implementation inputs: {missing_inputs}")

    shared_panel = data_context.evaluation_inputs is None
    evaluation_source = data_context.calculation_panel if shared_panel else data_context.evaluation_inputs
    assert evaluation_source is not None
    colliding_factor_columns = [
        column for column in implementation_artifact.output_factor_columns if column in evaluation_source.columns
    ]
    if colliding_factor_columns:
        raise ValueError(
            "evaluation inputs must not contain artifact factor columns: "
            f"{colliding_factor_columns}"
        )
    calculation_columns = list(
        dict.fromkeys(
            [
                *implementation_artifact.output_key_columns,
                *implementation_artifact.required_input_columns,
            ]
        )
    )
    evaluation_columns = _evaluation_projection_columns(plan, implementation_artifact)
    selected_case_count = sum(len(factor_plan.selected_evaluation_cases) for factor_plan in plan.factor_plans)
    preflight = estimate_resource_preflight(
        data_context.calculation_panel,
        evaluation_source,
        calculation_columns=calculation_columns,
        evaluation_columns=evaluation_columns,
        factor_output_columns=implementation_artifact.output_factor_columns,
        selected_case_count=selected_case_count,
        config=data_context.resource_config,
        methodological_deviations=data_context.methodological_deviations,
    )
    if preflight.partition_required:
        raise ResourceBudgetExceededError(preflight)

    calculation_panel = data_context.calculation_panel.loc[:, preflight.calculation_columns].copy()
    evaluation_inputs = evaluation_source.loc[:, preflight.evaluation_columns].copy(deep=False)
    context_limitations: list[str] = []
    if shared_panel:
        context_limitations.append(
            "calculation and evaluation panels were not separately supplied; one logical base panel is reused and evaluation eligibility is still applied after factor calculation"
        )
    context_limitations.extend(preflight.limitations)
    snapshot_hash = data_context.data_snapshot_hash or _data_context_hash(
        calculation_panel,
        evaluation_inputs,
        hash_chunk_rows=data_context.resource_config.hash_chunk_rows,
        source_identity=data_context.source_identity,
    )

    factor_frame = execute_factor_callable(implementation_artifact, calculation_panel, copy_input=False)
    factor_validation = validate_factor_frame(
        factor_frame,
        key_columns=implementation_artifact.output_key_columns,
        factor_columns=implementation_artifact.output_factor_columns,
    )
    if not factor_validation.valid:
        raise ValueError("invalid artifact FactorFrame: " + "; ".join(factor_validation.errors))
    alignment = align_factor_frame(
        evaluation_inputs,
        factor_frame,
        key_columns=implementation_artifact.output_key_columns,
        factor_columns=implementation_artifact.output_factor_columns,
    )
    if not alignment.valid or alignment.aligned_frame is None:
        raise ValueError("ambiguous FactorFrame alignment: " + "; ".join(alignment.errors))
    aligned_frame = alignment.aligned_frame
    resource_adaptations = list(preflight.resource_adaptations)
    if alignment.diagnostics.get("alignment_method") == "verified_positional_fast_path":
        resource_adaptations.append("verified positional factor alignment avoided a key merge")
    else:
        resource_adaptations.append("one-to-one left key join avoided a separate full outer key merge")

    records: list[EvaluationExecutionRecord] = []
    scored_samples: list[dict[str, Any]] = []
    for factor_plan in plan.factor_plans:
        factor_id, factor_column = _resolve_factor_identity(implementation_artifact, factor_plan.factor_name)
        for case in factor_plan.selected_evaluation_cases:
            truth_case_id = str(
                case.get("truth_case_id") or case.get("case_id") or case.get("truth_id") or case.get("source_truth_id") or ""
            )
            source_truth_id = str(case.get("source_truth_id") or case.get("truth_id") or truth_case_id)
            descriptor = evaluator_capabilities_for_case(case) or {}
            evaluator_id = str(descriptor.get("evaluator_id", "unregistered"))
            resolved_protocol = dict(case.get("resolved_protocol", {}) or {})
            comparability = str(case.get("comparability", "exact") or "exact")
            eligible_metrics = list(case.get("truth_match_eligible_metrics", []) or [])
            diagnostic_only_metrics = list(case.get("diagnostic_only_metrics", []) or [])
            universe_protocol = dict(
                resolved_protocol.get("universe_protocol", {}) or case.get("universe_protocol", {}) or {}
            )
            projected_case_columns = _case_projection_columns(
                case,
                factor_column=factor_column,
                key_columns=implementation_artifact.output_key_columns,
            )
            case_input = aligned_frame.loc[
                :,
                [column for column in projected_case_columns if column in aligned_frame.columns],
            ].copy(deep=False)
            case_input, scoring_sample_diagnostics = _clip_to_scoring_sample(
                case_input,
                case,
            )
            universe_application = apply_universe_protocol(
                case_input,
                universe_protocol,
                stage=_evaluation_filter_stage(case),
            )
            case_frame = universe_application.frame
            universe_diagnostics = {
                **universe_application.diagnostics,
                "stage": universe_application.stage,
                "applied_filters": universe_application.applied_filters,
                "skipped_filters": universe_application.skipped_filters,
            }
            scoring_sample_diagnostics["after_universe"] = _frame_sample(case_frame)
            scoring_sample_diagnostics["rows_removed_by_universe"] = int(
                len(case_input) - len(case_frame)
            )
            scored_samples.append(
                {
                    "truth_case_id": truth_case_id,
                    "execution_sample": _frame_sample(case_frame),
                    "declared_sample": scoring_sample_diagnostics.get("declared_sample", {}),
                }
            )
            record_limitations = [
                *context_limitations,
                *alignment.limitations,
                *universe_application.limitations,
            ]
            identity = {
                "truth_case_id": truth_case_id,
                "factor_id": factor_id,
                "scenario_id": data_context.scenario_id,
                "evaluator_id": evaluator_id,
                "implementation_source_hash": implementation_artifact.source_hash,
                "factor_specification_hash": implementation_artifact.factor_specification_hash,
                "data_snapshot_hash": snapshot_hash,
                "resolved_protocol": resolved_protocol,
            }
            execution_id = _stable_execution_id(identity)
            missing_case_columns = _missing_runtime_columns(case, case_frame)
            if missing_case_columns:
                records.append(
                    EvaluationExecutionRecord(
                        execution_id=execution_id,
                        truth_case_id=truth_case_id,
                        source_truth_id=source_truth_id,
                        factor_id=factor_id,
                        factor_name=factor_plan.factor_name,
                        scenario_id=data_context.scenario_id,
                        evaluator_id=evaluator_id,
                        lifecycle_state="insufficient_data",
                        implementation_source_hash=implementation_artifact.source_hash,
                        factor_specification_hash=implementation_artifact.factor_specification_hash,
                        data_snapshot_hash=snapshot_hash,
                        resolved_protocol=resolved_protocol,
                        comparability=comparability,
                        truth_match_eligible_metrics=eligible_metrics,
                        diagnostic_only_metrics=diagnostic_only_metrics,
                        alignment_diagnostics=dict(alignment.diagnostics),
                        universe_diagnostics=universe_diagnostics,
                        scoring_sample_diagnostics=scoring_sample_diagnostics,
                        limitations=record_limitations,
                        error={
                            "type": "MissingEvaluationInputs",
                            "message": f"missing evaluation columns: {missing_case_columns}",
                        },
                    )
                )
                continue
            try:
                evaluator_output = evaluate_paper_case(case, case_frame, factor_col=factor_column)
            except NotImplementedError as exc:
                lifecycle = "unsupported_evaluator"
                error = {"type": type(exc).__name__, "message": str(exc)}
                evaluator_output = {}
            except Exception as exc:  # isolate one case without hiding the structured error
                lifecycle = "evaluation_error"
                error = {"type": type(exc).__name__, "message": str(exc)}
                evaluator_output = {}
            else:
                lifecycle = "executed"
                error = None
                evaluator_output = dict(evaluator_output)
                evaluator_output["execution_mode"] = "canonical_plan_executor"
                evaluator_id = str(evaluator_output.get("evaluator_id", evaluator_id))
                skipped_controls = (
                    evaluator_output.get("neutralization_diagnostics", {}).get("skipped_controls", [])
                    if isinstance(evaluator_output.get("neutralization_diagnostics", {}), dict)
                    else []
                )
                for control in skipped_controls:
                    if not isinstance(control, dict):
                        continue
                    control_name = str(control.get("paper_field") or control.get("field") or "unknown_control")
                    record_limitations.append(
                        f"neutralization control {control_name} was not applied because its runtime field is unavailable"
                    )
            records.append(
                EvaluationExecutionRecord(
                    execution_id=execution_id,
                    truth_case_id=truth_case_id,
                    source_truth_id=source_truth_id,
                    factor_id=factor_id,
                    factor_name=factor_plan.factor_name,
                    scenario_id=data_context.scenario_id,
                    evaluator_id=evaluator_id,
                    lifecycle_state=lifecycle,
                    implementation_source_hash=implementation_artifact.source_hash,
                    factor_specification_hash=implementation_artifact.factor_specification_hash,
                    data_snapshot_hash=snapshot_hash,
                    resolved_protocol=resolved_protocol,
                    comparability=comparability,
                    truth_match_eligible_metrics=eligible_metrics,
                    diagnostic_only_metrics=diagnostic_only_metrics,
                    alignment_diagnostics=dict(alignment.diagnostics),
                    universe_diagnostics=universe_diagnostics,
                    scoring_sample_diagnostics=scoring_sample_diagnostics,
                    evaluator_output=evaluator_output,
                    limitations=record_limitations,
                    error=error,
                )
            )

    return EvaluationBundle(
        library=plan.library,
        scenario_id=data_context.scenario_id,
        data_snapshot_hash=snapshot_hash,
        implementation_artifact=_artifact_identity(implementation_artifact),
        records=records,
        limitations=context_limitations,
        resource_preflight=preflight.to_dict(),
        resource_telemetry={
            "measured_process_peak_rss_bytes": process_peak_rss_bytes(),
            "calculation_rows": len(calculation_panel),
            "evaluation_rows": len(evaluation_inputs),
            "scored_signal_rows": sum(
                int(item["execution_sample"].get("row_count", 0)) for item in scored_samples
            ),
            "factor_rows": len(factor_frame),
            "active_scenario_count": 1,
        },
        resource_adaptations=resource_adaptations,
        methodological_deviations=list(data_context.methodological_deviations),
        requested_execution={
            "sample": data_context.requested_sample or _frame_sample(evaluation_source),
            "samples_by_case": scored_samples,
            "universe": data_context.requested_universe or "as_declared_by_selected_evaluation_cases",
            "scenario_id": data_context.scenario_id,
        },
        executed_execution={
            "sample": _aggregate_scored_samples(scored_samples),
            "samples_by_case": scored_samples,
            "context_declared_sample": dict(data_context.executed_sample),
            "universe": data_context.executed_universe or "resolved_evaluation_universe",
            "scenario_id": data_context.scenario_id,
            "execution_mode": preflight.execution_mode,
        },
    )


def export_evaluation_bundle(bundle: EvaluationBundle, path: str | Path) -> Path:
    """Persist a complete scenario bundle so interrupted runs can resume safely."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def load_evaluation_bundle(path: str | Path) -> EvaluationBundle:
    """Reload a persisted scenario bundle without discarding successful records."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("evaluation bundle JSON must contain an object")
    records = [EvaluationExecutionRecord(**record) for record in payload.get("records", []) or []]
    fields = {
        "library": str(payload.get("library", "")),
        "scenario_id": str(payload.get("scenario_id", "")),
        "data_snapshot_hash": str(payload.get("data_snapshot_hash", "")),
        "implementation_artifact": dict(payload.get("implementation_artifact", {}) or {}),
        "records": records,
        "limitations": list(payload.get("limitations", []) or []),
        "resource_preflight": dict(payload.get("resource_preflight", {}) or {}),
        "resource_telemetry": dict(payload.get("resource_telemetry", {}) or {}),
        "resource_adaptations": list(payload.get("resource_adaptations", []) or []),
        "methodological_deviations": list(payload.get("methodological_deviations", []) or []),
        "requested_execution": dict(payload.get("requested_execution", {}) or {}),
        "executed_execution": dict(payload.get("executed_execution", {}) or {}),
        "raw_factor_before_evaluation_filters": bool(payload.get("raw_factor_before_evaluation_filters", True)),
        "schema_version": str(payload.get("schema_version", "evaluation_bundle/v2")),
    }
    return EvaluationBundle(**fields)


def merge_evaluation_bundles(
    bundles: list[EvaluationBundle],
    *,
    scenario_id: str = "combined_scenarios",
) -> EvaluationBundle:
    """Combine independently persisted scenarios for reporting and truth matching."""

    if not bundles:
        raise ValueError("At least one evaluation bundle is required.")
    library = bundles[0].library
    artifact = bundles[0].implementation_artifact
    for bundle in bundles[1:]:
        if bundle.library != library:
            raise ValueError("Cannot merge evaluation bundles from different libraries.")
        if bundle.implementation_artifact != artifact:
            raise ValueError("Cannot merge evaluation bundles from different implementation artifacts.")
    records: list[EvaluationExecutionRecord] = []
    seen: set[tuple[str, str]] = set()
    for bundle in bundles:
        for record in bundle.records:
            identity = (record.scenario_id, record.execution_id)
            if identity in seen:
                continue
            seen.add(identity)
            records.append(record)
    combined_hash = hashlib.sha256(
        "\0".join(bundle.data_snapshot_hash for bundle in bundles).encode("utf-8")
    ).hexdigest()
    return EvaluationBundle(
        library=library,
        scenario_id=scenario_id,
        data_snapshot_hash=combined_hash,
        implementation_artifact=dict(artifact),
        records=records,
        limitations=_unique_strings(item for bundle in bundles for item in bundle.limitations),
        resource_preflight={bundle.scenario_id: bundle.resource_preflight for bundle in bundles},
        resource_telemetry={bundle.scenario_id: bundle.resource_telemetry for bundle in bundles},
        resource_adaptations=_unique_strings(
            item for bundle in bundles for item in bundle.resource_adaptations
        ),
        methodological_deviations=_unique_strings(
            item for bundle in bundles for item in bundle.methodological_deviations
        ),
        requested_execution={bundle.scenario_id: bundle.requested_execution for bundle in bundles},
        executed_execution={bundle.scenario_id: bundle.executed_execution for bundle in bundles},
        raw_factor_before_evaluation_filters=all(
            bundle.raw_factor_before_evaluation_filters for bundle in bundles
        ),
    )


def _unique_strings(values: Any) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def _resolve_factor_identity(artifact: FactorImplementationArtifact, factor_name: str) -> tuple[str, str]:
    exact_id = artifact.factor_columns_by_id.get(factor_name)
    if exact_id:
        return factor_name, exact_id
    matches = [
        (factor_id, column)
        for factor_id, column in artifact.factor_columns_by_id.items()
        if column == factor_name
    ]
    if len(matches) != 1:
        raise ValueError(f"evaluation plan factor is not uniquely declared by the implementation artifact: {factor_name}")
    return matches[0]


def _missing_runtime_columns(case: dict[str, Any], frame: pd.DataFrame) -> list[str]:
    runtime = dict(case.get("resolved_protocol", {}) or case)
    evaluation_spec = dict(runtime.get("evaluation_spec", {}) or {})
    required_data = dict(runtime.get("required_data", {}) or {})
    required: list[str] = []
    return_col = str(evaluation_spec.get("return_col", "") or "")
    if not return_col:
        evaluation_values = required_data.get("evaluation", []) or []
        return_col = str(evaluation_values[0]) if evaluation_values else "forward_return_1d"
    required.append(return_col)
    required.extend(str(value) for value in evaluation_spec.get("regression_controls", []) or [])
    if str(evaluation_spec.get("regression_type", "")).lower() == "wls" and evaluation_spec.get("weight_col"):
        required.append(str(evaluation_spec["weight_col"]))
    transform_spec = dict(runtime.get("transform_spec", {}) or {})
    for step in transform_spec.get("steps", []) or []:
        if isinstance(step, dict) and str(step.get("name", "")).lower() == "neutralization":
            required.extend(str(value) for value in step.get("controls", []) or [])
    return sorted({column for column in required if column and column not in frame.columns})


def _evaluation_filter_stage(case: dict[str, Any]) -> str:
    runtime = dict(case.get("resolved_protocol", {}) or case)
    family = str(runtime.get("evaluation_family", "") or "")
    if family in {"ic_analysis", "ic_regression"}:
        return "factor_cross_section"
    if family == "layered_portfolio_backtest":
        return "portfolio_formation"
    return "factor_cross_section"


def _evaluation_projection_columns(
    plan: PaperEvaluationPlan,
    artifact: FactorImplementationArtifact,
) -> list[str]:
    columns = list(artifact.output_key_columns)
    for factor_plan in plan.factor_plans:
        for case in factor_plan.selected_evaluation_cases:
            columns.extend(_runtime_input_columns(case))
    return list(dict.fromkeys(columns))


def _case_projection_columns(
    case: dict[str, Any],
    *,
    factor_column: str,
    key_columns: list[str],
) -> list[str]:
    return list(dict.fromkeys([*key_columns, factor_column, *_runtime_input_columns(case)]))


def _runtime_input_columns(case: dict[str, Any]) -> list[str]:
    runtime = dict(case.get("resolved_protocol", {}) or case)
    evaluation_spec = dict(runtime.get("evaluation_spec", {}) or {})
    required_data = dict(runtime.get("required_data", {}) or {})
    columns: list[str] = []
    return_col = str(evaluation_spec.get("return_col", "") or "")
    if return_col:
        columns.append(return_col)
    else:
        evaluation_values = _string_values(required_data.get("evaluation", []))
        columns.append(evaluation_values[0] if evaluation_values else "forward_return_1d")
    columns.extend(_string_values(evaluation_spec.get("regression_controls", [])))
    columns.extend(_string_values(evaluation_spec.get("weight_col")))
    for category, values in required_data.items():
        if str(category) != "formula":
            columns.extend(_string_values(values))

    transform_spec = dict(runtime.get("transform_spec", {}) or {})
    for step in transform_spec.get("steps", []) or []:
        if isinstance(step, dict) and str(step.get("name", "")).lower() == "neutralization":
            columns.extend(_string_values(step.get("controls", [])))

    neutralization_spec = dict(runtime.get("neutralization_spec", {}) or {})
    for control in neutralization_spec.get("controls", []) or []:
        if isinstance(control, dict):
            columns.extend(
                _string_values(control.get("resolved_field") or control.get("field"))
            )

    universe_protocol = dict(runtime.get("universe_protocol", {}) or {})
    for item in universe_protocol.get("filters", []) or []:
        if isinstance(item, dict):
            columns.extend(_string_values(item.get("resolved_field") or item.get("field")))
    return list(dict.fromkeys(column for column in columns if column))


def _string_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, dict):
        return [str(item) for item in value.values() if isinstance(item, str) and item]
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item:
                result.append(item)
            elif isinstance(item, dict):
                result.extend(_string_values(item.get("resolved_field") or item.get("field")))
        return result
    return []


def _frame_sample(frame: pd.DataFrame) -> dict[str, Any]:
    date_column = next(
        (column for column in frame.columns if column.lower() in {"date", "datetime", "trade_date"}),
        None,
    )
    if date_column is None or frame.empty:
        return {"row_count": len(frame)}
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    return {
        "start_date": dates.min().isoformat() if dates.notna().any() else None,
        "end_date": dates.max().isoformat() if dates.notna().any() else None,
        "row_count": len(frame),
    }


def _clip_to_scoring_sample(
    frame: pd.DataFrame,
    case: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    declared = _declared_scoring_sample(case)
    diagnostics: dict[str, Any] = {
        "declared_sample": declared,
        "before_clip": _frame_sample(frame),
        "clip_applied": False,
        "rows_removed_before_start": 0,
        "rows_removed_after_end": 0,
        "rows_removed_invalid_date": 0,
        "calculation_history_preserved": True,
        "label_history_preserved": True,
    }
    start = declared.get("resolved_start_date")
    end = declared.get("resolved_end_date")
    if start is None and end is None:
        diagnostics["after_clip"] = _frame_sample(frame)
        return frame, diagnostics

    date_column = next(
        (column for column in frame.columns if column.lower() in {"date", "datetime", "trade_date"}),
        None,
    )
    if date_column is None:
        raise ValueError("declared evaluation sample cannot be enforced without a date column")
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    mask = dates.notna()
    diagnostics["rows_removed_invalid_date"] = int(dates.isna().sum())
    if start is not None:
        start_ts = pd.Timestamp(start)
        diagnostics["rows_removed_before_start"] = int((dates < start_ts).fillna(False).sum())
        mask &= dates >= start_ts
    if end is not None:
        end_ts = pd.Timestamp(end)
        diagnostics["rows_removed_after_end"] = int((dates > end_ts).fillna(False).sum())
        mask &= dates <= end_ts
    clipped = frame.loc[mask].copy(deep=False)
    diagnostics["clip_applied"] = True
    diagnostics["date_column"] = date_column
    diagnostics["after_clip"] = _frame_sample(clipped)
    return clipped, diagnostics


def _declared_scoring_sample(case: dict[str, Any]) -> dict[str, Any]:
    runtime = dict(case.get("resolved_protocol", {}) or {})
    evaluation_spec = dict(runtime.get("evaluation_spec", {}) or {})
    paper_protocol = dict(case.get("paper_protocol", {}) or {})
    requested_value = paper_protocol.get("sample_period") or case.get("sample_period") or ""
    resolved_value = runtime.get("sample_period") or requested_value

    explicit_start = (
        evaluation_spec.get("sample_start_date")
        or evaluation_spec.get("evaluation_start_date")
        or evaluation_spec.get("start_date")
    )
    explicit_end = (
        evaluation_spec.get("sample_end_date")
        or evaluation_spec.get("evaluation_end_date")
        or evaluation_spec.get("end_date")
    )
    if explicit_start or explicit_end:
        resolved_start = _period_endpoint(explicit_start, end=False)
        resolved_end = _period_endpoint(explicit_end, end=True)
        source = "resolved_protocol.evaluation_spec"
    else:
        resolved_start, resolved_end = _period_bounds(resolved_value)
        source = "resolved_protocol.sample_period" if runtime.get("sample_period") else "paper_sample_period"
    requested_start, requested_end = _period_bounds(requested_value)
    return {
        "source": source,
        "requested_value": requested_value,
        "resolved_value": resolved_value,
        "requested_start_date": requested_start,
        "requested_end_date": requested_end,
        "resolved_start_date": resolved_start,
        "resolved_end_date": resolved_end,
    }


def _period_bounds(value: Any) -> tuple[str | None, str | None]:
    if isinstance(value, dict):
        start = value.get("start_date") or value.get("start")
        end = value.get("end_date") or value.get("end")
        return _period_endpoint(start, end=False), _period_endpoint(end, end=True)
    tokens = re.findall(r"\d{4}(?:[-/.]\d{1,2}(?:[-/.]\d{1,2})?)?", str(value or ""))
    if not tokens:
        return None, None
    return (
        _period_endpoint(tokens[0], end=False),
        _period_endpoint(tokens[-1], end=True),
    )


def _period_endpoint(value: Any, *, end: bool) -> str | None:
    text = str(value or "").strip().replace("/", "-").replace(".", "-")
    if not text:
        return None
    parts = text.split("-")
    try:
        if len(parts) == 1:
            timestamp = pd.Timestamp(f"{parts[0]}-12-31" if end else f"{parts[0]}-01-01")
        elif len(parts) == 2:
            period = pd.Period(f"{int(parts[0]):04d}-{int(parts[1]):02d}", freq="M")
            timestamp = period.end_time.normalize() if end else period.start_time.normalize()
        else:
            timestamp = pd.Timestamp(text)
    except (TypeError, ValueError):
        return None
    return timestamp.isoformat()


def _aggregate_scored_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    execution_samples = [
        dict(item.get("execution_sample", {}) or {})
        for item in samples
        if isinstance(item, dict)
    ]
    if not execution_samples:
        return {"row_count": 0, "case_count": 0}
    if len(execution_samples) == 1:
        return {**execution_samples[0], "case_count": 1}
    starts = [item.get("start_date") for item in execution_samples if item.get("start_date")]
    ends = [item.get("end_date") for item in execution_samples if item.get("end_date")]
    return {
        "start_date": min(starts) if starts else None,
        "end_date": max(ends) if ends else None,
        "row_count": sum(int(item.get("row_count", 0)) for item in execution_samples),
        "case_count": len(execution_samples),
        "row_count_semantics": "sum_across_evaluation_cases",
    }


def _frame_identity_summary(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "columns": list(frame.columns),
        "dtypes": [str(dtype) for dtype in frame.dtypes],
        "sample": _frame_sample(frame),
    }


def _data_context_hash(
    calculation_panel: pd.DataFrame,
    evaluation_inputs: pd.DataFrame,
    *,
    hash_chunk_rows: int,
    source_identity: dict[str, Any],
) -> str:
    if source_identity:
        identity = {
            "source_identity": source_identity,
            "calculation_schema": _frame_identity_summary(calculation_panel),
            "evaluation_schema": _frame_identity_summary(evaluation_inputs),
        }
        return incremental_data_hash([], chunk_rows=hash_chunk_rows, source_identity=identity)
    return incremental_data_hash(
        [("calculation", calculation_panel), ("evaluation", evaluation_inputs)],
        chunk_rows=hash_chunk_rows,
    )


def _stable_execution_id(identity: dict[str, Any]) -> str:
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"execution-{hashlib.sha256(encoded).hexdigest()[:20]}"


def _artifact_identity(artifact: FactorImplementationArtifact) -> dict[str, Any]:
    return {
        "schema_version": artifact.schema_version,
        "module_path": artifact.module_path,
        "callable_import_path": artifact.callable_import_path,
        "implemented_factor_ids": list(artifact.implemented_factor_ids),
        "factor_columns_by_id": dict(artifact.factor_columns_by_id),
        "source_hash": artifact.source_hash,
        "factor_specification_hash": artifact.factor_specification_hash,
        "validation_status": artifact.validation_status,
    }
