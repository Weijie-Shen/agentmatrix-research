from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research_core.factor_lab.paper_reproduction.extraction import ExtractedFactor, ExtractedTruthSource, PaperExtraction
from research_core.factor_lab.paper_reproduction.pipeline import (
    PaperReproductionPipelineState,
    PaperReproductionStage,
    export_pipeline_state,
)
from research_core.factor_lab.runtime import FactorLabWorkspaceConfig


class PaperReproductionPipelineTest(unittest.TestCase):
    def _extraction(self) -> PaperExtraction:
        return PaperExtraction(
            paper_id="simple_price_volume_demo",
            title="Simple Price-Volume Signals",
            authors=["Factor Lab Team"],
            source="Factor Lab fixture",
            year=2026,
            factor_family_name="SimplePV",
            target_factors=[
                ExtractedFactor(
                    factor_name="pv_close_to_open",
                    formula="(close - open) / open",
                    required_fields=["open", "close"],
                    frequency="day",
                    truth_sources=[
                        ExtractedTruthSource(
                            truth_id="table_3",
                            truth_type="evaluation_results",
                            source_location="Table 3",
                            evaluation_method="daily rank IC",
                            metrics={"rank_ic_mean": 0.042},
                        )
                    ],
                )
            ],
        )

    def test_pipeline_state_records_stage_order_and_blocks_after_human_review(self) -> None:
        state = PaperReproductionPipelineState.from_extraction(self._extraction())
        state.mark_stage("paper_extraction", "passed", artifact_paths=["runtime/factor_lab/paper_specs/demo.json"])
        state.mark_stage("spec_normalization", "passed", artifact_paths=["runtime/factor_lab/specs/simplepv_specs.json"])
        state.mark_stage("input_dataframe_validation", "needs_human_review", summary="insufficient history")

        self.assertEqual([stage.name for stage in state.stages], [stage.value for stage in PaperReproductionStage])
        self.assertEqual(state.overall_status, "needs_human_review")
        self.assertEqual(state.next_stage, "factor_implementation")
        self.assertFalse(state.ready_for_stage("factor_implementation"))

    def test_pipeline_state_exports_json_artifact(self) -> None:
        state = PaperReproductionPipelineState.from_extraction(self._extraction(), job_id="paper-demo")
        state.mark_stage("paper_extraction", "passed")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = FactorLabWorkspaceConfig(data_root=root / "data", runtime_root=root / "runtime")
            path = export_pipeline_state(state, config=workspace)

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["job_id"], "paper-demo")
            self.assertEqual(payload["paper_id"], "simple_price_volume_demo")
            self.assertEqual(payload["stages"][0]["name"], "paper_extraction")


if __name__ == "__main__":
    unittest.main()
