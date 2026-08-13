from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research_core.factor_lab.paper_reproduction.extraction import (
    ExtractedFactor,
    ExtractedTruthSource,
    PaperExtraction,
    export_paper_extraction,
    load_paper_extraction,
    summarize_factor_truth_sources,
    validate_paper_extraction,
)
from research_core.factor_lab.runtime import FactorLabWorkspaceConfig


class PaperExtractionTest(unittest.TestCase):
    def _valid_extraction(self) -> PaperExtraction:
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
                    universe="liquid common stocks",
                    sample_period="2020-01-01 to 2020-12-31",
                    description="Daily close-to-open return.",
                    truth_sources=[
                        ExtractedTruthSource(
                            truth_id="pv_close_to_open_table_3_evaluation",
                            truth_type="evaluation_results",
                            description="Table 3 reports rank IC and IR for the factor.",
                            source_location="Table 3",
                            sample_period="2020-01-01 to 2020-12-31",
                            universe="liquid common stocks",
                            frequency="day",
                            evaluation_method="daily rank IC and long-short quintile spread",
                            evaluation_family="ic_analysis",
                            evaluation_spec={"return_horizon": 1, "ic_type": "spearman_rank_ic"},
                            transform_spec={"steps": [{"name": "adjust_prices", "source": "fixture"}]},
                            required_data={"formula": ["open", "close"], "evaluation": ["forward_return_1d"]},
                            metrics={"rank_ic_mean": 0.042, "rank_ic_ir": 0.31},
                        ),
                    ],
                ),
                ExtractedFactor(
                    factor_name="pv_volume_momentum_5d",
                    formula="volume / mean(volume, 5) - 1",
                    required_fields=["volume"],
                    frequency="day",
                    universe="liquid common stocks",
                    sample_period="2020-01-01 to 2020-12-31",
                    description="Volume relative to its 5-day moving average.",
                    parameters={"window": 5},
                    truth_sources=[
                        ExtractedTruthSource(
                            truth_id="pv_volume_table_3_evaluation",
                            truth_type="evaluation_results",
                            description="Table 3 reports evaluation metrics.",
                            source_location="Table 3",
                            sample_period="2020-01-01 to 2020-12-31",
                            universe="liquid common stocks",
                            frequency="day",
                            evaluation_method="daily rank IC and long-short quintile spread",
                            evaluation_family="ic_analysis",
                            evaluation_spec={"return_horizon": 1, "ic_type": "spearman_rank_ic"},
                            transform_spec={"steps": [{"name": "sort_panel", "source": "fixture"}]},
                            required_data={"formula": ["volume"], "evaluation": ["forward_return_1d"]},
                            metrics={"rank_ic_mean": 0.018, "rank_ic_ir": 0.12},
                        ),
                    ],
                ),
            ],
        )

    def test_valid_extraction_passes_gate_checks_and_exports_artifact(self) -> None:
        extraction = self._valid_extraction()
        validation = validate_paper_extraction(extraction)

        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(validation.status, "implemented")
        self.assertEqual(validation.errors, [])
        self.assertEqual(validation.warnings, [])

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = FactorLabWorkspaceConfig(data_root=root / "data", runtime_root=root / "runtime")
            path = export_paper_extraction(extraction, config=workspace)

            self.assertEqual(path, workspace.runtime_root / "paper_specs" / "simple_price_volume_demo_extracted.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["paper_id"], "simple_price_volume_demo")
            self.assertEqual(payload["target_factors"][0]["factor_name"], "pv_close_to_open")
            self.assertEqual(payload["target_factors"][0]["truth_sources"][0]["truth_type"], "evaluation_results")

            loaded = load_paper_extraction(path)
            self.assertEqual(loaded.paper_id, extraction.paper_id)
            self.assertEqual(loaded.target_factors[1].parameters["window"], 5)
            self.assertEqual(loaded.target_factors[1].truth_sources[0].metrics["rank_ic_ir"], 0.12)

    def test_validation_fails_when_factor_formula_or_required_fields_are_missing(self) -> None:
        extraction = self._valid_extraction()
        extraction.target_factors[0].formula = ""
        extraction.target_factors[1].required_fields = []

        validation = validate_paper_extraction(extraction)

        self.assertFalse(validation.valid)
        self.assertEqual(validation.status, "needs_human_review")
        self.assertIn("target_factors[0].formula is required", validation.errors)
        self.assertIn("target_factors[1].required_fields must not be empty", validation.errors)

    def test_factor_missing_evaluation_truth_source_waits_for_human_review(self) -> None:
        extraction = self._valid_extraction()
        extraction.target_factors[0].truth_sources = []

        validation = validate_paper_extraction(extraction)

        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(validation.status, "needs_human_review")
        self.assertIn("target_factors[0].truth_sources is missing; paper evaluation results are required", validation.warnings)

    def test_formula_required_fields_warn_on_family_wide_raw_field_superset(self) -> None:
        extraction = self._valid_extraction()
        extraction.target_factors[0].required_fields = ["open", "high", "low", "close", "vwap", "volume"]

        validation = validate_paper_extraction(extraction)

        self.assertEqual(validation.status, "needs_human_review")
        self.assertTrue(any("keep formula requirements factor-specific" in item for item in validation.warnings))

    def test_multiple_evaluation_truth_sources_require_selection_rule(self) -> None:
        extraction = self._valid_extraction()
        extraction.target_factors[1].truth_sources.append(
            ExtractedTruthSource(
                truth_id="pv_volume_table_4_ten_year_evaluation",
                truth_type="evaluation_results",
                description="Table 4 reports the same metric over a ten-year sample.",
                source_location="Table 4",
                sample_period="2010-01-01 to 2020-12-31",
                universe="liquid common stocks",
                frequency="day",
                evaluation_method="daily rank IC and long-short quintile spread",
                metrics={"rank_ic_mean": 0.014, "rank_ic_ir": 0.09},
            )
        )

        validation = validate_paper_extraction(extraction)
        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(validation.status, "needs_human_review")
        self.assertIn("target_factors[1].truth_sources has multiple entries but no truth_selection_rule", validation.warnings)

        extraction.target_factors[1].truth_selection_rule = "Use the truth source with the longest sample period covered by available data."
        validation = validate_paper_extraction(extraction)
        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(validation.status, "implemented")

    def test_selected_truth_source_ids_can_resolve_multiple_alternative_sources(self) -> None:
        extraction = self._valid_extraction()
        extraction.target_factors[1].truth_sources.append(
            ExtractedTruthSource(
                truth_id="pv_volume_table_4_ten_year_evaluation",
                truth_type="evaluation_results",
                description="Table 4 reports the same metric over a ten-year sample.",
                source_location="Table 4",
                sample_period="2010-01-01 to 2020-12-31",
                universe="liquid common stocks",
                frequency="day",
                evaluation_method="daily rank IC and long-short quintile spread",
                metrics={"rank_ic_mean": 0.014, "rank_ic_ir": 0.09},
            )
        )
        extraction.target_factors[1].selected_truth_source_ids = ["pv_volume_table_4_ten_year_evaluation"]

        validation = validate_paper_extraction(extraction)

        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(validation.status, "implemented")

    def test_selected_truth_source_ids_must_reference_existing_truth_sources(self) -> None:
        extraction = self._valid_extraction()
        extraction.target_factors[0].selected_truth_source_ids = ["missing_truth_id"]

        validation = validate_paper_extraction(extraction)

        self.assertFalse(validation.valid)
        self.assertEqual(validation.status, "needs_human_review")
        self.assertIn(
            "target_factors[0].selected_truth_source_ids contains unknown truth_id: missing_truth_id",
            validation.errors,
        )

    def test_truth_source_summary_reports_available_and_selected_evaluation_truth(self) -> None:
        factor = self._valid_extraction().target_factors[0]
        factor.selected_truth_source_ids = ["pv_close_to_open_table_3_evaluation"]

        summary = summarize_factor_truth_sources(factor)

        self.assertEqual(summary["available_truth_count"], 1)
        self.assertEqual(summary["available_truth_types"], ["evaluation_results"])
        self.assertEqual(summary["selected_truth_ids"], ["pv_close_to_open_table_3_evaluation"])
        self.assertEqual(summary["selected_truth_types"], ["evaluation_results"])
        self.assertTrue(summary["has_evaluation_truth"])

    def test_unrecognized_evaluation_metrics_and_missing_source_location_need_review(self) -> None:
        extraction = self._valid_extraction()
        truth = extraction.target_factors[1].truth_sources[0]
        truth.source_location = ""
        truth.metrics = {"custom_score": 0.12}

        validation = validate_paper_extraction(extraction)

        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(validation.status, "needs_human_review")
        self.assertIn("target_factors[1].truth_sources[0].source_location is missing", validation.warnings)
        self.assertIn(
            "target_factors[1].truth_sources[0].metrics has no recognized evaluation metric names",
            validation.warnings,
        )

    def test_selected_truth_source_ids_must_not_duplicate(self) -> None:
        extraction = self._valid_extraction()
        extraction.target_factors[0].selected_truth_source_ids = [
            "pv_close_to_open_table_3_evaluation",
            "pv_close_to_open_table_3_evaluation",
        ]

        validation = validate_paper_extraction(extraction)

        self.assertFalse(validation.valid)
        self.assertIn(
            "target_factors[0].selected_truth_source_ids contains duplicated truth_id: pv_close_to_open_table_3_evaluation",
            validation.errors,
        )

    def test_ambiguities_are_classified_for_pipeline_report(self) -> None:
        extraction = self._valid_extraction()
        extraction.target_factors[0].ambiguous_or_missing_information = [
            "Formula rank direction is ambiguous.",
            "Field mapping for volume adjustment is unclear.",
            "Evaluation uses IC but does not state whether it is Pearson or rank IC.",
        ]

        validation = validate_paper_extraction(extraction)

        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(validation.status, "needs_human_review")
        self.assertEqual(
            validation.diagnostics["ambiguities_by_category"],
            {
                "formula": ["target_factors[0]: Formula rank direction is ambiguous."],
                "field_mapping": ["target_factors[0]: Field mapping for volume adjustment is unclear."],
                "evaluation": [
                    "target_factors[0]: Evaluation uses IC but does not state whether it is Pearson or rank IC."
                ],
                "other": [],
            },
        )

    def test_missing_frequency_is_allowed_only_when_recorded_as_ambiguity(self) -> None:
        extraction = self._valid_extraction()
        extraction.target_factors[0].frequency = ""
        extraction.target_factors[0].ambiguous_or_missing_information = []

        validation = validate_paper_extraction(extraction)
        self.assertFalse(validation.valid)
        self.assertIn(
            "target_factors[0].frequency is missing and must be recorded in factor ambiguous_or_missing_information",
            validation.errors,
        )

        extraction.target_factors[0].ambiguous_or_missing_information = [
            "Paper does not specify the frequency for pv_close_to_open."
        ]
        validation = validate_paper_extraction(extraction)
        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(validation.status, "needs_human_review")


    def test_known_limitations_do_not_force_human_review_when_evaluation_truth_exists(self) -> None:
        extraction = self._valid_extraction()
        extraction.target_factors[0].known_limitations = [
            "Paper reports aggregate IC/backtest metrics but not daily factor values or per-date IC series."
        ]

        validation = validate_paper_extraction(extraction)

        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(validation.status, "implemented")
        self.assertEqual(validation.warnings, [])
        self.assertEqual(
            validation.diagnostics["known_limitations"],
            [
                "target_factors[0]: Paper reports aggregate IC/backtest metrics but not daily factor values or per-date IC series."
            ],
        )

    def test_factor_keeps_formula_fields_separate_from_evaluation_case_required_data(self) -> None:
        extraction = self._valid_extraction()
        factor = extraction.target_factors[0]
        factor.required_fields = ["open", "volume"]
        factor.truth_sources[0].required_data = {
            "formula": ["open", "volume"],
            "evaluation": ["forward_return_20d", "vwap"],
            "controls": ["industry", "market_cap"],
        }

        validation = validate_paper_extraction(extraction)

        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(factor.required_fields, ["open", "volume"])
        self.assertEqual(factor.truth_sources[0].required_data["evaluation"], ["forward_return_20d", "vwap"])
        self.assertEqual(factor.truth_sources[0].required_data["controls"], ["industry", "market_cap"])

    def test_broad_truth_source_location_warns_without_invalidating_extraction(self) -> None:
        extraction = self._valid_extraction()
        truth = extraction.target_factors[0].truth_sources[0]
        truth.source_location = "Table 52; Table 14; Table 36"

        validation = validate_paper_extraction(extraction)

        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(validation.status, "needs_human_review")
        self.assertIn(
            "target_factors[0].truth_sources[0].source_location appears to reference multiple tables/figures; split truth sources by metric group and evaluation setting",
            validation.warnings,
        )

    def test_vwap_execution_note_is_evaluation_ambiguity_not_formula_field_mapping(self) -> None:
        extraction = self._valid_extraction()
        extraction.target_factors[0].ambiguous_or_missing_information = [
            "Layered backtest rebalances next trading day at VWAP; confirm amount/volume units if deriving execution price."
        ]

        validation = validate_paper_extraction(extraction)

        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(
            validation.diagnostics["ambiguities_by_category"]["evaluation"],
            [
                "target_factors[0]: Layered backtest rebalances next trading day at VWAP; confirm amount/volume units if deriving execution price."
            ],
        )
        self.assertEqual(validation.diagnostics["ambiguities_by_category"]["field_mapping"], [])


    def test_truth_source_carries_evaluation_case_specs(self) -> None:
        extraction = self._valid_extraction()
        truth = extraction.target_factors[0].truth_sources[0]
        truth.evaluation_family = "ic_analysis"
        truth.evaluation_spec = {
            "return_horizon": 20,
            "return_horizon_unit": "trading_day",
            "ic_type": "spearman_rank_ic",
        }
        truth.transform_spec = {
            "steps": [
                {"name": "median_mad_winsorization", "source": "explicit"},
                {"name": "industry_market_cap_neutralization", "source": "explicit"},
                {"name": "zscore_standardization", "source": "explicit"},
            ]
        }
        truth.required_data = {
            "formula": ["open", "close"],
            "evaluation": ["forward_return_20d"],
            "controls": ["industry", "market_cap"],
        }

        validation = validate_paper_extraction(extraction)

        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(truth.evaluation_family, "ic_analysis")
        self.assertEqual(truth.evaluation_spec["return_horizon"], 20)
        self.assertEqual(truth.transform_spec["steps"][1]["name"], "industry_market_cap_neutralization")
        self.assertEqual(truth.required_data["controls"], ["industry", "market_cap"])

    def test_structured_neutralization_and_universe_protocol_validate_and_round_trip(self) -> None:
        extraction = self._valid_extraction()
        truth = extraction.target_factors[0].truth_sources[0]
        truth.neutralization_spec = {
            "method": "cross_sectional_regression_residual",
            "source": "explicit",
            "source_location": "Section 3.2",
            "confidence": 1.0,
            "dependent_variable": {
                "field": "factor_value",
                "source": "explicit",
                "transforms": [{"method": "median_mad", "threshold": 5, "source": "explicit"}],
            },
            "controls": [
                {
                    "semantic_role": "size_control",
                    "paper_field": "market_cap",
                    "encoding": "continuous",
                    "source": "explicit",
                    "transforms": [
                        {"method": "log", "source": "explicit"},
                        {"method": "cross_section_zscore", "source": "explicit"},
                    ],
                }
            ],
            "output_transforms": [{"method": "cross_section_zscore", "source": "explicit"}],
        }
        truth.universe_protocol = {
            "calculation_universe": {"description": "full valid history", "source": "defaulted"},
            "evaluation_universe": {"description": "exclude ST/PT", "source": "explicit"},
            "filters": [
                {
                    "filter_name": "exclude_st_pt",
                    "paper_field": "st_or_pt_status",
                    "application_stage": "factor_cross_section",
                    "effective_date_rule": "signal_date_t",
                    "operator": "falsy",
                    "source": "explicit",
                }
            ],
        }

        validation = validate_paper_extraction(extraction)

        self.assertTrue(validation.valid, validation.errors)
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = FactorLabWorkspaceConfig(data_root=Path(tmp_dir) / "data", runtime_root=Path(tmp_dir) / "runtime")
            loaded = load_paper_extraction(export_paper_extraction(extraction, config=workspace))
        loaded_truth = loaded.target_factors[0].truth_sources[0]
        self.assertEqual(loaded_truth.neutralization_spec["controls"][0]["transforms"][0]["method"], "log")
        self.assertEqual(loaded_truth.universe_protocol["filters"][0]["application_stage"], "factor_cross_section")

    def test_future_filter_before_calculation_requires_explicit_paper_support(self) -> None:
        extraction = self._valid_extraction()
        extraction.target_factors[0].truth_sources[0].universe_protocol = {
            "filters": [
                {
                    "filter_name": "bad_future_filter",
                    "paper_field": "next_day_suspension_status",
                    "application_stage": "factor_time_series",
                    "effective_date_rule": "t+1",
                    "source": "defaulted",
                }
            ]
        }

        validation = validate_paper_extraction(extraction)

        self.assertFalse(validation.valid)
        self.assertTrue(any("future-state filter" in error for error in validation.errors))


if __name__ == "__main__":
    unittest.main()
