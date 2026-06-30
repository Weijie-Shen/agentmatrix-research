from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from uuid import uuid4

from research_core.factor_lab.paper_reproduction.extraction import PaperExtraction
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


GATING_STATUSES = {"pending", "needs_human_review", "failed", "blocked_by_data"}


@dataclass(slots=True)
class PaperReproductionStageState:
    name: str
    status: str = "pending"
    summary: str = ""
    artifact_paths: list[str] = field(default_factory=list)
    diagnostics: dict[str, object] = field(default_factory=dict)
    updated_at: str = ""


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
        extraction: PaperExtraction,
        *,
        job_id: str | None = None,
    ) -> PaperReproductionPipelineState:
        return cls(
            job_id=job_id or f"paper-{uuid4().hex[:12]}",
            paper_id=extraction.paper_id,
            family_name=extraction.factor_family_name,
            stages=[PaperReproductionStageState(name=stage.value) for stage in PaperReproductionStage],
        )

    @property
    def overall_status(self) -> str:
        statuses = [stage.status for stage in self.stages]
        if any(status == "failed" for status in statuses):
            return "failed"
        if any(status == "blocked_by_data" for status in statuses):
            return "blocked_by_data"
        if any(status == "needs_human_review" for status in statuses):
            return "needs_human_review"
        if all(status == "passed" for status in statuses):
            return "passed"
        if any(status == "passed" for status in statuses):
            return "in_progress"
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
        summary: str = "",
        artifact_paths: list[str] | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        stage = self._stage(stage_name)
        stage.status = status
        stage.summary = summary
        stage.artifact_paths = artifact_paths or []
        stage.diagnostics = diagnostics or {}
        stage.updated_at = now_iso()
        self.updated_at = stage.updated_at

    def ready_for_stage(self, stage_name: str) -> bool:
        for stage in self.stages:
            if stage.name == stage_name:
                return True
            if stage.status in GATING_STATUSES:
                return False
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
