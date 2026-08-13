from __future__ import annotations

import unittest
from unittest.mock import patch

from contracts.factor_research import FactorResearchSpec
from research_core.factor_lab.paper_reproduction.paper_evaluation import (
    MAX_EVALUATION_METHODS_PER_RUN,
    build_paper_evaluation_plan,
)


class PaperEvaluationPlanningTest(unittest.TestCase):
    def test_plan_uses_paper_evaluation_truth_metrics_and_method(self) -> None:
        spec = FactorResearchSpec(
            factor_name="alpha_from_paper",
            library="PaperDemo",
            version="v0.1",
            formula="rank(close / open - 1)",
            required_fields=["open", "close"],
            metadata={
                "evaluation_method": "daily rank IC and long-short quintile spread with 1-day forward returns",
                "selected_truth_sources": [
                    {
                        "truth_id": "table_3_eval",
                        "truth_type": "evaluation_results",
                        "evaluation_method": "daily rank IC and long-short quintile spread with 1-day forward returns",
                        "metrics": {"rank_ic_mean": 0.042, "rank_ic_ir": 0.31, "long_short_mean": 0.006},
                    }
                ],
            },
        )

        plan = build_paper_evaluation_plan([spec])

        self.assertEqual(plan.library, "PaperDemo")
        self.assertEqual(plan.factor_plans[0].status, "ready_for_evaluation")
        self.assertEqual(plan.factor_plans[0].forward_return_periods, [1])
        self.assertEqual(plan.factor_plans[0].required_metrics, ["rank_ic_mean", "rank_ic_ir", "long_short_mean"])
        self.assertIn("rank_ic", plan.factor_plans[0].evaluation_features)
        self.assertIn("long_short", plan.factor_plans[0].evaluation_features)

    def test_plan_needs_human_review_when_evaluation_truth_has_no_method(self) -> None:
        spec = FactorResearchSpec(
            factor_name="alpha_from_paper",
            library="PaperDemo",
            version="v0.1",
            formula="close / open - 1",
            required_fields=["open", "close"],
            metadata={
                "selected_truth_sources": [
                    {
                        "truth_id": "table_3_eval",
                        "truth_type": "evaluation_results",
                        "metrics": {"custom_metric": 1.0},
                    }
                ],
            },
        )

        plan = build_paper_evaluation_plan([spec])

        self.assertEqual(plan.status, "needs_human_review")
        self.assertEqual(plan.factor_plans[0].status, "needs_human_review")
        self.assertIn("paper evaluation method is missing", plan.factor_plans[0].blocked_reasons)


    def test_plan_preserves_evaluation_cases_with_transform_specs_and_required_data(self) -> None:
        spec = FactorResearchSpec(
            factor_name="alpha_from_paper",
            library="PaperDemo",
            version="v0.1",
            formula="rank(close)",
            required_fields=["close"],
            metadata={
                "selected_truth_sources": [
                    {
                        "truth_id": "table_52_ic",
                        "truth_type": "evaluation_results",
                        "evaluation_family": "ic_regression",
                        "evaluation_method": "T=20 Rank IC after industry+market-cap neutralization",
                        "evaluation_spec": {"return_horizon": 20, "ic_type": "spearman_rank_ic"},
                        "transform_spec": {
                            "steps": [
                                {"name": "median_mad_winsorization"},
                                {"name": "industry_market_cap_neutralization"},
                            ]
                        },
                        "required_data": {"evaluation": ["forward_return_20d"], "controls": ["industry", "market_cap"]},
                        "metrics": {"rank_ic_mean": 0.0629, "ic_ir": 1.33},
                    }
                ],
            },
        )

        plan = build_paper_evaluation_plan([spec])

        self.assertEqual(plan.factor_plans[0].evaluation_cases[0]["truth_id"], "table_52_ic")
        self.assertEqual(plan.factor_plans[0].evaluation_cases[0]["truth_case_id"], "table_52_ic")
        self.assertEqual(plan.factor_plans[0].evaluation_cases[0]["evaluation_family"], "ic_regression")
        self.assertEqual(plan.factor_plans[0].evaluation_cases[0]["evaluation_spec"]["return_horizon"], 20)
        self.assertEqual(
            plan.factor_plans[0].evaluation_cases[0]["transform_spec"]["steps"][1]["name"],
            "industry_market_cap_neutralization",
        )
        self.assertEqual(plan.factor_plans[0].evaluation_cases[0]["required_data"]["controls"], ["industry", "market_cap"])

    def test_plan_canonicalizes_horizon_alias_into_runtime_return_column_without_mutating_paper_protocol(self) -> None:
        spec = FactorResearchSpec(
            factor_name="alpha_from_paper",
            library="PaperDemo",
            version="v0.1",
            formula="rank(close)",
            required_fields=["close"],
            metadata={
                "selected_truth_sources": [
                    {
                        "truth_id": "table_ic",
                        "truth_type": "evaluation_results",
                        "evaluation_family": "ic_analysis",
                        "evaluation_method": "20-day rank IC",
                        "evaluation_spec": {"return_horizon_days": 20},
                        "required_data": {"labels": ["close"]},
                        "metrics": {"rank_ic_mean": 0.04},
                    }
                ]
            },
        )

        case = build_paper_evaluation_plan([spec]).factor_plans[0].evaluation_cases[0]

        self.assertEqual(case["evaluation_spec"]["return_horizon"], 20)
        self.assertEqual(case["evaluation_spec"]["return_col"], "forward_return_20d")
        self.assertIn("forward_return_20d", case["required_data"]["evaluation"])
        self.assertNotIn("return_col", case["paper_protocol"]["evaluation_spec"])

    def test_plan_canonicalizes_natural_month_horizon_to_distinct_return_column(self) -> None:
        spec = FactorResearchSpec(
            factor_name="alpha_from_paper",
            library="PaperDemo",
            version="v0.1",
            formula="rank(close)",
            required_fields=["close"],
            metadata={
                "selected_truth_sources": [
                    {
                        "truth_id": "table_ic",
                        "truth_type": "evaluation_results",
                        "evaluation_family": "ic_analysis",
                        "evaluation_method": "monthly rank IC",
                        "evaluation_spec": {"return_horizon": 1, "forward_horizon_unit": "natural_month"},
                        "metrics": {"rank_ic_mean": 0.04},
                    }
                ]
            },
        )

        case = build_paper_evaluation_plan([spec]).factor_plans[0].evaluation_cases[0]

        self.assertEqual(case["evaluation_spec"]["return_horizon_unit"], "natural_month")
        self.assertEqual(case["evaluation_spec"]["return_col"], "forward_return_1m")
        self.assertIn("forward_return_1m", case["required_data"]["evaluation"])

    def test_plan_selects_ic_analysis_before_portfolio_backtest(self) -> None:
        spec = self._spec_with_cases(
            [
                self._case("portfolio", "layered_portfolio_backtest", {"long_short_mean": 0.01}),
                self._case("ic", "ic_analysis", {"rank_ic_mean": 0.04}),
            ]
        )

        plan = build_paper_evaluation_plan([spec])

        factor_plan = plan.factor_plans[0]
        self.assertEqual([case["truth_id"] for case in factor_plan.selected_evaluation_cases], ["ic"])
        self.assertEqual(factor_plan.skipped_evaluation_cases[0]["truth_id"], "portfolio")
        self.assertEqual(factor_plan.skipped_evaluation_cases[0]["skip_reason"], "known_method_available")
        self.assertFalse(factor_plan.requires_paper_local_evaluator)

    def test_plan_selects_ic_regression_before_ic_decay(self) -> None:
        spec = self._spec_with_cases(
            [
                self._case("decay", "ic_decay", {"half_life": 12}),
                self._case("regression", "ic_regression", {"t_abs_mean": 2.1}),
            ]
        )

        plan = build_paper_evaluation_plan([spec])

        factor_plan = plan.factor_plans[0]
        self.assertEqual([case["truth_id"] for case in factor_plan.selected_evaluation_cases], ["regression"])
        self.assertEqual(factor_plan.skipped_evaluation_cases[0]["truth_id"], "decay")

    def test_plan_selects_no_more_than_two_methods(self) -> None:
        spec = self._spec_with_cases(
            [
                self._case("ic_a", "ic_analysis", {"rank_ic_mean": 0.04}),
                self._case("ic_b", "ic_analysis", {"rank_ic_ir": 0.31}),
                self._case("regression", "ic_regression", {"t_abs_mean": 2.1}),
            ]
        )

        plan = build_paper_evaluation_plan([spec])

        factor_plan = plan.factor_plans[0]
        self.assertLessEqual(len(factor_plan.selected_evaluation_cases), MAX_EVALUATION_METHODS_PER_RUN)
        self.assertEqual([case["truth_id"] for case in factor_plan.selected_evaluation_cases], ["ic_a", "ic_b"])
        self.assertEqual(factor_plan.skipped_evaluation_cases[0]["skip_reason"], "method_budget_exceeded")

    def test_unsupported_method_becomes_implementation_target_when_no_known_method_exists(self) -> None:
        spec = self._spec_with_cases(
            [
                self._case("portfolio", "layered_portfolio_backtest", {"long_short_mean": 0.01}),
                self._case("decay", "ic_decay", {"half_life": 12}),
            ]
        )

        plan = build_paper_evaluation_plan([spec])

        factor_plan = plan.factor_plans[0]
        self.assertEqual(plan.status, "ready_for_evaluation_with_limitations")
        self.assertTrue(factor_plan.requires_paper_local_evaluator)
        self.assertEqual(
            [target["evaluation_family"] for target in factor_plan.evaluator_implementation_targets],
            ["ic_decay", "layered_portfolio_backtest"],
        )
        self.assertEqual(factor_plan.selected_evaluation_cases, [])

    def test_support_scoring_prefers_feasible_alternative_truth_without_mutating_source(self) -> None:
        primary = self._case("wls", "ic_regression", {"rank_ic_mean": 0.04, "t_abs_mean": 2.0})
        primary["required_data"] = {"evaluation": ["forward_return_20d"], "controls": ["industry"], "regression_weight": ["free_float_market_cap"]}
        alternative = self._case("ic", "ic_analysis", {"rank_ic_mean": 0.04})
        alternative["required_data"] = {"evaluation": ["forward_return_20d"]}
        spec = self._spec_with_cases([primary, alternative])
        original_primary = dict(primary)
        profile = {
            "columns": ["date", "code", "forward_return_20d"],
            "missingness": {"forward_return_20d": 0.0},
            "derived_fields": [],
        }

        plan = build_paper_evaluation_plan([spec], data_profiles={"alpha_from_paper": profile})

        factor_plan = plan.factor_plans[0]
        self.assertEqual(factor_plan.selected_evaluation_cases[0]["truth_id"], "ic")
        self.assertEqual(factor_plan.selected_evaluation_cases[0]["selection_reason"], "highest support score among assessed truth sources")
        self.assertEqual(factor_plan.selected_evaluation_cases[0]["lifecycle_state"], "selected")
        self.assertEqual(primary, original_primary)
        self.assertEqual({case["truth_id"] for case in factor_plan.assessed_evaluation_cases}, {"wls", "ic"})
        self.assertIn("resolved_protocol", factor_plan.selected_evaluation_cases[0])

    def test_changed_evaluator_capability_requires_explicit_stage3_reassessment(self) -> None:
        case = self._case("ic", "ic_analysis", {"rank_ic_mean": 0.04})
        case["required_data"] = {"evaluation": ["forward_return_20d"]}
        spec = self._spec_with_cases([case])
        profile = {
            "columns": ["date", "code", "forward_return_20d"],
            "missingness": {"forward_return_20d": 0.0},
        }
        with patch(
            "research_core.factor_lab.paper_reproduction.paper_evaluation.evaluator_capabilities_for_case",
            return_value=None,
        ):
            initial = build_paper_evaluation_plan(
                [spec],
                data_profiles={"alpha_from_paper": profile},
            )
        persisted = {
            "alpha_from_paper": {
                "ic": dict(
                    initial.factor_plans[0].assessed_evaluation_cases[0]["support_assessment"]
                )
            }
        }
        gated = build_paper_evaluation_plan(
            [spec],
            data_profiles={"alpha_from_paper": profile},
            persisted_support_assessments=persisted,
        )
        reassessed = build_paper_evaluation_plan(
            [spec],
            data_profiles={"alpha_from_paper": profile},
            persisted_support_assessments=persisted,
            reassess_support=True,
        )

        gated_case = gated.factor_plans[0].assessed_evaluation_cases[0]
        self.assertEqual(gated.factor_plans[0].selected_evaluation_cases, [])
        self.assertTrue(gated_case["support_assessment"]["reassessment_required"])
        self.assertEqual(gated_case["support_assessment"]["lifecycle_state"], "support_reassessment_required")
        self.assertEqual(len(reassessed.factor_plans[0].selected_evaluation_cases), 1)
        self.assertEqual(
            reassessed.factor_plans[0].assessed_evaluation_cases[0]["support_assessment"][
                "supersedes_assessment_id"
            ],
            persisted["alpha_from_paper"]["ic"]["assessment_id"],
        )

    def test_selection_rule_allows_unselected_feasible_truth_source(self) -> None:
        selected = self._case("unsupported_selected", "layered_portfolio_backtest", {"long_short_mean": 0.01})
        fallback = self._case("feasible_ic", "ic_analysis", {"rank_ic_mean": 0.04})
        fallback["required_data"] = {"evaluation": ["forward_return_20d"]}
        spec = self._spec_with_cases([selected])
        spec.metadata["truth_sources"] = [selected, fallback]
        spec.metadata["truth_selection_rule"] = "Prefer the best-supported paper truth source available in local data."
        profile = {"columns": ["date", "code", "forward_return_t20"], "missingness": {"forward_return_t20": 0.0}}

        plan = build_paper_evaluation_plan([spec], data_profiles={"alpha_from_paper": profile})

        factor_plan = plan.factor_plans[0]
        self.assertEqual(factor_plan.selected_evaluation_cases[0]["truth_id"], "feasible_ic")
        self.assertEqual({case["truth_id"] for case in factor_plan.assessed_evaluation_cases}, {"unsupported_selected", "feasible_ic"})

    def test_resolved_case_maps_aliases_and_downgrades_unavailable_wls_weight_to_ols_proxy(self) -> None:
        wls = self._case("table_52", "ic_regression", {"rank_ic_mean": 0.04, "t_abs_mean": 2.0})
        wls["sample_period"] = "2010-01-04 to 2019-04-30"
        wls["evaluation_spec"] = {
            "return_horizon": 20,
            "return_col": "forward_return_20d",
            "regression_type": "wls",
            "regression_weight": "sqrt_free_float_market_cap",
        }
        wls["required_data"] = {
            "evaluation": ["forward_return_20d"],
            "controls": ["market_cap_or_log_market_cap"],
            "regression_weight": ["sqrt_free_float_market_cap"],
        }
        spec = self._spec_with_cases([wls])
        profile = {
            "columns": ["date", "code", "forward_return_t20", "log_market_cap"],
            "date_min": "2017-01-03",
            "date_max": "2019-04-30",
            "missingness": {"forward_return_t20": 0.0, "log_market_cap": 0.0},
        }

        plan = build_paper_evaluation_plan([spec], data_profiles={"alpha_from_paper": profile})

        selected = plan.factor_plans[0].selected_evaluation_cases[0]
        self.assertEqual(selected["comparability"], "proxy")
        self.assertEqual(selected["paper_protocol"]["evaluation_spec"]["regression_type"], "wls")
        self.assertEqual(selected["resolved_protocol"]["evaluation_spec"]["regression_type"], "ols")
        self.assertEqual(selected["resolved_protocol"]["evaluation_spec"]["return_col"], "forward_return_t20")
        self.assertEqual(selected["resolved_protocol"]["evaluation_spec"]["regression_controls"], ["log_market_cap"])
        self.assertIn("t_abs_mean", selected["diagnostic_only_metrics"])
        self.assertIn("rank_ic_mean", selected["truth_match_eligible_metrics"])

    def test_resolved_case_uses_existing_proxy_weight_with_explicit_provenance(self) -> None:
        wls = self._case("proxy_wls", "ic_regression", {"rank_ic_mean": 0.04, "t_abs_mean": 2.0})
        wls["evaluation_spec"] = {
            "return_col": "forward_return_1d",
            "regression_type": "wls",
            "weight_col": "free_float_market_cap",
        }
        wls["required_data"] = {
            "evaluation": ["forward_return_1d"],
            "regression_weight": ["free_float_market_cap"],
        }
        profile = {
            "columns": ["date", "code", "forward_return_1d", "market_cap"],
            "missingness": {"forward_return_1d": 0.0, "market_cap": 0.0},
        }

        plan = build_paper_evaluation_plan(
            [self._spec_with_cases([wls])],
            data_profiles={"alpha_from_paper": profile},
        )

        selected = plan.factor_plans[0].selected_evaluation_cases[0]
        self.assertEqual(selected["comparability"], "proxy")
        self.assertEqual(selected["resolved_protocol"]["evaluation_spec"]["regression_type"], "wls")
        self.assertEqual(selected["resolved_protocol"]["evaluation_spec"]["weight_col"], "market_cap")
        self.assertEqual(selected["replacement_records"][0]["status"], "accepted_proxy")
        self.assertIn("t_abs_mean", selected["diagnostic_only_metrics"])
        self.assertIn("rank_ic_mean", selected["truth_match_eligible_metrics"])

    def test_resolved_case_preserves_control_transform_order_and_resolves_physical_field(self) -> None:
        case = self._case("neutralized_ic", "ic_analysis", {"rank_ic_mean": 0.04})
        case["evaluation_spec"] = {"return_col": "forward_return_1d"}
        case["required_data"] = {"evaluation": ["forward_return_1d"]}
        case["neutralization_spec"] = {
            "method": "cross_sectional_regression_residual",
            "controls": [
                {
                    "semantic_role": "size_control",
                    "paper_field": "market_cap",
                    "encoding": "continuous",
                    "transforms": [
                        {"method": "log"},
                        {"method": "median_mad", "threshold": 5},
                        {"method": "cross_section_zscore"},
                    ],
                }
            ],
        }
        profile = {
            "columns": ["date", "code", "forward_return_1d", "market_cap"],
            "missingness": {"forward_return_1d": 0.0, "market_cap": 0.0},
        }

        plan = build_paper_evaluation_plan(
            [self._spec_with_cases([case])],
            data_profiles={"alpha_from_paper": profile},
        )

        selected = plan.factor_plans[0].selected_evaluation_cases[0]
        resolved_control = selected["resolved_protocol"]["neutralization_spec"]["controls"][0]
        self.assertEqual(resolved_control["resolved_field"], "market_cap")
        self.assertEqual(
            [step["method"] for step in resolved_control["transforms"]],
            ["log", "median_mad", "cross_section_zscore"],
        )

    def test_a_share_exclusion_text_infers_evaluation_stage_filters_not_calculation_filters(self) -> None:
        case = self._case("a_share_filters", "ic_analysis", {"rank_ic_mean": 0.04})
        case["universe"] = "All A-shares; exclude ST/PT and stocks suspended on the next trading day"
        case["evaluation_spec"] = {"return_col": "forward_return_1d"}
        case["required_data"] = {"evaluation": ["forward_return_1d"]}
        profile = {
            "columns": ["date", "code", "forward_return_1d", "is_st", "next_is_suspended"],
            "missingness": {"forward_return_1d": 0.0, "is_st": 0.0, "next_is_suspended": 0.0},
        }

        plan = build_paper_evaluation_plan(
            [self._spec_with_cases([case])],
            data_profiles={"alpha_from_paper": profile},
        )

        selected = plan.factor_plans[0].selected_evaluation_cases[0]
        protocol = selected["resolved_protocol"]["universe_protocol"]
        self.assertEqual(
            [item["application_stage"] for item in protocol["filters"]],
            ["factor_cross_section", "factor_cross_section"],
        )
        self.assertEqual(
            [item["resolved_field"] for item in protocol["filters"]],
            ["is_st", "next_is_suspended"],
        )
        self.assertEqual(protocol["calculation_universe"]["description"], "retain complete valid security history for factor calculation")

    def test_unsupported_substitute_is_not_selected_or_written_into_runtime_protocol(self) -> None:
        case = self._case("bad_timing_alias", "ic_analysis", {"rank_ic_mean": 0.04})
        case["required_data"] = {
            "evaluation": ["forward_return_1d"],
            "filters": ["next_day_suspension_status"],
        }
        profile = {
            "columns": ["date", "code", "forward_return_1d", "is_suspended"],
            "missingness": {"forward_return_1d": 0.0, "is_suspended": 0.0},
        }

        plan = build_paper_evaluation_plan(
            [self._spec_with_cases([case])],
            data_profiles={"alpha_from_paper": profile},
        )

        factor_plan = plan.factor_plans[0]
        self.assertEqual(factor_plan.selected_evaluation_cases, [])
        self.assertEqual(factor_plan.unsupported_evaluation_cases[0]["lifecycle_state"], "insufficient_data")
        assessment = factor_plan.unsupported_evaluation_cases[0]["support_assessment"]
        status = next(item for item in assessment["requirement_results"] if item["requirement"] == "next_day_suspension_status")
        self.assertFalse(status["execution_ready"])
        self.assertIsNone(status["available_value"])

    def _spec_with_cases(self, cases: list[dict[str, object]]) -> FactorResearchSpec:
        return FactorResearchSpec(
            factor_name="alpha_from_paper",
            library="PaperDemo",
            version="v0.1",
            formula="rank(close)",
            required_fields=["close"],
            metadata={"selected_truth_sources": cases},
        )

    def _case(self, truth_id: str, family: str, metrics: dict[str, object]) -> dict[str, object]:
        return {
            "truth_id": truth_id,
            "truth_type": "evaluation_results",
            "evaluation_family": family,
            "evaluation_method": f"{family} method",
            "metrics": metrics,
        }


if __name__ == "__main__":
    unittest.main()
