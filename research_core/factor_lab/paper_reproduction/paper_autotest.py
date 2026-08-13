from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from research_core.factor_lab.paper_reproduction.agent_harness import (
    PaperReproductionAgentHarnessRequest,
    prepare_agent_harness_bundle,
)
from research_core.factor_lab.runtime import FactorLabWorkspaceConfig, now_iso


PAPER_EXTENSIONS = {".pdf"}
MAX_PARALLEL_REPRODUCERS = 2
MAX_FACTORS_PER_PAPER = 10
DEFAULT_REPRODUCER_MODEL = "gpt-5.6-terra"
DEFAULT_REVIEWER_MODEL = "gpt-5.6-sol"
OWNERSHIP_FILE = ".paper_autotest_owner.json"
ARTIFACT_ROOTS = (
    "runtime/factor_lab/agent_harness",
    "runtime/factor_lab/catalogs",
    "runtime/factor_lab/data_profiles",
    "runtime/factor_lab/evaluation_bundles",
    "runtime/factor_lab/evaluation_plans",
    "runtime/factor_lab/evaluations",
    "runtime/factor_lab/implementation_artifacts",
    "runtime/factor_lab/implementation_plans",
    "runtime/factor_lab/jobs",
    "runtime/factor_lab/paper_jobs",
    "runtime/factor_lab/paper_specs",
    "runtime/factor_lab/proofs",
    "runtime/factor_lab/reports",
    "runtime/factor_lab/resource_evidence",
    "runtime/factor_lab/specs",
    "runtime/factor_lab/test_results",
    "runtime/factor_lab/truth",
    "runtime/factor_lab/truth_matches",
    "research_core/factor_lab/libraries",
    "scripts",
    "tests",
)
REQUIRED_HARVEST_FAMILIES = (
    "pipeline_state",
    "paper_extraction",
    "normalized_specs",
    "data_profile",
    "implementation_artifact",
    "implementation_test_source",
    "implementation_test_result",
    "evaluation_plan",
    "evaluation_bundle",
    "truth_match",
    "report_json",
    "report_markdown",
)
IGNORED_HARVEST_DIRECTORY_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
IGNORED_HARVEST_FILE_NAMES = {".DS_Store"}
IGNORED_HARVEST_SUFFIXES = {".pyc", ".pyo"}


@dataclass(frozen=True, slots=True)
class PaperCandidate:
    paper_id: str
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class FactorSelectionEvidence:
    factor_name: str
    formula_source_location: str
    truth_source_location: str
    paper_metrics: dict[str, Any]
    formula_fields: list[str]
    formula_clarity: int
    local_data_support: int
    evaluator_support: int
    performance_strength: int
    compute_feasibility: int
    selection_reason: str

    @property
    def score(self) -> int:
        return (
            self.formula_clarity
            + self.local_data_support
            + self.evaluator_support
            + self.performance_strength
            + self.compute_feasibility
        )


@dataclass(slots=True)
class PaperSelectionArtifact:
    paper: PaperCandidate
    selected_factors: list[FactorSelectionEvidence]
    paper_title: str = ""
    paper_recommended_factors: list[str] = field(default_factory=list)
    recommendation_source_location: str = ""
    selection_basis: str = "within_paper_performance"
    selection_notes: list[str] = field(default_factory=list)
    schema_version: str = "paper_autotest_selection/v1"
    created_at: str = field(default_factory=now_iso)


@dataclass(slots=True)
class PaperTestRunPlan:
    batch_id: str
    run_id: str
    paper_id: str
    paper_path: str
    selected_factors: list[str]
    repository_root: str
    base_ref: str
    base_commit: str
    branch: str
    worktree: str
    control_root: str
    reproducer_model: str = DEFAULT_REPRODUCER_MODEL
    reviewer_model: str = DEFAULT_REVIEWER_MODEL
    status: str = "planned"
    attempt: int = 1
    harness_prompt_path: str = ""
    worker_task_id: str = ""
    worker_outcome: str = ""
    worker_started_at: str = ""
    worker_stopped_at: str = ""
    worker_gate_pass_count: int = 0
    worker_gate_path: str = ""
    reviewer_task_id: str = ""
    reviewer_assignment_path: str = ""
    reviewer_started_at: str = ""
    reviewer_completed_at: str = ""
    review_path: str = ""
    review_verdict: str = ""
    state_history: list[dict[str, str]] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)


@dataclass(slots=True)
class PaperAutotestBatchManifest:
    batch_id: str
    papers_root: str
    repository_root: str
    base_ref: str
    base_commit: str
    max_parallel_reproducers: int
    runs: list[PaperTestRunPlan]
    orchestrator_model: str = DEFAULT_REVIEWER_MODEL
    reviewer_model: str = DEFAULT_REVIEWER_MODEL
    reproducer_model: str = DEFAULT_REPRODUCER_MODEL
    status: str = "planned"
    schema_version: str = "paper_autotest_batch/v1"
    created_at: str = field(default_factory=now_iso)


def discover_test_papers(papers_root: str | Path) -> list[PaperCandidate]:
    root = Path(papers_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"paper test-case directory not found: {root}")
    papers: list[PaperCandidate] = []
    used_ids: set[str] = set()
    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix.lower() not in PAPER_EXTENSIONS:
            continue
        paper_id = _unique_slug(path.stem, used_ids)
        used_ids.add(paper_id)
        papers.append(
            PaperCandidate(
                paper_id=paper_id,
                path=str(path),
                size_bytes=path.stat().st_size,
                sha256=_sha256_file(path),
            )
        )
    return papers


def validate_selection(
    selection: PaperSelectionArtifact,
    *,
    minimum: int = 1,
    maximum: int = MAX_FACTORS_PER_PAPER,
) -> None:
    factors = selection.selected_factors
    if not minimum <= len(factors) <= maximum:
        raise ValueError(f"select between {minimum} and {maximum} factors per paper")
    names = [item.factor_name.strip() for item in factors]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("selected factor names must be non-empty and unique")
    for item in factors:
        if not item.formula_source_location.strip():
            raise ValueError(f"{item.factor_name}: formula source location is required")
        if not item.truth_source_location.strip() or not item.paper_metrics:
            raise ValueError(f"{item.factor_name}: numeric paper truth and its source location are required")
        scores = (
            item.formula_clarity,
            item.local_data_support,
            item.evaluator_support,
            item.performance_strength,
            item.compute_feasibility,
        )
        if any(score < 0 or score > 5 for score in scores):
            raise ValueError(f"{item.factor_name}: rubric scores must be integers from 0 through 5")
        if item.formula_clarity < 3 or item.performance_strength < 3:
            raise ValueError(f"{item.factor_name}: selected factors require clear formulas and strong paper evidence")
    recommended = [name.strip() for name in selection.paper_recommended_factors if name.strip()]
    if recommended:
        if len(recommended) != len(set(recommended)):
            raise ValueError("paper-recommended factor names must be unique")
        if not selection.recommendation_source_location.strip():
            raise ValueError("paper-recommended factors require a conclusion or recommendation source location")
        missing_recommended = [name for name in recommended if name not in names]
        if len(recommended) <= maximum and missing_recommended:
            raise ValueError(
                "all reproducible factors explicitly recommended by the paper must be selected: "
                f"{missing_recommended}"
            )
        if len(recommended) > maximum:
            unexpected = [name for name in names if name not in recommended]
            if len(names) != maximum or unexpected:
                raise ValueError(
                    f"when the paper recommends more than {maximum} factors, select exactly the strongest "
                    f"{maximum} from that paper-recommended set"
                )


def create_batch_manifest(
    *,
    batch_id: str,
    papers_root: str | Path,
    repository_root: str | Path,
    base_ref: str,
    selections: Sequence[PaperSelectionArtifact],
    worktree_root: str | Path = "/private/tmp/agentmatrix-paper-tests",
    max_parallel_reproducers: int = MAX_PARALLEL_REPRODUCERS,
) -> PaperAutotestBatchManifest:
    if not 1 <= max_parallel_reproducers <= MAX_PARALLEL_REPRODUCERS:
        raise ValueError(f"max_parallel_reproducers must be between 1 and {MAX_PARALLEL_REPRODUCERS}")
    if not selections:
        raise ValueError("at least one paper selection is required")
    batch_slug = _slug(batch_id)
    repo = Path(repository_root).expanduser().resolve()
    base_commit = _git(repo, "rev-parse", "--verify", f"{base_ref}^{{commit}}").strip()
    _require_framework_at_ref(repo, base_commit)
    control_root = repo / "runtime" / "factor_lab" / "paper_autotest" / batch_slug
    runs: list[PaperTestRunPlan] = []
    selected_paper_ids: set[str] = set()
    for selection in selections:
        validate_selection(selection)
        if selection.paper.paper_id in selected_paper_ids:
            raise ValueError(f"duplicate paper selection: {selection.paper.paper_id}")
        selected_paper_ids.add(selection.paper.paper_id)
        paper_path = Path(selection.paper.path).expanduser().resolve()
        if not paper_path.is_file():
            raise FileNotFoundError(f"selected paper is missing: {paper_path}")
        if _sha256_file(paper_path) != selection.paper.sha256:
            raise ValueError(f"selected paper hash changed after inventory: {paper_path}")
        paper_slug = _slug(selection.paper.paper_id)
        run_id = f"{batch_slug}-{paper_slug}-a01"
        runs.append(
            PaperTestRunPlan(
                batch_id=batch_slug,
                run_id=run_id,
                paper_id=selection.paper.paper_id,
                paper_path=str(paper_path),
                selected_factors=[factor.factor_name for factor in selection.selected_factors],
                repository_root=str(repo),
                base_ref=base_ref,
                base_commit=base_commit,
                branch=f"codex/paper-test-{run_id}",
                worktree=str(Path(worktree_root).expanduser().resolve() / batch_slug / paper_slug / "attempt-01"),
                control_root=str(control_root / paper_slug / "attempt-01"),
            )
        )
    manifest = PaperAutotestBatchManifest(
        batch_id=batch_slug,
        papers_root=str(Path(papers_root).expanduser().resolve()),
        repository_root=str(repo),
        base_ref=base_ref,
        base_commit=base_commit,
        max_parallel_reproducers=max_parallel_reproducers,
        runs=runs,
    )
    export_json(manifest, control_root / "batch_manifest.json")
    selections_root = control_root / "selections"
    for selection in selections:
        export_json(selection, selections_root / f"{_slug(selection.paper.paper_id)}.json")
    return manifest


def prepare_test_worktree(plan: PaperTestRunPlan) -> Path:
    repo = Path(plan.repository_root).resolve()
    worktree = Path(plan.worktree).resolve()
    if not plan.branch.startswith("codex/paper-test-"):
        raise ValueError("paper test branches must use the codex/paper-test- prefix")
    if worktree.exists():
        raise FileExistsError(f"refusing to reuse an existing paper-test path: {worktree}")
    branch_exists = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{plan.branch}"], cwd=repo, check=False
    ).returncode == 0
    if branch_exists:
        raise FileExistsError(f"refusing to reuse an existing paper-test branch: {plan.branch}")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-b", plan.branch, str(worktree), plan.base_commit)
    ownership = {
        "schema_version": "paper_autotest_worktree/v1",
        "run_id": plan.run_id,
        "branch": plan.branch,
        "base_commit": plan.base_commit,
        "repository_root": str(repo),
        "created_at": now_iso(),
        "baseline_artifacts": _artifact_hashes(worktree),
    }
    (worktree / OWNERSHIP_FILE).write_text(json.dumps(ownership, ensure_ascii=False, indent=2), encoding="utf-8")
    plan.status = "worktree_ready"
    _persist_run_state(plan)
    return worktree


def prepare_run_harness(plan: PaperTestRunPlan) -> str:
    worktree = Path(plan.worktree).resolve()
    ownership = _load_and_validate_ownership(plan)
    if ownership["base_commit"] != plan.base_commit:
        raise ValueError("worktree ownership base commit does not match run plan")
    workspace = FactorLabWorkspaceConfig(
        data_root=worktree / "data" / "factor_lab",
        runtime_root=worktree / "runtime" / "factor_lab",
    )
    bundle = prepare_agent_harness_bundle(
        PaperReproductionAgentHarnessRequest(
            harness_id=plan.run_id,
            working_directory=str(worktree),
            selected_factors=list(plan.selected_factors),
            paper_path=plan.paper_path,
            paper_id=plan.paper_id,
            skill_path=str(worktree / ".agents" / "skills" / "paper-factor-reproduction" / "SKILL.md"),
            notes=[
                f"This is isolated batch {plan.batch_id}, run {plan.run_id}.",
                "Do not inspect other test worktrees, selection rubrics, prior attempts, or reviewer artifacts.",
            ],
        ),
        config=workspace,
    )
    plan.harness_prompt_path = bundle.prompt_path
    plan.status = "ready_for_worker"
    _persist_run_state(plan)
    return bundle.prompt_path


def record_worker_started(plan: PaperTestRunPlan, *, worker_task_id: str) -> Path:
    if plan.status != "ready_for_worker":
        raise ValueError(f"worker can start only from ready_for_worker, not {plan.status}")
    if not worker_task_id.strip():
        raise ValueError("worker task id is required")
    plan.worker_task_id = worker_task_id
    plan.worker_started_at = now_iso()
    plan.status = "running"
    return _persist_run_state(plan)


def record_worker_stopped(
    plan: PaperTestRunPlan,
    *,
    outcome: str,
    details: dict[str, Any] | None = None,
) -> Path:
    if plan.status != "running":
        raise ValueError(f"worker can stop only from running, not {plan.status}")
    if outcome not in {"completed", "interrupted", "failed"}:
        raise ValueError("worker outcome must be completed, interrupted, or failed")
    if outcome == "completed":
        gate = assess_worker_completion_gate(plan)
        if not gate.complete:
            raise ValueError(
                "worker completion gate failed; keep the worker active and repair from "
                f"{gate.earliest_invalid_stage or 'the reported defects'}: {gate.defects}"
            )
    plan.worker_outcome = outcome
    plan.worker_stopped_at = now_iso()
    plan.status = "worker_stopped"
    destination = Path(plan.control_root).resolve()
    export_json(
        {
            "schema_version": "paper_autotest_worker_stop/v1",
            "run_id": plan.run_id,
            "worker_task_id": plan.worker_task_id,
            "outcome": outcome,
            "details": details or {},
            "started_at": plan.worker_started_at,
            "stopped_at": plan.worker_stopped_at,
        },
        destination / "worker_stop.json",
    )
    return _persist_run_state(plan)


def assess_worker_completion_gate(plan: PaperTestRunPlan):
    """Run and persist a fresh control-plane assessment while the worker remains active."""

    if plan.status != "running":
        raise ValueError(f"worker completion gate can run only from running, not {plan.status}")
    from research_core.factor_lab.paper_reproduction.agent_harness_review import assess_agent_harness_run

    assessment = assess_agent_harness_run(
        plan.worktree,
        expected_factors=list(plan.selected_factors),
        harness_id=plan.run_id,
    )
    destination = Path(plan.control_root).resolve()
    plan.worker_gate_pass_count += 1
    history_path = destination / "worker_gate_assessments" / f"gate-{plan.worker_gate_pass_count:02d}.json"
    export_json(assessment, history_path)
    latest_path = export_json(assessment, destination / "worker_completion_gate.json")
    plan.worker_gate_path = str(latest_path)
    _persist_run_state(plan)
    return assessment


def harvest_run_artifacts(plan: PaperTestRunPlan, *, maximum_file_bytes: int = 256 * 1024 * 1024) -> Path:
    worktree = Path(plan.worktree).resolve()
    ownership = _load_and_validate_ownership(plan)
    if not (Path(plan.control_root).resolve() / "worker_stop.json").is_file():
        raise FileNotFoundError("record worker stop before harvesting artifacts")
    baseline = ownership.get("baseline_artifacts", {}) or {}
    destination = Path(plan.control_root).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    changed: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    current = _artifact_hashes(worktree)
    for relative, digest in sorted(current.items()):
        if baseline.get(relative) == digest:
            continue
        source = worktree / relative
        size = source.stat().st_size
        if size > maximum_file_bytes:
            omitted.append({"path": relative, "size_bytes": size, "reason": "file_size_limit"})
            continue
        target = destination / "artifacts" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied_digest = _sha256_file(target)
        if copied_digest != digest:
            raise OSError(f"harvested artifact hash mismatch after copy: {relative}")
        changed.append({"path": relative, "size_bytes": size, "sha256": digest})
    status = _git(worktree, "status", "--short", "--untracked-files=all")
    diff = _git(
        worktree,
        "diff",
        "--no-ext-diff",
        plan.base_commit,
        "--",
        "research_core",
        "docs",
        "scripts",
        "tests",
    )
    (destination / "git_status.txt").write_text(status, encoding="utf-8")
    (destination / "worker_changes.patch").write_text(diff, encoding="utf-8")
    ownership_source = worktree / OWNERSHIP_FILE
    ownership_target = destination / "worktree_ownership.json"
    shutil.copy2(ownership_source, ownership_target)
    artifact_inventory = _artifact_inventory(item["path"] for item in changed)
    artifact_inventory["implementation_test_source"] = _bound_implementation_test_sources(
        worktree,
        changed_paths=[item["path"] for item in changed],
        candidates=artifact_inventory.get("implementation_test_source", []),
    )
    if not artifact_inventory["implementation_test_source"]:
        artifact_inventory.pop("implementation_test_source")
    missing_required = [
        family for family in REQUIRED_HARVEST_FAMILIES if not artifact_inventory.get(family)
    ]
    payload = {
        "schema_version": "paper_autotest_harvest/v2",
        "run_id": plan.run_id,
        "paper_id": plan.paper_id,
        "base_commit": plan.base_commit,
        "branch": plan.branch,
        "worktree": str(worktree),
        "observed_git_head": _git(worktree, "rev-parse", "HEAD").strip(),
        "observed_git_branch": _git(worktree, "branch", "--show-current").strip(),
        "harvested_at": now_iso(),
        "files": changed,
        "omitted_files": omitted,
        "artifact_inventory": artifact_inventory,
        "required_artifact_families": list(REQUIRED_HARVEST_FAMILIES),
        "missing_required_artifact_families": missing_required,
        "copy_integrity": {
            "eligible_changed_file_count": len(changed) + len(omitted),
            "copied_file_count": len(changed),
            "omitted_file_count": len(omitted),
            "all_copied_hashes_verified": True,
            "complete": not omitted,
        },
        "review_ready": not omitted and not missing_required,
        "worktree_ownership_path": str(ownership_target),
        "worktree_ownership_sha256": _sha256_file(ownership_target),
        "git_status_path": str(destination / "git_status.txt"),
        "worker_patch_path": str(destination / "worker_changes.patch"),
    }
    manifest_path = destination / "harvest_manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    plan.status = "harvested"
    _persist_run_state(plan)
    return manifest_path


def record_deterministic_assessment(plan: PaperTestRunPlan, assessment: object | None = None) -> Path:
    destination = Path(plan.control_root).resolve()
    harvest_path = destination / "harvest_manifest.json"
    if not harvest_path.is_file():
        raise FileNotFoundError("harvest artifacts before recording the deterministic assessment")
    from research_core.factor_lab.paper_reproduction.agent_harness_review import assess_agent_harness_run

    fresh = assess_agent_harness_run(
        plan.worktree,
        expected_factors=list(plan.selected_factors),
        harness_id=plan.run_id,
        harvest_manifest_path=harvest_path,
    )
    payload = asdict(fresh)
    if assessment is not None:
        submitted = asdict(assessment) if hasattr(assessment, "__dataclass_fields__") else assessment
        payload.setdefault("diagnostics", {})["submitted_assessment_agreed"] = (
            isinstance(submitted, dict) and bool(submitted.get("complete")) == fresh.complete
        )
    path = export_json(payload, destination / "deterministic_assessment.json")
    plan.status = "deterministic_reviewed"
    _persist_run_state(plan)
    return path


def record_reviewer_started(
    plan: PaperTestRunPlan,
    *,
    reviewer_task_id: str,
    requested_model: str | None = None,
    runtime_model_evidence: dict[str, Any] | None = None,
) -> Path:
    """Persist reviewer assignment provenance before dispatching the reviewer.

    The assignment is control-plane evidence. Reviewer-authored JSON is never
    accepted as proof of its own task identity or requested model.
    """

    if plan.status != "deterministic_reviewed":
        raise ValueError(f"reviewer can start only from deterministic_reviewed, not {plan.status}")
    task_id = reviewer_task_id.strip()
    if not task_id:
        raise ValueError("reviewer task id is required")
    if task_id == plan.worker_task_id:
        raise ValueError("independent reviewer task id must differ from the worker task id")
    _require_fresh_reviewer_task_id(plan, task_id)
    model = (requested_model or plan.reviewer_model).strip()
    if model != plan.reviewer_model:
        raise ValueError(f"reviewer requested model must match the run plan: {plan.reviewer_model}")
    model_evidence = dict(runtime_model_evidence or {})
    observed_model = str(model_evidence.get("actual_model", "")).strip()
    if observed_model and observed_model != model:
        raise ValueError(f"reviewer runtime model does not match requested model: {observed_model} != {model}")
    destination = Path(plan.control_root).resolve()
    required_inputs = (destination / "harvest_manifest.json", destination / "deterministic_assessment.json")
    missing_inputs = [str(path) for path in required_inputs if not path.is_file()]
    if missing_inputs:
        raise FileNotFoundError(f"reviewer assignment inputs are missing: {missing_inputs}")
    assigned_at = now_iso()
    payload = {
        "schema_version": "paper_autotest_reviewer_assignment/v1",
        "run_id": plan.run_id,
        "paper_id": plan.paper_id,
        "paper_path": plan.paper_path,
        "paper_sha256": _sha256_file(Path(plan.paper_path).expanduser().resolve()),
        "selected_factors": list(plan.selected_factors),
        "base_commit": plan.base_commit,
        "branch": plan.branch,
        "worker_task_id": plan.worker_task_id,
        "reviewer_task_id": task_id,
        "requested_model": model,
        "actual_model_status": "attested" if observed_model else "unverified",
        "runtime_model_evidence": model_evidence,
        "independence_checks": {
            "different_from_worker": True,
            "unused_by_other_batch_run": True,
        },
        "review_inputs": _review_input_records(plan),
        "assigned_at": assigned_at,
    }
    path = export_json(payload, destination / "reviewer_assignment.json")
    plan.reviewer_task_id = task_id
    plan.reviewer_assignment_path = str(path)
    plan.reviewer_started_at = assigned_at
    plan.status = "reviewer_running"
    _persist_run_state(plan)
    return path


def record_independent_review(plan: PaperTestRunPlan, review: dict[str, Any]) -> Path:
    destination = Path(plan.control_root).resolve()
    if plan.status != "reviewer_running":
        raise ValueError(f"independent review can finish only from reviewer_running, not {plan.status}")
    assignment_path = destination / "reviewer_assignment.json"
    if not assignment_path.is_file():
        raise FileNotFoundError("record the reviewer assignment before independent review")
    assignment = json.loads(assignment_path.read_text(encoding="utf-8"))
    if assignment.get("run_id") != plan.run_id or assignment.get("reviewer_task_id") != plan.reviewer_task_id:
        raise ValueError("reviewer assignment does not match the active run plan")
    verdict = str(review.get("verdict", ""))
    if verdict not in {"complete", "complete_with_limitations", "incomplete"}:
        raise ValueError("independent review verdict must be complete, complete_with_limitations, or incomplete")
    deterministic_path = destination / "deterministic_assessment.json"
    harvest_path = destination / "harvest_manifest.json"
    deterministic = json.loads(deterministic_path.read_text(encoding="utf-8"))
    harvest = json.loads(harvest_path.read_text(encoding="utf-8"))
    if verdict in {"complete", "complete_with_limitations"}:
        if deterministic.get("complete") is not True:
            raise ValueError(
                "a positive independent-review verdict requires a complete deterministic assessment"
            )
        if harvest.get("review_ready") is not True:
            raise ValueError(
                "a positive independent-review verdict requires a review-ready harvest manifest"
            )
    for field_name in ("blocking_defects", "limitations", "cited_artifact_paths"):
        if not isinstance(review.get(field_name), list):
            raise ValueError(f"independent review must include list field: {field_name}")
    if not review["cited_artifact_paths"]:
        raise ValueError("independent review must cite at least one persisted artifact path")
    reported_task_id = str(review.get("reviewer_task_id", "")).strip()
    if reported_task_id and reported_task_id != plan.reviewer_task_id:
        raise ValueError("reviewer-authored task id conflicts with the control-plane assignment")
    reported_model = str(review.get("requested_model", "")).strip()
    if reported_model and reported_model != assignment.get("requested_model"):
        raise ValueError("reviewer-authored requested model conflicts with the control-plane assignment")
    completed_at = now_iso()
    payload = dict(review)
    payload["schema_version"] = "paper_reproduction_independent_review/v2"
    payload["reviewer_task_id"] = plan.reviewer_task_id
    payload["requested_model"] = assignment["requested_model"]
    payload["recorded_at"] = completed_at
    payload["provenance"] = {
        "source": "paper_autotest_control_plane",
        "assignment_path": str(assignment_path),
        "assignment_sha256": _sha256_file(assignment_path),
        "worker_task_id": plan.worker_task_id,
        "reviewer_task_id": plan.reviewer_task_id,
        "requested_model": assignment["requested_model"],
        "actual_model_status": assignment["actual_model_status"],
        "independence_checks": assignment["independence_checks"],
        "review_input_hashes": assignment["review_inputs"],
        "deterministic_assessment_sha256": _sha256_file(deterministic_path),
        "harvest_manifest_sha256": _sha256_file(harvest_path),
    }
    path = export_json(payload, destination / "independent_review.json")
    export_json(
        {
            "schema_version": "paper_autotest_reviewer_completion/v1",
            "run_id": plan.run_id,
            "reviewer_task_id": plan.reviewer_task_id,
            "requested_model": assignment["requested_model"],
            "actual_model_status": assignment["actual_model_status"],
            "assignment_sha256": _sha256_file(assignment_path),
            "review_sha256": _sha256_file(path),
            "verdict": verdict,
            "completed_at": completed_at,
        },
        destination / "reviewer_completion.json",
    )
    plan.review_path = str(path)
    plan.reviewer_completed_at = completed_at
    plan.status = "independently_reviewed"
    _persist_run_state(plan)
    plan.review_verdict = verdict
    plan.status = verdict
    _persist_run_state(plan)
    return path


def cleanup_test_worktree(plan: PaperTestRunPlan) -> None:
    """Remove only a worktree carrying the exact run ownership record."""

    repo = Path(plan.repository_root).resolve()
    worktree = Path(plan.worktree).resolve()
    _load_and_validate_ownership(plan)
    control_root = Path(plan.control_root).resolve()
    required = (
        control_root / "harvest_manifest.json",
        control_root / "deterministic_assessment.json",
        control_root / "reviewer_assignment.json",
        control_root / "independent_review.json",
        control_root / "reviewer_completion.json",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"refusing cleanup before harvest and both persisted reviews: {missing}")
    _git(repo, "worktree", "remove", "--force", str(worktree))
    _git(repo, "branch", "-D", plan.branch)
    plan.status = "cleaned"
    _persist_run_state(plan)


def export_json(value: object, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(value) if hasattr(value, "__dataclass_fields__") else value
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _persist_run_state(plan: PaperTestRunPlan) -> Path:
    if not plan.state_history or plan.state_history[-1].get("status") != plan.status:
        plan.state_history.append({"status": plan.status, "recorded_at": now_iso()})
    path = export_json(plan, Path(plan.control_root).resolve() / "run_state.json")
    _sync_batch_manifest(plan)
    return path


def _load_and_validate_ownership(plan: PaperTestRunPlan) -> dict[str, Any]:
    worktree = Path(plan.worktree).resolve()
    path = worktree / OWNERSHIP_FILE
    if not path.is_file():
        raise FileNotFoundError(f"paper-test ownership record is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {"run_id": plan.run_id, "branch": plan.branch, "repository_root": str(Path(plan.repository_root).resolve())}
    mismatches = [key for key, value in expected.items() if payload.get(key) != value]
    if mismatches:
        raise ValueError(f"paper-test ownership mismatch: {mismatches}")
    return payload


def _artifact_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative_root in ARTIFACT_ROOTS:
        directory = root / relative_root
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and _is_harvestable_file(path, root):
                hashes[path.relative_to(root).as_posix()] = _sha256_file(path)
    return hashes


def _is_harvestable_file(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in IGNORED_HARVEST_DIRECTORY_NAMES for part in relative.parts):
        return False
    if path.name in IGNORED_HARVEST_FILE_NAMES or path.suffix.lower() in IGNORED_HARVEST_SUFFIXES:
        return False
    return True


def _artifact_inventory(paths: Sequence[str]) -> dict[str, list[str]]:
    inventory: dict[str, list[str]] = {}
    for path in paths:
        for family in _artifact_families(path):
            inventory.setdefault(family, []).append(path)
    return {family: sorted(values) for family, values in sorted(inventory.items())}


def _artifact_families(path: str) -> set[str]:
    families: set[str] = set()
    if path.startswith(("runtime/factor_lab/paper_jobs/", "runtime/factor_lab/jobs/")):
        families.add("pipeline_state")
    if path.startswith("runtime/factor_lab/paper_specs/"):
        families.add("paper_extraction")
    if path.startswith("runtime/factor_lab/specs/"):
        families.add("normalized_specs")
    if path.startswith("runtime/factor_lab/data_profiles/"):
        families.add("data_profile")
    if path.startswith("runtime/factor_lab/implementation_artifacts/"):
        families.add("implementation_artifact")
    if path.startswith("runtime/factor_lab/implementation_plans/"):
        families.add("implementation_plan")
    if path.startswith("runtime/factor_lab/evaluation_plans/"):
        families.add("evaluation_plan")
    if path.startswith(("runtime/factor_lab/evaluation_bundles/", "runtime/factor_lab/evaluations/")):
        families.add("evaluation_bundle")
    if path.startswith(("runtime/factor_lab/truth_matches/", "runtime/factor_lab/truth/")):
        families.add("truth_match")
    if path.startswith("runtime/factor_lab/reports/") and path.endswith(".json"):
        families.add("report_json")
    if path.startswith("runtime/factor_lab/reports/") and path.endswith(".md"):
        families.add("report_markdown")
    if path.startswith("runtime/factor_lab/test_results/"):
        families.add("implementation_test_result")
    name = Path(path).name
    is_test_source = path.endswith(".py") and (
        name.startswith("test_") or "/tests/" in path or path.startswith("tests/")
    )
    is_factor_test_location = path.startswith("research_core/factor_lab/libraries/") or path.startswith(
        "tests/"
    )
    if is_test_source and is_factor_test_location:
        families.add("implementation_test_source")
    if path.startswith("runtime/factor_lab/resource_evidence/"):
        families.add("resource_evidence")
    if path.startswith("runtime/factor_lab/agent_harness/"):
        families.add("agent_harness")
    if path.startswith("scripts/"):
        families.add("worker_script")
    return families


def _bound_implementation_test_sources(
    worktree: Path,
    *,
    changed_paths: Sequence[str],
    candidates: Sequence[str],
) -> list[str]:
    worktree = worktree.resolve()
    module_paths: list[Path] = []
    callable_modules: list[str] = []
    for relative in changed_paths:
        if not relative.startswith("runtime/factor_lab/implementation_artifacts/") or not relative.endswith(
            ".json"
        ):
            continue
        try:
            artifact = json.loads((worktree / relative).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        raw_module_path = Path(str(artifact.get("module_path", "")))
        module_path = raw_module_path if raw_module_path.is_absolute() else worktree / raw_module_path
        try:
            module_paths.append(module_path.resolve().relative_to(worktree))
        except ValueError:
            continue
        callable_module = str(artifact.get("callable_import_path", "")).split(":", 1)[0]
        if callable_module:
            callable_modules.append(callable_module)
    bound: list[str] = []
    for relative in candidates:
        candidate = Path(relative)
        if any(candidate.parent == module.parent for module in module_paths):
            bound.append(relative)
            continue
        try:
            text = (worktree / candidate).read_text(encoding="utf-8")
        except OSError:
            continue
        if any(module in text for module in callable_modules):
            bound.append(relative)
    return sorted(dict.fromkeys(bound))


def _review_input_records(plan: PaperTestRunPlan) -> list[dict[str, str]]:
    control_root = Path(plan.control_root).resolve()
    batch_root = control_root.parents[1]
    candidates = [
        ("harvest_manifest", control_root / "harvest_manifest.json"),
        ("deterministic_assessment", control_root / "deterministic_assessment.json"),
        ("selection", batch_root / "selections" / f"{_slug(plan.paper_id)}.json"),
    ]
    harness_metadata = sorted((control_root / "artifacts" / "runtime" / "factor_lab" / "agent_harness").glob(
        "*/harness_metadata.json"
    ))
    if harness_metadata:
        candidates.append(("harness_metadata", harness_metadata[-1]))
    records: list[dict[str, str]] = []
    for role, path in candidates:
        if path.is_file():
            records.append({"role": role, "path": str(path), "sha256": _sha256_file(path)})
    return records


def _require_fresh_reviewer_task_id(plan: PaperTestRunPlan, reviewer_task_id: str) -> None:
    manifest_path = Path(plan.control_root).resolve().parents[1] / "batch_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"batch manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    conflicts: list[str] = []
    for run in manifest.get("runs", []) or []:
        run_id = str(run.get("run_id", ""))
        for role in ("worker_task_id", "reviewer_task_id"):
            if str(run.get(role, "")) == reviewer_task_id and not (
                run_id == plan.run_id and role == "reviewer_task_id"
            ):
                conflicts.append(f"{run_id}:{role}")
    if conflicts:
        raise ValueError(f"reviewer task id is not fresh within the batch: {conflicts}")


def _sync_batch_manifest(plan: PaperTestRunPlan) -> None:
    manifest_path = Path(plan.control_root).resolve().parents[1] / "batch_manifest.json"
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runs = manifest.get("runs", []) or []
    matched = False
    for index, run in enumerate(runs):
        if run.get("run_id") == plan.run_id:
            runs[index] = asdict(plan)
            matched = True
            break
    if not matched:
        raise ValueError(f"run {plan.run_id} is missing from batch manifest")
    manifest["runs"] = runs
    verdicts = [str(run.get("review_verdict", "")) for run in runs]
    if all(verdicts):
        if "incomplete" in verdicts:
            manifest["status"] = "incomplete"
        elif "complete_with_limitations" in verdicts:
            manifest["status"] = "complete_with_limitations"
        else:
            manifest["status"] = "complete"
    elif all(str(run.get("status", "")) == "planned" for run in runs):
        manifest["status"] = "planned"
    else:
        manifest["status"] = "in_progress"
    manifest["updated_at"] = now_iso()
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(manifest_path)


def _require_framework_at_ref(repo: Path, ref: str) -> None:
    required = (
        ".agents/skills/paper-factor-reproduction/SKILL.md",
        ".agents/skills/paper-reproduction-review/SKILL.md",
        "research_core/factor_lab/paper_reproduction/agent_harness.py",
    )
    tracked = set(_git(repo, "ls-tree", "-r", "--name-only", ref, "--", *required).splitlines())
    missing = [path for path in required if path not in tracked]
    if missing:
        raise ValueError(f"base ref does not contain the tracked reproduction framework: {missing}")


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not text:
        text = "paper-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return text[:72].rstrip("-")


def _unique_slug(value: str, used: set[str]) -> str:
    base = _slug(value)
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base[:64]}-{index}"
        index += 1
    return candidate
