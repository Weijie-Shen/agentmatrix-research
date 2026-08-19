from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research_core.factor_lab.paper_reproduction.agent_harness import (
    PaperReproductionAgentHarnessRequest,
    default_skill_path,
    prepare_agent_harness_bundle,
)
from research_core.factor_lab.runtime import FactorLabWorkspaceConfig


class PaperReproductionAgentHarnessTest(unittest.TestCase):
    def test_default_skill_path_uses_repository_scoped_codex_skill(self) -> None:
        path = default_skill_path()
        self.assertEqual(path.name, "SKILL.md")
        self.assertEqual(path.parent.name, "paper-factor-reproduction")
        self.assertEqual(path.parent.parent.parent.name, ".agents")

    def test_harness_bundle_copies_skill_and_writes_prompt_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            skill_path = root / "source_skill" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_text = "# Paper Factor Reproduction\n\nUse evaluation_results truth.\n"
            skill_path.write_text(skill_text, encoding="utf-8")
            workspace = FactorLabWorkspaceConfig(data_root=root / "data", runtime_root=root / "runtime")

            bundle = prepare_agent_harness_bundle(
                PaperReproductionAgentHarnessRequest(
                    harness_id="huatai-alpha3-test",
                    working_directory="/tmp/agentmatrix-paper-test",
                    paper_id="huatai_mass_technical_factors_20190521",
                    paper_path="docs/huatai.pdf",
                    selected_factors=["Alpha3", "Alpha13", "Alpha15"],
                    skill_path=str(skill_path),
                    notes=["Fresh agent must use the bundled skill."],
                ),
                config=workspace,
            )

            copied_skill = Path(bundle.skill_copy_path)
            metadata = json.loads(Path(bundle.metadata_path).read_text(encoding="utf-8"))
            prompt = Path(bundle.prompt_path).read_text(encoding="utf-8")

            self.assertEqual(copied_skill.read_text(encoding="utf-8"), skill_text)
            self.assertEqual(bundle.skill_sha256, hashlib.sha256(skill_text.encode("utf-8")).hexdigest())
            self.assertEqual(metadata["skill_copy_path"], str(copied_skill))
            self.assertEqual(metadata["skill_sha256"], bundle.skill_sha256)
            self.assertEqual(metadata["agent_platform"], "codex")
            self.assertEqual(metadata["skill_bundle_sha256"], bundle.skill_bundle_sha256)
            self.assertEqual(metadata["skill_bundle_paths"], bundle.skill_bundle_paths)
            self.assertEqual(bundle.skill_bundle_paths, [str(copied_skill)])
            self.assertEqual(metadata["selected_factors"], ["Alpha3", "Alpha13", "Alpha15"])
            self.assertEqual(metadata["required_price_adjustment_views"], ["qfq", "hfq"])
            self.assertEqual(metadata["required_extraction_schema_version"], "paper_extraction.ic_recipe.v3")
            self.assertEqual(metadata["required_global_evaluation_policy_id"], "china_a_share_ic_evaluation_v1")
            self.assertEqual(metadata["truth_selection_stage"], 1)
            self.assertIn(str(copied_skill), prompt)
            self.assertIn("Load and follow the bundled skill", prompt)
            self.assertIn("Skill bundle SHA-256", prompt)
            self.assertIn("repository-scoped Codex stage skills", prompt)
            self.assertIn("Use paper-reported `evaluation_results` only as truth", prompt)
            self.assertIn("load_recommended_daily_panel(..., price_view=\"qfq\"", prompt)
            self.assertIn("IndustryClassificationSelection", prompt)
            self.assertIn("market_cap_fields", prompt)
            self.assertIn("PIT financial statements", prompt)
            self.assertIn("monthly versus daily index weights", prompt)
            self.assertIn("`$rqdata-fetch-reference`", prompt)
            self.assertIn("release one scenario before loading the next", prompt)
            self.assertIn("resource preflight", prompt)
            self.assertIn("testing-end-anchored QFQ", prompt)
            self.assertIn("initial-baseline HFQ", prompt)
            self.assertIn("Exact aliases, constructed equivalents, accepted proxies, and rejected substitutes", prompt)
            self.assertIn("`FactorImplementationArtifact`", prompt)
            self.assertIn("`execute_evaluation_plan(...)`", prompt)
            self.assertIn("`export_paper_truth_matches(...)`", prompt)
            self.assertIn("`finalize_paper_reproduction_report(...)`", prompt)
            self.assertIn("`scientific_process_lease(worktree, process_name=...)`", prompt)
            self.assertIn("full calculation panel separate from evaluation inputs", prompt)
            self.assertIn("truth-source-owned declarative IC recipes", prompt)
            self.assertIn("Select exactly one truth source", prompt)
            self.assertIn("without truth reselection", prompt)
            self.assertIn("one ordered recipe", prompt)
            self.assertIn("china_a_share_ic_evaluation_v1", prompt)
            self.assertIn("do not apply log when `transform.natural_log` is already materialized", prompt)
            self.assertNotIn("paper_extraction.ic_analysis.v2`; legacy extraction", prompt)
            self.assertIn("persistent command session", prompt)
            self.assertIn("yield deadline is not process termination", prompt)
            self.assertIn("deterministic completion gate", prompt)
            self.assertIn("agent_harness_review", prompt)
            self.assertIn("earliest_invalid_stage", prompt)
            self.assertIn("--factor Alpha3", metadata["deterministic_gate_command"])
            self.assertEqual(metadata["deterministic_gate_max_repair_passes"], 3)

    def test_missing_skill_path_fails_before_writing_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = FactorLabWorkspaceConfig(data_root=root / "data", runtime_root=root / "runtime")

            with self.assertRaises(FileNotFoundError):
                prepare_agent_harness_bundle(
                    PaperReproductionAgentHarnessRequest(
                        harness_id="missing-skill-test",
                        working_directory="/tmp/agentmatrix-paper-test",
                        selected_factors=["Alpha3"],
                        skill_path=str(root / "missing" / "SKILL.md"),
                    ),
                    config=workspace,
                )

            self.assertFalse((workspace.runtime_root / "agent_harness" / "missing-skill-test" / "fresh_agent_prompt.md").exists())


if __name__ == "__main__":
    unittest.main()
