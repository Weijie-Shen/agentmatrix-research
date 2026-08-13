from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from research_core.factor_lab.paper_reproduction import (
    ICAnalysisPaperExtraction,
    ExtractedFactorDefinition,
    ExtractedICProtocol,
    ExtractedICTruthSource,
    ExtractedMetricDefinition,
    ExtractedOperationPipeline,
    ExtractedSemanticRequirement,
    ExtractedUniverseProtocol,
    PaperReproductionPipelineState,
    build_paper_evaluation_plan,
    build_paper_reproduction_report,
    compare_evaluation_bundle_to_paper_truth,
    export_paper_extraction,
    load_paper_extraction,
    normalize_extraction_to_specs,
    validate_paper_extraction,
)
from research_core.factor_lab.runtime import FactorLabWorkspaceConfig
from research_core.factor_lab.paper_reproduction.evaluation_execution import (
    EvaluationBundle,
    EvaluationExecutionRecord,
)
from research_core.factor_lab.paper_reproduction.data_validation import assess_evaluation_case_support
from research_core.factor_lab.paper_reproduction.evaluators import get_generic_evaluator_capabilities
from research_core.factor_lab.paper_reproduction.extraction import infer_reported_ratio_denominator


def ic_v2_fixture() -> ICAnalysisPaperExtraction:
    factors = [
        ExtractedFactorDefinition(
            factor_id="alpha_a",
            paper_label="AlphaA",
            formula="-correlation(rank(OPEN), rank(VOLUME), 5)",
            required_semantic_fields=["daily_open", "daily_volume"],
            native_frequency="daily",
            parameters={"window": 5},
            evidence={"page": 5, "table": "formula"},
        ),
        ExtractedFactorDefinition(
            factor_id="alpha_b",
            paper_label="AlphaB",
            formula="-correlation(rank(CLOSE), rank(VOLUME), 5)",
            required_semantic_fields=["daily_close", "daily_volume"],
            native_frequency="daily",
            parameters={"window": 5},
            evidence={"page": 5, "table": "formula"},
        ),
    ]
    semantics = [
        ExtractedSemanticRequirement("daily_open", "market_data", "daily_open_price"),
        ExtractedSemanticRequirement("daily_close", "market_data", "daily_close_price"),
        ExtractedSemanticRequirement("daily_volume", "market_data", "daily_trading_volume"),
        ExtractedSemanticRequirement("forward_stock_return", "evaluation_input", "stock_return_over_following_h_trading_days"),
        ExtractedSemanticRequirement(
            "industry_citic_level_1",
            "classification",
            "industry_membership",
            {"taxonomy_family": "CITIC", "taxonomy_level": 1, "taxonomy_revision": "not_specified"},
        ),
        ExtractedSemanticRequirement(
            "total_company_market_cap_close",
            "capitalization",
            "total_company_market_cap",
            {"cap_basis": "total_company", "observation_time": "close"},
        ),
        ExtractedSemanticRequirement("st_or_pt_status", "evaluation_universe_filter", "ST_or_PT_status_at_signal_date"),
        ExtractedSemanticRequirement(
            "next_day_suspension_status",
            "evaluation_universe_filter",
            "full_day_suspension_on_next_exchange_trading_day",
        ),
    ]
    universe = ExtractedUniverseProtocol(
        universe_protocol_id="all_a_evaluation_filtered",
        calculation_universe={
            "base_universe": "all_A_shares",
            "retain_full_valid_security_history": True,
            "source": "inferred",
        },
        evaluation_universe={"base_universe": "all_A_shares", "source": "explicit"},
        filters=[
            {
                "filter_name": "exclude_st_pt",
                "paper_field": "st_or_pt_status",
                "application_stage": "factor_cross_section",
                "effective_date_rule": "signal_date_t",
                "operator": "falsy",
                "missing_policy": "exclude",
                "source": "explicit",
            },
            {
                "filter_name": "exclude_next_day_suspension",
                "paper_field": "next_day_suspension_status",
                "application_stage": "factor_cross_section",
                "effective_date_rule": "next_trading_day_t_plus_1",
                "operator": "falsy",
                "missing_policy": "exclude",
                "source": "explicit",
            },
        ],
    )
    raw = ExtractedOperationPipeline(
        "unneutralized",
        "unneutralized",
        [
            {"order": 1, "type": "winsorize", "target": "factor", "threshold_mad": 5},
            {"order": 2, "type": "standardize", "target": "factor"},
            {"order": 3, "type": "missing_values", "method": "do_not_impute"},
        ],
    )
    neutral = ExtractedOperationPipeline(
        "industry_cap_neutralized",
        "industry plus total cap",
        [
            {"order": 1, "type": "winsorize", "target": "factor", "threshold_mad": 5},
            {
                "order": 2,
                "type": "transform",
                "target": "total_company_market_cap_close",
                "method": "natural_log",
                "output": "log_total_company_market_cap",
            },
            {
                "order": 3,
                "type": "neutralize",
                "method": "cross_sectional_OLS_residual",
                "controls": ["industry_citic_level_1", "log_total_company_market_cap"],
            },
            {"order": 4, "type": "standardize", "target": "factor_residual"},
            {"order": 5, "type": "missing_values", "method": "do_not_impute"},
        ],
    )
    metric_definitions = [
        ExtractedMetricDefinition("rank_ic_mean", "Rank IC mean", "mean", "decimal_correlation"),
        ExtractedMetricDefinition("rank_ic_std", "Rank IC std", "standard deviation", "decimal_correlation"),
        ExtractedMetricDefinition("ic_ir", "IC_IR", "mean divided by std", "ratio"),
        ExtractedMetricDefinition("rank_ic_positive_ratio", "IC>0", "positive ratio", "decimal_fraction"),
    ]
    results = {
        "alpha_a": {"rank_ic_mean": 0.04, "rank_ic_std": 0.05, "ic_ir": 0.8, "rank_ic_positive_ratio": 0.75},
        "alpha_b": {"rank_ic_mean": 0.03, "rank_ic_std": 0.05, "ic_ir": 0.6, "rank_ic_positive_ratio": 0.70},
    }
    return ICAnalysisPaperExtraction(
        artifact_id="fixture_ic_v2",
        paper={
            "paper_id": "fixture_ic_v2",
            "title": "IC v2 fixture",
            "publisher": "Factor Lab",
            "publication_date": "2026-08-13",
            "authors": [{"name": "Fixture"}],
        },
        factor_family_name="fixture_ic_v2",
        factor_definitions=factors,
        semantic_requirements=semantics,
        universe_protocols=[universe],
        sample_periods=[{"sample_period_id": "full", "start": "2020-01-01", "end": "2020-12-31"}],
        operation_pipelines=[raw, neutral],
        metric_definitions=metric_definitions,
        ic_analysis_contract={
            "evaluator_type": "ic_analysis",
            "contract_id": "spearman_daily",
            "cross_sectional_statistic": "Spearman rank correlation",
            "universe_protocol_id": "all_a_evaluation_filtered",
            "signal_frequency": "every_trading_day",
        },
        ic_protocols=[
            ExtractedICProtocol("raw_h20", "full", "unneutralized", 20, "all_a_evaluation_filtered", "spearman_daily"),
            ExtractedICProtocol(
                "neutral_h20",
                "full",
                "industry_cap_neutralized",
                20,
                "all_a_evaluation_filtered",
                "spearman_daily",
            ),
        ],
        truth_sources=[
            ExtractedICTruthSource(
                "table_raw_h20",
                "raw_h20",
                {"page": 10, "table": "Table 1", "column_group": "raw"},
                ["rank_ic_mean", "rank_ic_std", "ic_ir", "rank_ic_positive_ratio"],
                results,
            ),
            ExtractedICTruthSource(
                "table_neutral_h20",
                "neutral_h20",
                {"page": 11, "table": "Table 2", "column_group": "neutral"},
                ["ic_ir"],
                {"alpha_a": {"ic_ir": 1.1}, "alpha_b": {"ic_ir": 0.9}},
            ),
        ],
        truth_selection_policy={
            "support_assessment_stage": 3,
            "selection_stage": 6,
            "selection_unit": "factor_id plus truth_source_id",
            "forbidden_selection_evidence": ["reported metric closeness", "best reproduced IC"],
        },
        scope={"factor_ids": ["alpha_a", "alpha_b"], "supported_evaluator_types": ["ic_analysis"]},
    )


class ICAnalysisExtractionV2Test(unittest.TestCase):
    def test_infers_unique_shared_observation_denominator_from_printed_ratios(self) -> None:
        self.assertEqual(
            infer_reported_ratio_denominator([0.2671, 0.1781, 0.1644, 0.1575]),
            146,
        )
        self.assertIsNone(infer_reported_ratio_denominator([0.25, 0.50]))

    def test_validates_round_trips_and_keeps_shared_registries(self) -> None:
        extraction = ic_v2_fixture()
        validation = validate_paper_extraction(extraction)
        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(validation.diagnostics["protocol_count"], 2)
        self.assertEqual(validation.diagnostics["result_row_count"], 4)

        with tempfile.TemporaryDirectory() as tmp:
            workspace = FactorLabWorkspaceConfig(data_root=Path(tmp) / "data", runtime_root=Path(tmp) / "runtime")
            loaded = load_paper_extraction(export_paper_extraction(extraction, config=workspace))
        self.assertIsInstance(loaded, ICAnalysisPaperExtraction)
        self.assertEqual(len(loaded.truth_sources), 2)
        self.assertEqual(loaded.truth_sources[0].reported_results["alpha_a"]["ic_ir"], 0.8)

    def test_extensible_registries_strictly_round_trip_nested_attributes(self) -> None:
        extraction = ic_v2_fixture()
        extraction.semantic_requirements[0].attributes = {
            "price_basis": "backward_adjusted",
            "timing": {"observation": "close", "lag_days": 0},
        }
        extraction.operation_pipelines[0].attributes = {
            "applies_to": ["alpha_a", "alpha_b"],
            "missing_policy": {"method": "drop_cross_section"},
        }
        extraction.metric_definitions[0].attributes = {
            "aggregation": "arithmetic_mean",
            "eligibility": {"minimum_cross_sections": 2},
        }
        extraction.ic_protocols[0].attributes = {
            "signal_timing": "close_t",
            "return_alignment": {"start": "t_plus_1", "end": "t_plus_20"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            workspace = FactorLabWorkspaceConfig(data_root=Path(tmp) / "data", runtime_root=Path(tmp) / "runtime")
            loaded = load_paper_extraction(export_paper_extraction(extraction, config=workspace))

        self.assertEqual(loaded, extraction)
        self.assertEqual(loaded.semantic_requirements, extraction.semantic_requirements)
        self.assertEqual(loaded.operation_pipelines, extraction.operation_pipelines)
        self.assertEqual(loaded.metric_definitions, extraction.metric_definitions)
        self.assertEqual(loaded.ic_protocols, extraction.ic_protocols)

    def test_rejects_runtime_binding_and_calculation_stage_future_filter(self) -> None:
        extraction = ic_v2_fixture()
        extraction.semantic_requirements[0].attributes["resolved_field"] = "open"
        result = validate_paper_extraction(extraction)
        self.assertFalse(result.valid)
        self.assertTrue(any("forbidden in extraction" in error for error in result.errors))

        extraction = ic_v2_fixture()
        extraction.universe_protocols[0].filters[1]["application_stage"] = "factor_time_series"
        extraction.universe_protocols[0].filters[1]["source"] = "inferred"
        result = validate_paper_extraction(extraction)
        self.assertFalse(result.valid)
        self.assertTrue(any("future-state filter" in error for error in result.errors))

    def test_stage2_projects_candidates_without_selecting_or_defaulting(self) -> None:
        specs = normalize_extraction_to_specs(ic_v2_fixture(), version="v2")
        self.assertEqual(len(specs), 2)
        first = specs[0]
        self.assertEqual(first.semantic_required_fields, ["daily_open", "daily_volume"])
        self.assertEqual(first.evaluation_case_refs, ["table_raw_h20", "table_neutral_h20"])
        self.assertEqual(first.metadata["selected_truth_sources"], [])
        self.assertEqual(first.metadata["truth_source_summary"]["support_assessment_stage"], 3)
        self.assertEqual(first.metadata["truth_source_summary"]["selection_stage"], 6)
        raw_case, neutral_case = first.metadata["truth_sources"]
        self.assertEqual(raw_case["defaulted_transform_steps"], [])
        self.assertEqual(raw_case["paper_protocol_refs"]["protocol_id"], "raw_h20")
        self.assertEqual(
            [step["method"] for step in raw_case["transform_spec"]["steps"]],
            ["median_mad", "cross_section_zscore", "do_not_fill"],
        )
        controls = neutral_case["neutralization_spec"]["controls"]
        self.assertEqual([item["paper_field"] for item in controls], ["industry_citic_level_1", "total_company_market_cap_close"])
        self.assertEqual(controls[1]["transforms"][0]["method"], "log")

    def test_stage2_honors_natural_month_protocol_attribute(self) -> None:
        extraction = ic_v2_fixture()
        extraction.ic_protocols[0].attributes["forward_horizon_unit"] = "natural_month"

        case = normalize_extraction_to_specs(extraction, version="v2")[0].metadata["truth_sources"][0]

        self.assertEqual(case["evaluation_spec"]["return_horizon_unit"], "natural_month")
        self.assertEqual(case["evaluation_spec"]["return_col"], "forward_return_20m")
        self.assertEqual(case["required_data"]["evaluation"], ["forward_return_20m"])

    def test_stage2_preserves_explicit_zero_fill_and_absolute_ir_semantics(self) -> None:
        extraction = ic_v2_fixture()
        for pipeline in extraction.operation_pipelines:
            for operation in pipeline.operations:
                if operation.get("type") == "missing_values":
                    operation["method"] = "fill_mean_to_zero"
        for metric in extraction.metric_definitions:
            if metric.metric_id == "ic_ir":
                metric.definition = "absolute value of IC mean divided by IC standard deviation"

        truth_cases = normalize_extraction_to_specs(extraction, version="v2")[0].metadata["truth_sources"]

        self.assertEqual(
            truth_cases[0]["transform_spec"]["steps"][2]["method"],
            "fill_zero",
        )
        self.assertEqual(
            truth_cases[1]["neutralization_spec"]["output_transforms"][1]["method"],
            "fill_zero",
        )
        self.assertTrue(all(case["evaluation_spec"]["ic_ir_convention"] == "absolute" for case in truth_cases))

    def test_stage3_and_stage6_choose_one_supported_truth_without_metric_peeking(self) -> None:
        specs = normalize_extraction_to_specs(ic_v2_fixture(), version="v2")
        profile = {
            "columns": [
                "date",
                "code",
                "open",
                "close",
                "volume",
                "forward_return_20d",
                "is_st",
                "next_is_suspended",
                "industry",
                "market_cap",
            ],
            "missingness": {
                "open": 0.0,
                "close": 0.0,
                "volume": 0.0,
                "forward_return_20d": 0.0,
                "is_st": 0.0,
                "next_is_suspended": 0.0,
                "industry": 0.0,
                "market_cap": 0.0,
            },
            "date_min": "2020-01-01",
            "date_max": "2020-12-31",
            "conventions": {
                "industry_classification": {
                    "source": "sws",
                    "level": 1,
                    "interval_rule": "start_date <= date < cancel_date",
                },
                "market_cap_fields": ["market_cap"],
            },
        }
        plan = build_paper_evaluation_plan(
            specs,
            data_profiles={spec.factor_name: copy.deepcopy(profile) for spec in specs},
        )
        for factor_plan in plan.factor_plans:
            self.assertEqual(len(factor_plan.assessed_evaluation_cases), 2)
            self.assertEqual(len(factor_plan.selected_evaluation_cases), 1)
            selected = factor_plan.selected_evaluation_cases[0]
            self.assertEqual(selected["truth_source_id"], "table_raw_h20")
            self.assertIn("reported metric values were not used", selected["selection_reason"])
            self.assertEqual(
                [item["application_stage"] for item in selected["resolved_protocol"]["universe_protocol"]["filters"]],
                ["factor_cross_section", "factor_cross_section"],
            )
            self.assertTrue(
                selected["resolved_protocol"]["universe_protocol"]["calculation_universe"][
                    "retain_full_valid_security_history"
                ]
            )

    def test_neutralized_v2_controls_keep_exact_semantic_support(self) -> None:
        neutral_case = normalize_extraction_to_specs(ic_v2_fixture(), version="v2")[0].metadata["truth_sources"][1]
        profile = {
            "columns": [
                "date",
                "code",
                "open",
                "volume",
                "forward_return_20d",
                "st_or_pt_status",
                "next_day_suspension_status",
                "industry",
                "market_cap",
            ],
            "missingness": {
                "open": 0.0,
                "volume": 0.0,
                "forward_return_20d": 0.0,
                "st_or_pt_status": 0.0,
                "next_day_suspension_status": 0.0,
                "industry": 0.0,
                "market_cap": 0.0,
            },
            "date_min": "2020-01-01",
            "date_max": "2020-12-31",
            "conventions": {
                "industry_classification": {
                    "source": "citics",
                    "level": 1,
                    "interval_rule": "start_date <= date < cancel_date",
                },
                "market_cap_fields": ["market_cap"],
            },
        }

        assessment = assess_evaluation_case_support(
            neutral_case,
            profile,
            get_generic_evaluator_capabilities(),
        )
        controls = [item for item in assessment.requirement_results if item.category == "transform_control"]

        self.assertEqual(len(controls), 2)
        self.assertTrue(all(item.semantic_availability == "exactly_available" for item in controls))
        self.assertTrue(all(item.relationship == "exact_alias" for item in controls))
        self.assertEqual({item.available_value for item in controls}, {"industry", "market_cap"})
        self.assertEqual(assessment.comparability, "exact")

    def test_stage6_refuses_v2_selection_without_stage3_profile(self) -> None:
        plan = build_paper_evaluation_plan(normalize_extraction_to_specs(ic_v2_fixture()))
        for factor_plan in plan.factor_plans:
            self.assertEqual(factor_plan.selected_evaluation_cases, [])
            self.assertTrue(factor_plan.unsupported_evaluation_cases)
            self.assertTrue(
                all(item["lifecycle_state"] == "insufficient_data" for item in factor_plan.unsupported_evaluation_cases)
            )

    def test_pipeline_state_accepts_v2_paper_identity(self) -> None:
        extraction = ic_v2_fixture()
        state = PaperReproductionPipelineState.from_extraction(extraction, job_id="v2-job")

        self.assertEqual(state.job_id, "v2-job")
        self.assertEqual(state.paper_id, "fixture_ic_v2")
        self.assertEqual(state.family_name, extraction.factor_family_name)

    def test_stage7_matches_selected_v2_factor_result_row(self) -> None:
        extraction = ic_v2_fixture()
        record = EvaluationExecutionRecord(
            execution_id="execution-v2",
            truth_case_id="table_raw_h20",
            source_truth_id="table_raw_h20",
            factor_id="fixture_alpha_a",
            factor_name="alpha_a",
            scenario_id="qfq",
            evaluator_id="generic_ic_v1",
            lifecycle_state="executed",
            implementation_source_hash="source",
            factor_specification_hash="spec",
            data_snapshot_hash="data",
            comparability="exact",
            truth_match_eligible_metrics=["rank_ic_mean", "rank_ic_std", "ic_ir", "rank_ic_positive_ratio"],
            evaluator_output={
                "metrics": {
                    "rank_ic_mean": 0.04,
                    "rank_ic_std": 0.05,
                    "ic_ir": 0.8,
                    "rank_ic_positive_ratio": 0.75,
                }
            },
        )
        bundle = EvaluationBundle(
            library="fixture_ic_v2",
            scenario_id="qfq",
            data_snapshot_hash="data",
            implementation_artifact={},
            records=[record],
        )

        results = compare_evaluation_bundle_to_paper_truth(bundle, extraction)

        self.assertEqual(results["alpha_a"][0].status, "exact_match")

    def test_stage8_report_reads_v2_shared_evidence(self) -> None:
        extraction = ic_v2_fixture()
        specs = normalize_extraction_to_specs(extraction)
        report = build_paper_reproduction_report(
            job_id="v2-report",
            extraction=extraction,
            specs=specs,
            evaluation_plan=build_paper_evaluation_plan(specs),
        )

        self.assertEqual(report["paper"]["extraction_schema_version"], "paper_extraction.ic_analysis.v2")
        self.assertEqual([item["factor_name"] for item in report["factors"]], ["alpha_a", "alpha_b"])
        self.assertTrue(all(item["truth_sources"] for item in report["factors"]))


if __name__ == "__main__":
    unittest.main()
