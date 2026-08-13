from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

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
            record_worker_stopped(plan, outcome="completed", details={"message": "fixture done"})

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
            record_independent_review(
                plan,
                {"verdict": "incomplete", "blocking_defects": ["fixture"], "limitations": []},
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
                    "independently_reviewed",
                    "incomplete",
                    "cleaned",
                ],
            )
            branch_check = subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{plan.branch}"], cwd=repo, check=False
            )
            self.assertNotEqual(branch_check.returncode, 0)

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
