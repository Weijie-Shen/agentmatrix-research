from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research_core.factor_lab.paper_reproduction.agent_harness import (
    PaperReproductionAgentHarnessRequest,
    prepare_agent_harness_bundle,
)
from research_core.factor_lab.runtime import FactorLabWorkspaceConfig


class PaperReproductionAgentHarnessTest(unittest.TestCase):
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
                    golden_json_path="research_core/factor_lab/paper_reproduction/golden/huatai_alpha3_13_15.json",
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
            self.assertEqual(metadata["selected_factors"], ["Alpha3", "Alpha13", "Alpha15"])
            self.assertEqual(metadata["required_price_adjustment_views"], ["qfq", "hfq"])
            self.assertIn(str(copied_skill), prompt)
            self.assertIn("Load and follow the bundled skill", prompt)
            self.assertIn("Use paper-reported `evaluation_results` only as truth", prompt)
            self.assertIn("load_recommended_paper_panels(test_end_date=...)", prompt)
            self.assertIn("testing-end-anchored QFQ", prompt)
            self.assertIn("initial-baseline HFQ", prompt)

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
