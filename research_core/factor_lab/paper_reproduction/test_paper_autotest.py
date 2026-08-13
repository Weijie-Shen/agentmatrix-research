from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_core.factor_lab.paper_reproduction.agent_harness_review import AgentHarnessRunAssessment
from research_core.factor_lab.paper_reproduction.paper_autotest import (
    FactorSelectionEvidence,
    PaperSelectionArtifact,
    cleanup_test_worktree,
    create_batch_manifest,
    discover_test_papers,
    harvest_run_artifacts,
    prepare_run_harness,
    prepare_test_worktree,
    record_deterministic_assessment,
    record_independent_review,
    record_reviewer_started,
    record_worker_started,
    record_worker_stopped,
    validate_selection,
)


class PaperAutotestTest(unittest.TestCase):
    def test_discovers_pdf_candidates_with_stable_hashes_and_unique_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "Factor Test.pdf").write_bytes(b"paper-one")
            (root / "Factor-Test.pdf").write_bytes(b"paper-two")
            (root / "notes.txt").write_text("ignore", encoding="utf-8")

            papers = discover_test_papers(root)

            self.assertEqual(len(papers), 2)
            self.assertEqual([paper.paper_id for paper in papers], ["factor-test", "factor-test-2"])
            self.assertNotEqual(papers[0].sha256, papers[1].sha256)

    def test_selection_requires_formula_and_numeric_truth_evidence(self) -> None:
        paper = self._paper(Path("/tmp/demo.pdf"))
        selection = PaperSelectionArtifact(
            paper=paper,
            selected_factors=[self._factor("ClearFactor")],
        )
        validate_selection(selection)

        invalid = PaperSelectionArtifact(
            paper=paper,
            selected_factors=[
                FactorSelectionEvidence(
                    factor_name="NoTruth",
                    formula_source_location="p. 3",
                    truth_source_location="",
                    paper_metrics={},
                    formula_fields=["close"],
                    formula_clarity=5,
                    local_data_support=5,
                    evaluator_support=5,
                    performance_strength=5,
                    compute_feasibility=5,
                    selection_reason="invalid fixture",
                )
            ],
        )
        with self.assertRaisesRegex(ValueError, "numeric paper truth"):
            validate_selection(invalid)

    def test_selection_uses_paper_conclusion_set_and_allows_up_to_ten_factors(self) -> None:
        paper = self._paper(Path("/tmp/demo.pdf"))
        conclusion_factors = [f"Factor{index}" for index in range(1, 8)]
        selection = PaperSelectionArtifact(
            paper=paper,
            selected_factors=[self._factor(name) for name in conclusion_factors],
            paper_recommended_factors=conclusion_factors,
            recommendation_source_location="Conclusion, p. 42",
        )

        validate_selection(selection)

        selection.selected_factors = [self._factor(name) for name in conclusion_factors[:-1]]
        with self.assertRaisesRegex(ValueError, "explicitly recommended"):
            validate_selection(selection)

        ten = PaperSelectionArtifact(
            paper=paper,
            selected_factors=[self._factor(f"Top{index}") for index in range(10)],
        )
        validate_selection(ten)
        ten.selected_factors.append(self._factor("TooMany"))
        with self.assertRaisesRegex(ValueError, "between 1 and 10"):
            validate_selection(ten)

    def test_batch_worktree_harness_harvest_and_owned_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo = root / "repo"
            papers = root / "papers"
            worktrees = root / "worktrees"
            repo.mkdir()
            papers.mkdir()
            paper_path = papers / "Demo Paper.pdf"
            paper_path.write_bytes(b"paper")
            self._init_framework_repo(repo)
            selection = PaperSelectionArtifact(
                paper=discover_test_papers(papers)[0],
                selected_factors=[self._factor("FactorA")],
                paper_title="Demo Paper",
            )

            manifest = create_batch_manifest(
                batch_id="batch-1",
                papers_root=papers,
                repository_root=repo,
                base_ref="HEAD",
                selections=[selection],
                worktree_root=worktrees,
                max_parallel_reproducers=2,
            )
            plan = manifest.runs[0]
            worktree = prepare_test_worktree(plan)
            prompt_path = Path(prepare_run_harness(plan))
            self.assertTrue(prompt_path.is_file())
            self.assertIn("FactorA", prompt_path.read_text(encoding="utf-8"))
            report = worktree / "runtime" / "factor_lab" / "reports" / "demo_paper_reproduction_report.json"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({"paper_id": "demo"}), encoding="utf-8")
            record_worker_started(plan, worker_task_id="terra-worker-1")
            record_worker_stopped(plan, outcome="failed", details={"message": "fixture done"})

            harvest_path = harvest_run_artifacts(plan)
            harvest = json.loads(harvest_path.read_text(encoding="utf-8"))
            harvested_paths = [item["path"] for item in harvest["files"]]
            self.assertIn("runtime/factor_lab/reports/demo_paper_reproduction_report.json", harvested_paths)
            self.assertTrue(
                (Path(plan.control_root) / "artifacts" / "runtime" / "factor_lab" / "reports" / report.name).is_file()
            )
            with self.assertRaisesRegex(FileNotFoundError, "both persisted reviews"):
                cleanup_test_worktree(plan)
            record_deterministic_assessment(plan, {"complete": False, "defects": ["fixture"]})
            record_reviewer_started(
                plan,
                reviewer_task_id="sol-reviewer-1",
                runtime_model_evidence={
                    "actual_model": "gpt-5.6-sol",
                    "source": "test dispatcher fixture",
                },
            )
            with self.assertRaisesRegex(ValueError, "complete deterministic assessment"):
                record_independent_review(
                    plan,
                    {
                        "verdict": "complete",
                        "blocking_defects": [],
                        "limitations": [],
                        "cited_artifact_paths": [str(harvest_path)],
                    },
                )
            record_independent_review(
                plan,
                {
                    "reviewer_task_id": "sol-reviewer-1",
                    "requested_model": "gpt-5.6-sol",
                    "verdict": "incomplete",
                    "blocking_defects": ["fixture"],
                    "limitations": [],
                    "cited_artifact_paths": [str(harvest_path)],
                },
            )

            cleanup_test_worktree(plan)
            self.assertFalse(worktree.exists())
            state = json.loads((Path(plan.control_root) / "run_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "cleaned")
            self.assertEqual(
                [item["status"] for item in state["state_history"]],
                [
                    "worktree_ready",
                    "ready_for_worker",
                    "running",
                    "worker_stopped",
                    "harvested",
                    "deterministic_reviewed",
                    "reviewer_running",
                    "independently_reviewed",
                    "incomplete",
                    "cleaned",
                ],
            )
            branch_check = subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{plan.branch}"], cwd=repo, check=False
            )
            self.assertNotEqual(branch_check.returncode, 0)

            batch = json.loads((Path(plan.control_root).parents[1] / "batch_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(batch["status"], "incomplete")
            self.assertEqual(batch["runs"][0]["review_verdict"], "incomplete")

    def test_harvest_captures_required_scientific_families_scripts_and_ignores_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo = root / "repo"
            papers = root / "papers"
            worktrees = root / "worktrees"
            repo.mkdir()
            papers.mkdir()
            (papers / "Demo Paper.pdf").write_bytes(b"paper")
            self._init_framework_repo(repo)
            selection = PaperSelectionArtifact(
                paper=discover_test_papers(papers)[0],
                selected_factors=[self._factor("FactorA")],
            )
            plan = create_batch_manifest(
                batch_id="harvest-families",
                papers_root=papers,
                repository_root=repo,
                base_ref="HEAD",
                selections=[selection],
                worktree_root=worktrees,
            ).runs[0]
            worktree = prepare_test_worktree(plan)
            prepare_run_harness(plan)
            fixture_files = {
                "runtime/factor_lab/paper_jobs/job.json": "{}",
                "runtime/factor_lab/paper_specs/extraction.json": "{}",
                "runtime/factor_lab/specs/specs.json": "{}",
                "runtime/factor_lab/data_profiles/qfq.json": "{}",
                "runtime/factor_lab/implementation_artifacts/implementation.json": "{}",
                "runtime/factor_lab/test_results/pytest.txt": "2 passed",
                "runtime/factor_lab/evaluation_plans/plan.json": "{}",
                "runtime/factor_lab/evaluation_bundles/qfq.json": "{}",
                "runtime/factor_lab/truth_matches/matches.json": "{}",
                "runtime/factor_lab/reports/report.json": "{}",
                "runtime/factor_lab/reports/report.md": "# report",
                "research_core/factor_lab/libraries/demo/test_factors.py": "def test_factor(): pass\n",
                "research_core/factor_lab/libraries/demo/__pycache__/test_factors.pyc": "bytecode",
                "scripts/run_demo.py": "print(1)\n",
            }
            for relative, content in fixture_files.items():
                path = worktree / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            record_worker_started(plan, worker_task_id="terra-worker-harvest")
            record_worker_stopped(plan, outcome="failed")

            manifest = json.loads(harvest_run_artifacts(plan).read_text(encoding="utf-8"))
            paths = {item["path"] for item in manifest["files"]}

            self.assertTrue(manifest["review_ready"])
            self.assertEqual(manifest["missing_required_artifact_families"], [])
            self.assertIn("runtime/factor_lab/data_profiles/qfq.json", paths)
            self.assertIn("runtime/factor_lab/implementation_artifacts/implementation.json", paths)
            self.assertIn("runtime/factor_lab/truth_matches/matches.json", paths)
            self.assertIn("scripts/run_demo.py", paths)
            self.assertNotIn("research_core/factor_lab/libraries/demo/__pycache__/test_factors.pyc", paths)
            self.assertEqual(manifest["observed_git_head"], plan.base_commit)
            self.assertTrue(Path(manifest["worktree_ownership_path"]).is_file())

            assessment_path = record_deterministic_assessment(plan, {"complete": True})
            assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
            self.assertFalse(assessment["complete"])
            self.assertFalse(assessment["diagnostics"]["submitted_assessment_agreed"])

    def test_reviewer_provenance_is_control_plane_owned_and_requires_fresh_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo = root / "repo"
            papers = root / "papers"
            worktrees = root / "worktrees"
            repo.mkdir()
            papers.mkdir()
            (papers / "Demo Paper.pdf").write_bytes(b"paper")
            self._init_framework_repo(repo)
            plan = create_batch_manifest(
                batch_id="reviewer-provenance",
                papers_root=papers,
                repository_root=repo,
                base_ref="HEAD",
                selections=[
                    PaperSelectionArtifact(
                        paper=discover_test_papers(papers)[0],
                        selected_factors=[self._factor("FactorA")],
                    )
                ],
                worktree_root=worktrees,
            ).runs[0]
            prepare_test_worktree(plan)
            prepare_run_harness(plan)
            record_worker_started(plan, worker_task_id="terra-worker-1")
            record_worker_stopped(plan, outcome="failed")
            harvest_path = harvest_run_artifacts(plan)
            record_deterministic_assessment(plan, {"complete": False})

            with self.assertRaisesRegex(ValueError, "differ from the worker"):
                record_reviewer_started(plan, reviewer_task_id="terra-worker-1")
            with self.assertRaisesRegex(ValueError, "must match the run plan"):
                record_reviewer_started(
                    plan,
                    reviewer_task_id="sol-reviewer-1",
                    requested_model="gpt-5.6-terra",
                )
            manifest_path = Path(plan.control_root).parents[1] / "batch_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            reused = dict(manifest["runs"][0])
            reused["run_id"] = "another-run"
            reused["worker_task_id"] = "previous-terra-task"
            manifest["runs"].append(reused)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not fresh within the batch"):
                record_reviewer_started(plan, reviewer_task_id="previous-terra-task")
            assignment_path = record_reviewer_started(plan, reviewer_task_id="sol-reviewer-1")
            assignment = json.loads(assignment_path.read_text(encoding="utf-8"))
            self.assertEqual(assignment["actual_model_status"], "unverified")
            self.assertTrue(assignment["independence_checks"]["different_from_worker"])
            self.assertTrue(assignment["review_inputs"])

            with self.assertRaisesRegex(ValueError, "conflicts"):
                record_independent_review(
                    plan,
                    {
                        "reviewer_task_id": "wrong-reviewer",
                        "verdict": "incomplete",
                        "blocking_defects": ["fixture"],
                        "limitations": [],
                        "cited_artifact_paths": [str(harvest_path)],
                    },
                )
            review_path = record_independent_review(
                plan,
                {
                    "verdict": "incomplete",
                    "blocking_defects": ["fixture"],
                    "limitations": [],
                    "cited_artifact_paths": [str(harvest_path)],
                },
            )
            review = json.loads(review_path.read_text(encoding="utf-8"))
            completion = json.loads(
                (Path(plan.control_root) / "reviewer_completion.json").read_text(encoding="utf-8")
            )
            self.assertEqual(review["reviewer_task_id"], "sol-reviewer-1")
            self.assertEqual(review["provenance"]["actual_model_status"], "unverified")
            self.assertEqual(completion["reviewer_task_id"], "sol-reviewer-1")
            self.assertEqual(completion["review_sha256"], __import__("hashlib").sha256(review_path.read_bytes()).hexdigest())

    def test_completed_worker_is_kept_running_until_fresh_gate_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo = root / "repo"
            papers = root / "papers"
            worktrees = root / "worktrees"
            repo.mkdir()
            papers.mkdir()
            (papers / "Demo Paper.pdf").write_bytes(b"paper")
            self._init_framework_repo(repo)
            plan = create_batch_manifest(
                batch_id="worker-gate",
                papers_root=papers,
                repository_root=repo,
                base_ref="HEAD",
                selections=[
                    PaperSelectionArtifact(
                        paper=discover_test_papers(papers)[0],
                        selected_factors=[self._factor("FactorA")],
                    )
                ],
                worktree_root=worktrees,
            ).runs[0]
            prepare_test_worktree(plan)
            prepare_run_harness(plan)
            record_worker_started(plan, worker_task_id="terra-worker-gated")
            failed = AgentHarnessRunAssessment(
                complete=False,
                worktree=plan.worktree,
                expected_factors=["FactorA"],
                defects=["[tests] missing formula coverage"],
                earliest_invalid_stage="implementation_tests",
                repair_actions=["Add tests."],
            )
            passed = AgentHarnessRunAssessment(
                complete=True,
                worktree=plan.worktree,
                expected_factors=["FactorA"],
            )
            with patch(
                "research_core.factor_lab.paper_reproduction.agent_harness_review.assess_agent_harness_run",
                side_effect=[failed, passed],
            ):
                with self.assertRaisesRegex(ValueError, "keep the worker active"):
                    record_worker_stopped(plan, outcome="completed")
                self.assertEqual(plan.status, "running")
                self.assertEqual(plan.worker_gate_pass_count, 1)
                record_worker_stopped(plan, outcome="completed")

            self.assertEqual(plan.status, "worker_stopped")
            self.assertEqual(plan.worker_gate_pass_count, 2)
            gate_history = sorted((Path(plan.control_root) / "worker_gate_assessments").glob("*.json"))
            self.assertEqual(len(gate_history), 2)
            latest = json.loads((Path(plan.control_root) / "worker_completion_gate.json").read_text(encoding="utf-8"))
            self.assertTrue(latest["complete"])

    def _init_framework_repo(self, repo: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Paper Tests"], cwd=repo, check=True)
        files = {
            ".agents/skills/paper-factor-reproduction/SKILL.md": (
                "---\nname: paper-factor-reproduction\n"
                "description: Run paper factor reproduction tests.\n---\n# Reproduce\n"
            ),
            ".agents/skills/paper-reproduction-review/SKILL.md": (
                "---\nname: paper-reproduction-review\n"
                "description: Review paper reproduction artifacts.\n---\n# Review\n"
            ),
            "research_core/factor_lab/paper_reproduction/agent_harness.py": "# tracked harness marker\n",
        }
        for relative, content in files.items():
            path = repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "framework"], cwd=repo, check=True)

    def _paper(self, path: Path):
        from research_core.factor_lab.paper_reproduction.paper_autotest import PaperCandidate

        return PaperCandidate(paper_id="demo-paper", path=str(path), size_bytes=5, sha256="abc")

    def _factor(self, name: str) -> FactorSelectionEvidence:
        return FactorSelectionEvidence(
            factor_name=name,
            formula_source_location="p. 3, formula 1",
            truth_source_location="p. 8, table 2",
            paper_metrics={"rank_ic_mean": 0.05},
            formula_fields=["close", "volume"],
            formula_clarity=5,
            local_data_support=5,
            evaluator_support=5,
            performance_strength=4,
            compute_feasibility=4,
            selection_reason="Clear formula, strong IC, and direct local inputs.",
        )


if __name__ == "__main__":
    unittest.main()
