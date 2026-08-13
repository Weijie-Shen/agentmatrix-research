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
    "runtime/factor_lab/evaluation_bundles",
    "runtime/factor_lab/evaluations",
    "runtime/factor_lab/implementation_plans",
    "runtime/factor_lab/jobs",
    "runtime/factor_lab/paper_jobs",
    "runtime/factor_lab/paper_specs",
    "runtime/factor_lab/proofs",
    "runtime/factor_lab/reports",
    "runtime/factor_lab/specs",
    "runtime/factor_lab/truth",
    "research_core/factor_lab/libraries",
)


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
    reviewer_task_id: str = ""
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
    plan.worker_outcome = outcome
    plan.status = "worker_stopped"
    destination = Path(plan.control_root).resolve()
    export_json(
        {
            "schema_version": "paper_autotest_worker_stop/v1",
            "run_id": plan.run_id,
            "worker_task_id": plan.worker_task_id,
            "outcome": outcome,
            "details": details or {},
            "stopped_at": now_iso(),
        },
        destination / "worker_stop.json",
    )
    return _persist_run_state(plan)


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
        changed.append({"path": relative, "size_bytes": size, "sha256": digest})
    status = _git(worktree, "status", "--short", "--untracked-files=all")
    diff = _git(worktree, "diff", "--no-ext-diff", plan.base_commit, "--", "research_core", "docs")
    (destination / "git_status.txt").write_text(status, encoding="utf-8")
    (destination / "worker_changes.patch").write_text(diff, encoding="utf-8")
    payload = {
        "schema_version": "paper_autotest_harvest/v1",
        "run_id": plan.run_id,
        "paper_id": plan.paper_id,
        "base_commit": plan.base_commit,
        "branch": plan.branch,
        "worktree": str(worktree),
        "harvested_at": now_iso(),
        "files": changed,
        "omitted_files": omitted,
        "git_status_path": str(destination / "git_status.txt"),
        "worker_patch_path": str(destination / "worker_changes.patch"),
    }
    manifest_path = destination / "harvest_manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    plan.status = "harvested"
    _persist_run_state(plan)
    return manifest_path


def record_deterministic_assessment(plan: PaperTestRunPlan, assessment: object) -> Path:
    destination = Path(plan.control_root).resolve()
    if not (destination / "harvest_manifest.json").is_file():
        raise FileNotFoundError("harvest artifacts before recording the deterministic assessment")
    path = export_json(assessment, destination / "deterministic_assessment.json")
    plan.status = "deterministic_reviewed"
    _persist_run_state(plan)
    return path


def record_independent_review(plan: PaperTestRunPlan, review: dict[str, Any]) -> Path:
    destination = Path(plan.control_root).resolve()
    if not (destination / "deterministic_assessment.json").is_file():
        raise FileNotFoundError("record the deterministic assessment before independent review")
    verdict = str(review.get("verdict", ""))
    if verdict not in {"complete", "complete_with_limitations", "incomplete"}:
        raise ValueError("independent review verdict must be complete, complete_with_limitations, or incomplete")
    path = export_json(review, destination / "independent_review.json")
    plan.review_path = str(path)
    plan.reviewer_task_id = str(review.get("reviewer_task_id", plan.reviewer_task_id))
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
        control_root / "independent_review.json",
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
    return export_json(plan, Path(plan.control_root).resolve() / "run_state.json")


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
            if path.is_file():
                hashes[path.relative_to(root).as_posix()] = _sha256_file(path)
    return hashes


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
