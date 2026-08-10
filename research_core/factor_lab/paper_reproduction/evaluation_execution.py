from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
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


@dataclass(slots=True)
class EvaluationDataContext:
    """Separate factor-calculation history from possibly filtered evaluation inputs."""

    calculation_panel: pd.DataFrame = field(repr=False)
    evaluation_inputs: pd.DataFrame | None = field(default=None, repr=False)
    scenario_id: str = "base"
    data_snapshot_hash: str = ""


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
    alignment_diagnostics: dict[str, Any] = field(default_factory=dict)
    universe_diagnostics: dict[str, Any] = field(default_factory=dict)
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
    schema_version: str = "evaluation_bundle/v1"

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
    evaluation_inputs = (
        data_context.calculation_panel.copy()
        if shared_panel
        else data_context.evaluation_inputs.copy()
    )
    context_limitations: list[str] = []
    if shared_panel:
        context_limitations.append(
            "calculation and evaluation panels were not separately supplied; calculation_panel was also used as evaluation_inputs"
        )
    snapshot_hash = data_context.data_snapshot_hash or _data_context_hash(
        data_context.calculation_panel,
        evaluation_inputs,
        key_columns=implementation_artifact.output_key_columns,
    )

    factor_frame = execute_factor_callable(implementation_artifact, data_context.calculation_panel)
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

    records: list[EvaluationExecutionRecord] = []
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
            universe_protocol = dict(
                resolved_protocol.get("universe_protocol", {}) or case.get("universe_protocol", {}) or {}
            )
            universe_application = apply_universe_protocol(
                aligned_frame,
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
                        alignment_diagnostics=dict(alignment.diagnostics),
                        universe_diagnostics=universe_diagnostics,
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
                    alignment_diagnostics=dict(alignment.diagnostics),
                    universe_diagnostics=universe_diagnostics,
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
    )


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


def _data_context_hash(
    calculation_panel: pd.DataFrame,
    evaluation_inputs: pd.DataFrame,
    *,
    key_columns: list[str],
) -> str:
    digest = hashlib.sha256()
    for label, frame in (("calculation", calculation_panel), ("evaluation", evaluation_inputs)):
        ordered = frame.copy()
        if all(column in ordered.columns for column in key_columns):
            ordered = ordered.sort_values(key_columns, kind="stable").reset_index(drop=True)
        digest.update(label.encode("utf-8"))
        digest.update(json.dumps(list(ordered.columns), ensure_ascii=False).encode("utf-8"))
        digest.update(json.dumps([str(dtype) for dtype in ordered.dtypes]).encode("utf-8"))
        digest.update(pd.util.hash_pandas_object(ordered, index=False, categorize=True).values.tobytes())
    return digest.hexdigest()


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
