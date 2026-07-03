from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from contracts.factor_research import FactorResearchSpec
from research_core.factor_lab.paper_reproduction.extraction import ExtractedFactor, ExtractedTruthSource, PaperExtraction
from research_core.factor_lab.paper_reproduction.paper_evaluation import PaperEvaluationPlan, PaperFactorEvaluationPlan
from research_core.factor_lab.paper_reproduction.pipeline import PaperReproductionPipelineState
from research_core.factor_lab.paper_reproduction.reporting import (
    build_paper_reproduction_report,
    export_paper_reproduction_report,
    render_paper_reproduction_report_markdown,
)
from research_core.factor_lab.runtime import FactorLabWorkspaceConfig


class PaperReproductionReportingTest(unittest.TestCase):
    def _extraction(self) -> PaperExtraction:
        return PaperExtraction(
            paper_id="paper_demo",
            title="Demo Paper Factors",
            authors=["Researcher A"],
            source="Demo Journal",
            year=2026,
            factor_family_name="PaperDemo",
            target_factors=[
                ExtractedFactor(
                    factor_name="paper_alpha_1",
                    formula="close / open - 1",
                    required_fields=["open", "close"],
                    frequency="day",
                    truth_sources=[
                        ExtractedTruthSource(
                            truth_id="table_3_eval",
                            truth_type="evaluation_results",
                            source_location="Table 3",
                            evaluation_method="daily rank IC using 1-day forward returns",
                            evaluation_family="ic_analysis",
                            evaluation_spec={"return_horizon": 1, "ic_type": "spearman_rank_ic"},
                            required_data={"formula": ["open", "close"], "evaluation": ["forward_return_1d"]},
                            metrics={"rank_ic_mean": 0.04},
                        )
                    ],
                )
            ],
        )

    def _spec(self) -> FactorResearchSpec:
        return FactorResearchSpec(
            factor_name="paper_alpha_1",
            library="PaperDemo",
            version="v0.1",
            source_document="Demo Paper Factors (Demo Journal, 2026)",
            formula="close / open - 1",
            required_fields=["open", "close"],
            metadata={
                "status": "planned",
                "truth_source_summary": {"available_truth_count": 1, "selected_truth_types": ["evaluation_results"]},
                "factor_ambiguities_by_category": {"formula": [], "field_mapping": [], "evaluation": [], "other": []},
                "data_requirements": {
                    "formula_required_fields": ["open", "close"],
                    "evaluation_required_fields": ["forward_return_1d"],
                },
                "known_limitations": ["Paper reports aggregate evaluation metrics only."],
            },
        )

    def test_build_report_summarizes_pipeline_specs_evaluation_and_truth(self) -> None:
        extraction = self._extraction()
        state = PaperReproductionPipelineState.from_extraction(extraction, job_id="paper-demo-job")
        state.mark_stage("paper_extraction", "passed")
        state.mark_stage("spec_normalization", "passed")
        state.mark_stage("evaluation", "passed")
        evaluation_plan = PaperEvaluationPlan(
            library="PaperDemo",
            status="ready_for_evaluation",
            factor_plans=[
                PaperFactorEvaluationPlan(
                    factor_name="paper_alpha_1",
                    status="ready_for_evaluation",
                    evaluation_method="daily rank IC using 1-day forward returns",
                    required_metrics=["rank_ic_mean"],
                    evaluation_features=["rank_ic"],
                    forward_return_periods=[1],
                    truth_source_ids=["table_3_eval"],
                )
            ],
        )
        truth_results = {
            "paper_alpha_1": [
                {
                    "truth_id": "table_3_eval",
                    "status": "acceptable",
                    "diagnostics": {"quality": "approximately_consistent"},
                }
            ]
        }

        report = build_paper_reproduction_report(
            job_id="paper-demo-job",
            extraction=extraction,
            specs=[self._spec()],
            pipeline_state=state,
            evaluation_plan=evaluation_plan,
            truth_results=truth_results,
            artifacts={"input_panel": "runtime/factor_lab/frames/panel.parquet"},
        )

        self.assertEqual(report["paper"]["paper_id"], "paper_demo")
        self.assertEqual(report["summary"]["overall_status"], "in_progress")
        self.assertEqual(report["summary"]["factor_count"], 1)
        self.assertEqual(report["factors"][0]["truth_results"][0]["status"], "acceptable")
        self.assertEqual(report["factors"][0]["data_requirements"]["evaluation_required_fields"], ["forward_return_1d"])
        self.assertEqual(report["factors"][0]["evaluation_cases"][0]["evaluation_family"], "ic_analysis")
        self.assertEqual(report["factors"][0]["known_limitations"], ["Paper reports aggregate evaluation metrics only."])
        self.assertIn("input_panel", report["artifacts"])

    def test_markdown_render_includes_status_factors_and_no_overclaiming_note(self) -> None:
        report = build_paper_reproduction_report(
            job_id="paper-demo-job",
            extraction=self._extraction(),
            specs=[self._spec()],
        )

        markdown = render_paper_reproduction_report_markdown(report)

        self.assertIn("# Paper Factor Reproduction Report", markdown)
        self.assertIn("paper_alpha_1", markdown)
        self.assertIn("Do not claim full reproduction", markdown)
        self.assertIn("Evaluation Truth", markdown)

    def test_export_report_writes_json_and_markdown(self) -> None:
        report = build_paper_reproduction_report(
            job_id="paper-demo-job",
            extraction=self._extraction(),
            specs=[self._spec()],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = FactorLabWorkspaceConfig(data_root=Path(tmp_dir) / "data", runtime_root=Path(tmp_dir) / "runtime")
            paths = export_paper_reproduction_report(report, config=workspace)

            self.assertTrue(paths["json"].exists())
            self.assertTrue(paths["markdown"].exists())
            payload = json.loads(paths["json"].read_text(encoding="utf-8"))
            self.assertEqual(payload["job_id"], "paper-demo-job")
            self.assertIn("paper_alpha_1", paths["markdown"].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
