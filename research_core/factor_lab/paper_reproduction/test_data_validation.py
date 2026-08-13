from __future__ import annotations

import unittest

import pandas as pd

from research_core.factor_lab.paper_reproduction.data_validation import (
    DataFrameValidationRequest,
    FieldRelationship,
    assess_evaluation_case_support,
    build_data_profile,
    materialize_forward_return,
    validate_input_frame,
)
from research_core.factor_lab.paper_reproduction.evaluators import get_generic_evaluator_capabilities
from research_core.factor_lab.paper_reproduction.extraction import ExtractedFactor


class PaperInputDataValidationTest(unittest.TestCase):
    def _factor(self) -> ExtractedFactor:
        return ExtractedFactor(
            factor_name="pv_close_to_open",
            formula="(close - open) / open",
            required_fields=["open", "close"],
            frequency="day",
            sample_period="2020-01-01 to 2020-01-04",
            universe="demo stocks",
        )

    def _valid_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-01", "2020-01-02"]),
                "code": ["AAA", "AAA", "BBB", "BBB"],
                "open": [10.0, 10.2, 20.0, 19.8],
                "close": [10.1, 10.0, 19.9, 20.2],
            }
        )

    def test_valid_input_frame_passes_required_columns_unique_keys_and_sorting(self) -> None:
        result = validate_input_frame(self._valid_frame(), DataFrameValidationRequest.from_factor(self._factor()))

        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.status, "passed")
        self.assertEqual(result.diagnostics["row_count"], 4)
        self.assertEqual(result.diagnostics["date_count"], 2)
        self.assertEqual(result.diagnostics["code_count"], 2)
        self.assertEqual(result.diagnostics["missing_required_columns"], [])

    def test_missing_required_factor_field_fails(self) -> None:
        frame = self._valid_frame().drop(columns=["close"])

        result = validate_input_frame(frame, DataFrameValidationRequest.from_factor(self._factor()))

        self.assertFalse(result.valid)
        self.assertEqual(result.status, "failed")
        self.assertIn("missing required columns: close", result.errors)

    def test_duplicate_date_code_keys_fail(self) -> None:
        frame = pd.concat([self._valid_frame(), self._valid_frame().iloc[[0]]], ignore_index=True)

        result = validate_input_frame(frame, DataFrameValidationRequest.from_factor(self._factor()))

        self.assertFalse(result.valid)
        self.assertIn("duplicate date-code rows: 2", result.errors)

    def test_unsorted_frame_returns_human_review_warning_not_failure(self) -> None:
        frame = self._valid_frame().iloc[[1, 0, 2, 3]].reset_index(drop=True)

        result = validate_input_frame(frame, DataFrameValidationRequest.from_factor(self._factor()))

        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.status, "needs_human_review")
        self.assertIn("frame is not sorted by code,date", result.warnings)

    def test_insufficient_history_for_rolling_window_needs_human_review(self) -> None:
        factor = self._factor()
        factor.parameters = {"window": 5}

        result = validate_input_frame(self._valid_frame(), DataFrameValidationRequest.from_factor(factor))

        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.status, "needs_human_review")
        self.assertIn("max history per code 2 is shorter than required lookback 5", result.warnings)

    def test_build_data_profile_records_coverage_missingness_and_duplicates(self) -> None:
        frame = pd.concat([self._valid_frame(), self._valid_frame().iloc[[0]]], ignore_index=True)
        frame.loc[0, "close"] = None

        profile = build_data_profile(frame, source_id="unit_panel")

        self.assertEqual(profile.source_id, "unit_panel")
        self.assertEqual(profile.row_count, 5)
        self.assertEqual(profile.date_min, "2020-01-01")
        self.assertGreater(profile.missingness["close"], 0)
        self.assertEqual(profile.duplicate_key_count, 2)
        self.assertIn("close", profile.field_coverage)

    def test_materialize_forward_return_uses_future_security_observation_and_preserves_order(self) -> None:
        frame = self._valid_frame().iloc[[2, 0, 3, 1]].copy()

        result = materialize_forward_return(frame, 1)

        self.assertEqual(result[["date", "code"]].to_dict("records"), frame[["date", "code"]].to_dict("records"))
        first_a = result.loc[(result["code"] == "AAA") & (result["date"] == pd.Timestamp("2020-01-01")), "forward_return_1d"].iloc[0]
        first_b = result.loc[(result["code"] == "BBB") & (result["date"] == pd.Timestamp("2020-01-01")), "forward_return_1d"].iloc[0]
        self.assertAlmostEqual(first_a, 10.0 / 10.1 - 1)
        self.assertAlmostEqual(first_b, 20.2 / 19.9 - 1)
        self.assertTrue(result.groupby("code")["forward_return_1d"].apply(lambda values: values.isna().sum() == 1).all())

    def test_assess_evaluation_case_support_records_missing_evaluation_field_as_proxy(self) -> None:
        profile = build_data_profile(self._valid_frame(), source_id="unit_panel")
        truth_source = {
            "truth_id": "table_52",
            "evaluation_family": "ic_regression",
            "evaluation_method": "WLS rank IC regression",
            "required_data": {"evaluation": ["forward_return_20d"], "regression_weight": ["free_float_market_cap"]},
            "metrics": {"rank_ic_mean": 0.04, "t_abs_mean": 2.0},
        }

        assessment = assess_evaluation_case_support(
            truth_source,
            profile,
            get_generic_evaluator_capabilities(),
        )

        self.assertEqual(assessment.comparability, "proxy")
        self.assertLess(assessment.support_score, 1.0)
        self.assertTrue(any(item.requirement == "free_float_market_cap" for item in assessment.requirement_results))
        self.assertTrue(assessment.deviations)
        self.assertIn("t_abs_mean", assessment.diagnostic_only_metrics)
        self.assertEqual(assessment.replacement_records, [])

    def test_inferred_operation_is_disclosed_and_downgrades_comparability(self) -> None:
        profile = build_data_profile(materialize_forward_return(self._valid_frame(), 1), source_id="unit_panel")
        truth_source = {
            "truth_id": "table_inferred_method",
            "evaluation_family": "ic_analysis",
            "evaluation_method": "Pearson IC",
            "required_data": {"evaluation": ["forward_return_1d"]},
            "operation_pipeline": {
                "operations": [
                    {
                        "order": 1,
                        "type": "transform",
                        "target": "market_cap",
                        "method": "log",
                        "source": "inferred",
                    }
                ]
            },
            "metrics": {"ic_mean": 0.04},
        }

        assessment = assess_evaluation_case_support(
            truth_source,
            profile,
            get_generic_evaluator_capabilities(),
        )

        self.assertEqual(assessment.comparability, "proxy")
        self.assertEqual(assessment.score_components["inferred_methodology_count"], 1.0)
        self.assertTrue(any(item["category"] == "methodology_inference" for item in assessment.deviations))
        self.assertIn("ic_mean", assessment.truth_match_eligible_metrics)

    def test_assess_evaluation_case_support_resolves_aliases_sample_and_universe_filters(self) -> None:
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(["2017-01-03", "2019-04-30"]),
                "code": ["AAA", "AAA"],
                "forward_return_t20": [0.01, 0.02],
                "market_cap": [100.0, 110.0],
                "log_market_cap": [4.6, 4.7],
                "is_st": [0, 0],
                "next_is_suspended": [0, 0],
            }
        )
        profile = build_data_profile(frame, source_id="huatai_like")
        truth_source = {
            "truth_id": "table_52",
            "sample_period": "2010-01-04 to 2019-04-30",
            "universe": "All A-shares; exclude ST/PT and next-day suspended stocks",
            "evaluation_family": "ic_regression",
            "evaluation_method": "T=20 OLS rank IC regression",
            "evaluation_spec": {"return_horizon": 20, "return_col": "forward_return_20d", "regression_type": "ols"},
            "required_data": {
                "evaluation": ["forward_return_20d"],
                "controls": ["market_cap_or_log_market_cap"],
                "filters": ["st_or_pt_status", "next_day_suspension_status"],
            },
            "metrics": {"rank_ic_mean": 0.04, "t_abs_mean": 2.0},
        }

        assessment = assess_evaluation_case_support(truth_source, profile, get_generic_evaluator_capabilities())
        results = {item.requirement: item for item in assessment.requirement_results}

        self.assertEqual(results["forward_return_20d"].available_value, "forward_return_t20")
        self.assertEqual(results["market_cap_or_log_market_cap"].available_value, "log_market_cap")
        self.assertEqual(results["st_or_pt_status"].available_value, "is_st")
        self.assertEqual(results["next_day_suspension_status"].available_value, "next_is_suspended")
        self.assertEqual(results["sample_period"].availability, "partially_available")
        self.assertEqual(assessment.comparability, "proxy")
        self.assertEqual(results["st_or_pt_status"].relationship, "proxy_substitute")
        self.assertEqual(results["next_day_suspension_status"].relationship, "exact_alias")

    def test_a_share_universe_without_exclusion_text_does_not_invent_status_filters(self) -> None:
        frame = pd.DataFrame(
            {
                "date": ["2020-01-02", "2020-01-02"],
                "code": ["AAA", "BBB"],
                "forward_return_1d": [0.01, -0.01],
            }
        )
        truth_source = {
            "truth_id": "all_a_share_no_filter",
            "universe": "All A-shares",
            "evaluation_family": "ic_analysis",
            "evaluation_method": "rank IC",
            "evaluation_spec": {"return_col": "forward_return_1d"},
            "metrics": {"rank_ic_mean": 0.04},
        }

        assessment = assess_evaluation_case_support(
            truth_source,
            build_data_profile(frame),
            get_generic_evaluator_capabilities(),
        )

        requirements = {item.requirement for item in assessment.requirement_results}
        self.assertNotIn("st_or_pt_status", requirements)
        self.assertNotIn("next_day_suspension_status", requirements)

    def test_proxy_substitute_is_reported_and_downgrades_only_affected_metrics(self) -> None:
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(["2020-01-02", "2020-01-03"]),
                "code": ["AAA", "AAA"],
                "forward_return_1d": [0.01, 0.02],
                "market_cap": [100.0, 110.0],
            }
        )
        truth_source = {
            "truth_id": "wls_proxy",
            "evaluation_family": "ic_regression",
            "evaluation_method": "WLS rank IC regression",
            "evaluation_spec": {
                "return_col": "forward_return_1d",
                "regression_type": "wls",
                "weight_col": "free_float_market_cap",
            },
            "required_data": {
                "evaluation": ["forward_return_1d"],
                "regression_weight": ["free_float_market_cap"],
            },
            "metrics": {"rank_ic_mean": 0.04, "t_abs_mean": 2.0},
        }

        assessment = assess_evaluation_case_support(
            truth_source,
            build_data_profile(frame),
            get_generic_evaluator_capabilities(),
        )
        weights = [
            item
            for item in assessment.requirement_results
            if item.category == "regression_weight" and item.requirement == "free_float_market_cap"
        ]

        self.assertEqual(len(weights), 1)
        self.assertEqual(weights[0].source_contexts, ["required_data.regression_weight", "evaluation_spec.regression_weight"])
        self.assertEqual(weights[0].relationship, "proxy_substitute")
        self.assertEqual(weights[0].semantic_availability, "replacement_available")
        self.assertEqual(weights[0].available_value, "market_cap")
        self.assertFalse(weights[0].pipeline_blocking)
        self.assertTrue(assessment.case_executable)
        self.assertEqual(assessment.comparability, "proxy")
        self.assertIn("rank_ic_mean", assessment.truth_match_eligible_metrics)
        self.assertIn("t_abs_mean", assessment.diagnostic_only_metrics)
        self.assertEqual(assessment.replacement_records[0]["status"], "accepted_proxy")
        self.assertEqual(assessment.replacement_records[0]["replacement_field"], "market_cap")

    def test_declared_derivation_is_constructible_but_not_an_executable_field(self) -> None:
        frame = pd.DataFrame(
            {
                "date": ["2020-01-02"],
                "code": ["AAA"],
                "forward_return_1d": [0.01],
                "free_float_market_cap": [100.0],
            }
        )
        truth_source = {
            "truth_id": "derived_weight",
            "evaluation_family": "ic_regression",
            "evaluation_method": "WLS rank IC regression",
            "evaluation_spec": {
                "return_col": "forward_return_1d",
                "regression_type": "wls",
                "weight_col": "sqrt_free_float_market_cap",
            },
            "required_data": {"evaluation": ["forward_return_1d"]},
            "metrics": {"t_abs_mean": 2.0},
        }

        assessment = assess_evaluation_case_support(
            truth_source,
            build_data_profile(frame),
            get_generic_evaluator_capabilities(),
        )
        weight = next(item for item in assessment.requirement_results if item.category == "regression_weight")

        self.assertEqual(weight.relationship, "derived_equivalent")
        self.assertEqual(weight.semantic_availability, "constructible")
        self.assertIsNone(weight.available_value)
        self.assertFalse(weight.execution_ready)
        self.assertEqual(assessment.replacement_records[0]["status"], "constructible_not_materialized")

    def test_materialized_derivation_is_executable_and_keeps_lineage(self) -> None:
        frame = pd.DataFrame(
            {
                "date": ["2020-01-02"],
                "code": ["AAA"],
                "forward_return_1d": [0.01],
                "sqrt_free_float_market_cap": [10.0],
            }
        )
        profile = build_data_profile(
            frame,
            derived_fields=[
                {
                    "field": "sqrt_free_float_market_cap",
                    "sources": ["free_float_market_cap"],
                    "formula": "sqrt(free_float_market_cap)",
                    "source": "data_profile",
                }
            ],
        )
        truth_source = {
            "truth_id": "materialized_weight",
            "evaluation_family": "ic_regression",
            "evaluation_method": "WLS rank IC regression",
            "evaluation_spec": {
                "return_col": "forward_return_1d",
                "regression_type": "wls",
                "weight_col": "sqrt_free_float_market_cap",
            },
            "metrics": {"t_abs_mean": 2.0},
        }

        assessment = assess_evaluation_case_support(
            truth_source,
            profile,
            get_generic_evaluator_capabilities(),
        )
        weight = next(item for item in assessment.requirement_results if item.category == "regression_weight")

        self.assertTrue(weight.execution_ready)
        self.assertEqual(weight.relationship, "derived_equivalent")
        self.assertEqual(weight.available_value, "sqrt_free_float_market_cap")
        self.assertEqual(assessment.comparability, "exact")
        self.assertEqual(assessment.replacement_records[0]["status"], "constructed_equivalent")
        self.assertEqual(assessment.replacement_records[0]["derivation"]["formula"], "sqrt(free_float_market_cap)")
        self.assertEqual(assessment.deviations, [])

    def test_unsupported_timing_substitute_is_rejected_and_case_is_not_executable(self) -> None:
        frame = pd.DataFrame(
            {
                "date": ["2020-01-02"],
                "code": ["AAA"],
                "forward_return_1d": [0.01],
                "is_suspended": [False],
            }
        )
        truth_source = {
            "truth_id": "next_day_filter",
            "evaluation_family": "ic_analysis",
            "evaluation_method": "rank IC",
            "required_data": {
                "evaluation": ["forward_return_1d"],
                "filters": ["next_day_suspension_status"],
            },
            "metrics": {"rank_ic_mean": 0.04},
        }

        assessment = assess_evaluation_case_support(
            truth_source,
            build_data_profile(frame),
            get_generic_evaluator_capabilities(),
        )
        status = next(item for item in assessment.requirement_results if item.requirement == "next_day_suspension_status")

        self.assertEqual(status.relationship, "unsupported_substitute")
        self.assertIsNone(status.available_value)
        self.assertFalse(status.execution_ready)
        self.assertFalse(assessment.case_executable)
        self.assertEqual(assessment.replacement_records[0]["status"], "rejected_candidate")

    def test_neutralization_control_transforms_are_checked_against_evaluator_capabilities(self) -> None:
        frame = pd.DataFrame(
            {
                "date": ["2020-01-02", "2020-01-02"],
                "code": ["AAA", "BBB"],
                "forward_return_1d": [0.01, -0.01],
                "market_cap": [100.0, 200.0],
            }
        )
        truth_source = {
            "truth_id": "transformed_control",
            "evaluation_family": "ic_analysis",
            "evaluation_method": "rank IC after size neutralization",
            "evaluation_spec": {"return_col": "forward_return_1d"},
            "neutralization_spec": {
                "method": "cross_sectional_regression_residual",
                "controls": [
                    {
                        "paper_field": "market_cap",
                        "encoding": "continuous",
                        "transforms": [
                            {"method": "log"},
                            {"method": "median_mad"},
                            {"method": "cross_section_zscore"},
                        ],
                    }
                ],
            },
            "metrics": {"rank_ic_mean": 0.04},
        }

        supported = assess_evaluation_case_support(
            truth_source,
            build_data_profile(frame),
            get_generic_evaluator_capabilities(),
        )

        capability = next(item for item in supported.requirement_results if item.category == "evaluator_capability")
        control = next(item for item in supported.requirement_results if item.category == "transform_control")
        self.assertEqual(capability.availability, "available")
        self.assertTrue(supported.case_executable)
        self.assertEqual(control.available_value, "market_cap")

        truth_source["neutralization_spec"]["controls"][0]["transforms"].append({"method": "quantile_normalize"})
        unsupported = assess_evaluation_case_support(
            truth_source,
            build_data_profile(frame),
            get_generic_evaluator_capabilities(),
        )
        unsupported_capability = next(
            item for item in unsupported.requirement_results if item.category == "evaluator_capability"
        )
        self.assertEqual(unsupported_capability.availability, "missing")
        self.assertFalse(unsupported.case_executable)

    def test_profile_relationship_can_explicitly_override_conservative_proxy(self) -> None:
        frame = pd.DataFrame(
            {
                "date": ["2020-01-02"],
                "code": ["AAA"],
                "forward_return_1d": [0.01],
                "market_cap": [100.0],
            }
        )
        profile = build_data_profile(
            frame,
            field_relationships=[
                FieldRelationship(
                    "free_float_market_cap",
                    "market_cap",
                    "exact_alias",
                    reason="Fixture provider declares market_cap to use the paper's free-float definition.",
                    source="provider_profile",
                )
            ],
        )
        truth_source = {
            "truth_id": "provider_semantics",
            "evaluation_family": "ic_analysis",
            "evaluation_method": "rank IC",
            "required_data": {
                "evaluation": ["forward_return_1d"],
                "controls": ["free_float_market_cap"],
            },
            "metrics": {"rank_ic_mean": 0.04},
        }

        assessment = assess_evaluation_case_support(
            truth_source,
            profile,
            get_generic_evaluator_capabilities(),
        )
        control = next(item for item in assessment.requirement_results if item.requirement == "free_float_market_cap")

        self.assertEqual(control.relationship, "exact_alias")
        self.assertEqual(control.semantic_availability, "exactly_available")
        self.assertEqual(control.available_value, "market_cap")
        self.assertEqual(assessment.replacement_records, [])

    def test_data_profile_infers_explicit_price_view_conventions(self) -> None:
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(["2019-04-29", "2019-04-30"]),
                "code": ["AAA", "AAA"],
                "close": [10.0, 11.0],
                "price_adjustment": ["qfq", "qfq"],
                "adjustment_anchor_date": pd.to_datetime(["2019-04-30", "2019-04-30"]),
            }
        )

        profile = build_data_profile(frame, source_id="qfq-test")

        self.assertEqual(profile.conventions["price_adjustment"], "qfq")
        self.assertEqual(profile.conventions["adjustment_anchor_date"], "2019-04-30")


if __name__ == "__main__":
    unittest.main()
