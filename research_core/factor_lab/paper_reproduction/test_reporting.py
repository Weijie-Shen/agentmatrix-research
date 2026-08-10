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
                    selected_evaluation_cases=[
                        {
                            "truth_id": "table_3_eval",
                            "evaluation_family": "ic_analysis",
                            "defaulted_transform_steps": ["winsorization"],
                        }
                    ],
                    skipped_evaluation_cases=[
                        {
                            "truth_id": "table_4_portfolio",
                            "evaluation_family": "layered_portfolio_backtest",
                            "skip_reason": "known_method_available",
                        }
                    ],
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
        self.assertEqual(report["factors"][0]["selected_evaluation_cases"][0]["truth_id"], "table_3_eval")
        self.assertEqual(report["factors"][0]["skipped_evaluation_cases"][0]["skip_reason"], "known_method_available")
        self.assertEqual(report["factors"][0]["defaulted_transform_assumptions"], ["winsorization"])
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
        self.assertIn("Selected Evaluation Methods", markdown)
        self.assertIn("Defaulted Transform Assumptions", markdown)

    def test_report_preserves_canonical_execution_and_universe_filter_provenance(self) -> None:
        bundle = {
            "schema_version": "evaluation_bundle/v1",
            "records": [
                {
                    "execution_id": "execution-1",
                    "factor_name": "paper_alpha_1",
                    "lifecycle_state": "executed",
                    "evaluator_output": {"execution_mode": "canonical_plan_executor"},
                    "universe_diagnostics": {
                        "removed_rows": 2,
                        "applied_filters": [
                            {
                                "filter_name": "exclude_st_pt",
                                "application_stage": "factor_cross_section",
                                "removed_rows": 2,
                            }
                        ],
                    },
                }
            ],
        }

        report = build_paper_reproduction_report(
            job_id="paper-demo-job",
            extraction=self._extraction(),
            specs=[self._spec()],
            evaluation_bundle=bundle,
        )
        markdown = render_paper_reproduction_report_markdown(report)

        self.assertEqual(report["summary"]["evaluation_execution_counts"], {"executed": 1})
        self.assertEqual(report["summary"]["evaluation_filter_rows_removed"], 2)
        self.assertEqual(report["factors"][0]["evaluation_executions"][0]["execution_id"], "execution-1")
        self.assertIn("Filter `exclude_st_pt` at `factor_cross_section` removed 2 rows", markdown)

    def test_report_separates_resource_adaptations_from_methodological_deviations(self) -> None:
        bundle = {
            "schema_version": "evaluation_bundle/v2",
            "records": [],
            "resource_preflight": {
                "execution_mode": "resource_bounded_projected",
                "memory_budget_bytes": 4_000_000_000,
                "estimated_projected_peak_bytes": 3_000_000_000,
            },
            "resource_telemetry": {"measured_process_peak_rss_bytes": 2_500_000_000},
            "resource_adaptations": ["required-column projection"],
            "methodological_deviations": [],
            "requested_execution": {"sample": {"start_date": "2010-01-04", "end_date": "2019-04-30"}},
            "executed_execution": {"sample": {"start_date": "2010-01-04", "end_date": "2019-04-30"}},
            "raw_factor_before_evaluation_filters": True,
        }

        report = build_paper_reproduction_report(
            job_id="paper-demo-job",
            extraction=self._extraction(),
            specs=[self._spec()],
            evaluation_bundle=bundle,
        )
        markdown = render_paper_reproduction_report_markdown(report)

        self.assertEqual(report["summary"]["evaluation_execution_mode"], "resource_bounded_projected")
        self.assertEqual(report["summary"]["resource_adaptation_count"], 1)
        self.assertEqual(report["summary"]["methodological_deviation_count"], 0)
        self.assertTrue(report["summary"]["raw_factor_before_evaluation_filters"])
        self.assertIn("Methodology-preserving resource adaptation: required-column projection", markdown)
        self.assertIn("Methodological deviations: none", markdown)

    def test_report_counts_only_executed_selected_truth_results(self) -> None:
        extraction = self._extraction()
        evaluation_plan = PaperEvaluationPlan(
            library="PaperDemo",
            status="ready_for_evaluation_with_limitations",
            factor_plans=[
                PaperFactorEvaluationPlan(
                    factor_name="paper_alpha_1",
                    status="ready_for_evaluation_with_limitations",
                    selected_evaluation_cases=[
                        {
                            "truth_id": "table_3_eval",
                            "source_truth_id": "table_3_eval",
                            "evaluation_family": "ic_analysis",
                        }
                    ],
                    unsupported_evaluation_cases=[
                        {
                            "truth_id": "portfolio",
                            "evaluation_family": "layered_portfolio_backtest",
                            "lifecycle_state": "unsupported_evaluator",
                        }
                    ],
                )
            ],
        )
        truth_results = {
            "paper_alpha_1": [
                {"truth_id": "table_3_eval", "status": "approximately_consistent", "lifecycle_state": "executed"},
                {"truth_id": "portfolio", "status": "not_evaluated", "lifecycle_state": "unsupported_evaluator"},
            ]
        }

        report = build_paper_reproduction_report(
            job_id="paper-demo-job",
            extraction=extraction,
            specs=[self._spec()],
            evaluation_plan=evaluation_plan,
            truth_results=truth_results,
        )

        counts = report["summary"]["truth_case_counts"]
        self.assertEqual(counts["truth_cases_executed"], 1)
        self.assertEqual(counts["truth_cases_deferred"], 1)
        self.assertEqual(counts["truth_cases_matched"], 1)
        self.assertEqual(report["summary"]["truth_match_pass_rate"], "1/1")

    def test_report_preserves_canonical_requirement_and_replacement_provenance(self) -> None:
        requirement = {
            "requirement": "free_float_market_cap",
            "category": "regression_weight",
            "available_value": "market_cap",
            "availability": "available",
            "semantic_availability": "replacement_available",
            "relationship": "proxy_substitute",
            "execution_ready": True,
            "pipeline_blocking": False,
        }
        replacement = {
            "required_semantic_role": "regression_weight",
            "paper_definition": "free_float_market_cap",
            "replacement_field": "market_cap",
            "relationship": "proxy_substitute",
            "status": "accepted_proxy",
            "accepted": True,
            "execution_ready": True,
            "replacement_reason": "Free-float capitalization is unavailable.",
            "pipeline_blocking": False,
        }
        assessed_case = {
            "truth_id": "table_3_eval",
            "source_truth_id": "table_3_eval",
            "support_assessment": {
                "requirement_results": [requirement],
                "replacement_records": [replacement],
                "case_executable": True,
            },
        }
        evaluation_plan = PaperEvaluationPlan(
            library="PaperDemo",
            status="ready_for_evaluation_with_limitations",
            factor_plans=[
                PaperFactorEvaluationPlan(
                    factor_name="paper_alpha_1",
                    status="ready_for_evaluation_with_limitations",
                    assessed_evaluation_cases=[assessed_case],
                    selected_evaluation_cases=[
                        {
                            **assessed_case,
                            "comparability": "proxy",
                            "case_executable": True,
                        }
                    ],
                )
            ],
        )

        report = build_paper_reproduction_report(
            job_id="paper-demo-job",
            extraction=self._extraction(),
            specs=[self._spec()],
            evaluation_plan=evaluation_plan,
        )

        factor = report["factors"][0]
        self.assertEqual(factor["data_requirement_assessments"][0]["semantic_availability"], "replacement_available")
        self.assertEqual(factor["data_replacements"][0], {**replacement, "truth_id": "table_3_eval"})
        self.assertEqual(report["summary"]["data_requirement_counts"]["replacement_available"], 1)
        self.assertEqual(report["summary"]["data_replacement_count"], 1)
        self.assertIn("accepted_proxy", render_paper_reproduction_report_markdown(report))

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
