from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from research_core.factor_lab.paper_reproduction.extraction import ICAnalysisPaperExtraction, PaperExtraction
from research_core.factor_lab.runtime import FactorLabWorkspaceConfig, now_iso


class PaperReproductionStage(str, Enum):
    PAPER_EXTRACTION = "paper_extraction"
    SPEC_NORMALIZATION = "spec_normalization"
    INPUT_DATAFRAME_VALIDATION = "input_dataframe_validation"
    FACTOR_IMPLEMENTATION = "factor_implementation"
    IMPLEMENTATION_TESTS = "implementation_tests"
    EVALUATION = "evaluation"
    PAPER_TRUTH_VALIDATION = "paper_truth_validation"
    FINAL_REPORT = "final_report"


EXECUTION_STATUSES = {"pending", "running", "completed", "completed_with_limitations", "failed"}
TRUTH_VALIDATION_STATUSES = {
    "exact_match",
    "approximately_consistent",
    "directionally_consistent",
    "inconclusive_due_to_protocol_gap",
    "inconsistent",
    "not_evaluated",
}
HARD_GATING_EXECUTION_STATUSES = {"pending", "running", "failed"}
HARD_GATING_LEGACY_STATUSES = {"pending", "failed", "blocked_by_data"}


@dataclass(slots=True)
class PaperReproductionStageState:
    name: str
    status: str = "pending"
    execution_status: str = "pending"
    truth_validation_status: str = "not_evaluated"
    summary: str = ""
    artifact_paths: list[str] = field(default_factory=list)
    diagnostics: dict[str, object] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    updated_at: str = ""


@dataclass(slots=True)
class StageExecutionDecision:
    allowed: bool
    hard_blockers: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    deferred_dependencies: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PaperReproductionPipelineState:
    job_id: str
    paper_id: str
    family_name: str
    stages: list[PaperReproductionStageState]
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_extraction(
        cls,
        extraction: PaperExtraction | ICAnalysisPaperExtraction,
        *,
        job_id: str | None = None,
    ) -> PaperReproductionPipelineState:
        paper_id = (
            extraction.paper_id
            if isinstance(extraction, PaperExtraction)
            else str(extraction.paper.get("paper_id") or extraction.artifact_id)
        )
        return cls(
            job_id=job_id or f"paper-{uuid4().hex[:12]}",
            paper_id=paper_id,
            family_name=extraction.factor_family_name,
            stages=[PaperReproductionStageState(name=stage.value) for stage in PaperReproductionStage],
        )

    @property
    def overall_status(self) -> str:
        statuses = [stage.status for stage in self.stages]
        execution_statuses = [stage.execution_status or _legacy_execution_status(stage.status) for stage in self.stages]
        truth_statuses = [stage.truth_validation_status for stage in self.stages]
        if any(status == "failed" for status in execution_statuses):
            return "failed"
        if "inconsistent" in truth_statuses:
            return "truth_inconsistent"
        if any(status in {"inconclusive_due_to_protocol_gap", "not_evaluated"} for status in truth_statuses):
            if all(status in {"completed", "completed_with_limitations"} for status in execution_statuses):
                return "completed_with_limitations"
        if all(status == "completed" for status in execution_statuses):
            return "passed"
        if all(status in {"completed", "completed_with_limitations"} for status in execution_statuses):
            return "completed_with_limitations"
        if any(status in {"completed", "completed_with_limitations"} for status in execution_statuses):
            return "in_progress"
        if any(status == "needs_human_review" for status in statuses):
            return "needs_human_review"
        return "pending"

    @property
    def next_stage(self) -> str:
        for stage in self.stages:
            if stage.status == "pending":
                return stage.name
        return "complete"

    def mark_stage(
        self,
        stage_name: str,
        status: str,
        *,
        execution_status: str | None = None,
        truth_validation_status: str | None = None,
        summary: str = "",
        artifact_paths: list[str] | None = None,
        diagnostics: dict[str, object] | None = None,
        limitations: list[str] | None = None,
    ) -> None:
        stage = self._stage(stage_name)
        stage.status = status
        stage.execution_status = execution_status or _legacy_execution_status(status)
        stage.truth_validation_status = truth_validation_status or stage.truth_validation_status
        stage.summary = summary
        stage.artifact_paths = _merge_unique(stage.artifact_paths, artifact_paths or [])
        stage.diagnostics = {**stage.diagnostics, **(diagnostics or {})}
        stage.limitations = _merge_unique(stage.limitations, limitations or [])
        stage.updated_at = now_iso()
        self.updated_at = stage.updated_at

    def ready_for_stage(self, stage_name: str) -> bool:
        return self.execution_decision(stage_name).allowed

    def execution_decision(self, stage_name: str) -> StageExecutionDecision:
        blockers: list[str] = []
        limitations: list[str] = []
        deferred: list[str] = []
        for stage in self.stages:
            if stage.name == stage_name:
                return StageExecutionDecision(
                    allowed=not blockers,
                    hard_blockers=blockers,
                    limitations=limitations,
                    deferred_dependencies=deferred,
                )
            execution_status = stage.execution_status or _legacy_execution_status(stage.status)
            if execution_status in HARD_GATING_EXECUTION_STATUSES or stage.status in HARD_GATING_LEGACY_STATUSES:
                blockers.append(f"{stage.name}: {stage.summary or execution_status}")
            elif execution_status == "completed_with_limitations" or stage.limitations:
                limitations.extend(f"{stage.name}: {item}" for item in stage.limitations)
                if not stage.limitations:
                    limitations.append(f"{stage.name}: completed with limitations")
            if stage.status == "needs_human_review":
                deferred.append(stage.name)
        raise KeyError(f"Unknown paper reproduction stage: {stage_name}")

    def _stage(self, stage_name: str) -> PaperReproductionStageState:
        for stage in self.stages:
            if stage.name == stage_name:
                return stage
        raise KeyError(f"Unknown paper reproduction stage: {stage_name}")


def export_pipeline_state(
    state: PaperReproductionPipelineState,
    *,
    config: FactorLabWorkspaceConfig | None = None,
) -> Path:
    workspace = config or FactorLabWorkspaceConfig()
    workspace.ensure_directories()
    output_dir = workspace.runtime_root / "paper_jobs"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{state.job_id}.json"
    payload = asdict(state)
    payload["overall_status"] = state.overall_status
    payload["next_stage"] = state.next_stage
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def record_stage3_support_assessments(
    state: PaperReproductionPipelineState,
    evaluation_plan: Any,
) -> dict[str, dict[str, str]]:
    """Record authoritative support-assessment identities in durable Stage-3 state."""

    identities: dict[str, dict[str, str]] = {}
    for factor_plan in getattr(evaluation_plan, "factor_plans", []) or []:
        factor_name = str(getattr(factor_plan, "factor_name", "") or "")
        factor_identities: dict[str, str] = {}
        for case in getattr(factor_plan, "assessed_evaluation_cases", []) or []:
            if not isinstance(case, dict):
                continue
            truth_id = str(case.get("truth_id") or case.get("truth_case_id") or "")
            assessment = dict(case.get("support_assessment", {}) or {})
            assessment_id = str(assessment.get("assessment_id", "") or "")
            if truth_id and assessment_id:
                factor_identities[truth_id] = assessment_id
        if factor_name and factor_identities:
            identities[factor_name] = factor_identities
    state.mark_stage(
        PaperReproductionStage.INPUT_DATAFRAME_VALIDATION.value,
        "completed",
        diagnostics={
            "support_assessment_ids": identities,
            "support_assessment_authority": "stage_3_persisted",
        },
    )
    return identities


def load_pipeline_state(
    job_id: str,
    *,
    config: FactorLabWorkspaceConfig | None = None,
) -> PaperReproductionPipelineState:
    workspace = config or FactorLabWorkspaceConfig()
    path = workspace.runtime_root / "paper_jobs" / f"{job_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    stages = [
        PaperReproductionStageState(
            name=str(stage.get("name", "")),
            status=str(stage.get("status", "pending")),
            execution_status=str(stage.get("execution_status") or _legacy_execution_status(str(stage.get("status", "pending")))),
            truth_validation_status=str(stage.get("truth_validation_status", "not_evaluated")),
            summary=str(stage.get("summary", "")),
            artifact_paths=list(stage.get("artifact_paths", []) or []),
            diagnostics=dict(stage.get("diagnostics", {}) or {}),
            limitations=list(stage.get("limitations", []) or []),
            updated_at=str(stage.get("updated_at", "")),
        )
        for stage in payload.get("stages", [])
    ]
    return PaperReproductionPipelineState(
        job_id=str(payload["job_id"]),
        paper_id=str(payload["paper_id"]),
        family_name=str(payload["family_name"]),
        stages=stages,
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
        notes=list(payload.get("notes", []) or []),
    )


def merge_pipeline_stage_update(
    state: PaperReproductionPipelineState,
    stage_update: PaperReproductionStageState,
) -> PaperReproductionPipelineState:
    state.mark_stage(
        stage_update.name,
        stage_update.status,
        execution_status=stage_update.execution_status,
        truth_validation_status=stage_update.truth_validation_status,
        summary=stage_update.summary,
        artifact_paths=stage_update.artifact_paths,
        diagnostics=stage_update.diagnostics,
        limitations=stage_update.limitations,
    )
    return state


def _legacy_execution_status(status: str) -> str:
    if status == "passed":
        return "completed"
    if status in {"needs_human_review", "blocked_by_data"}:
        return "completed_with_limitations"
    if status == "failed":
        return "failed"
    return status if status in EXECUTION_STATUSES else "pending"


def _merge_unique(existing: list[str], incoming: list[str]) -> list[str]:
    merged = list(existing)
    for item in incoming:
        if item not in merged:
            merged.append(item)
    return merged
