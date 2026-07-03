from __future__ import annotations

import unittest

from contracts.factor_research import FactorResearchSpec
from research_core.factor_lab.paper_reproduction.paper_evaluation import build_paper_evaluation_plan


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
        self.assertEqual(plan.factor_plans[0].evaluation_cases[0]["evaluation_family"], "ic_regression")
        self.assertEqual(plan.factor_plans[0].evaluation_cases[0]["evaluation_spec"]["return_horizon"], 20)
        self.assertEqual(
            plan.factor_plans[0].evaluation_cases[0]["transform_spec"]["steps"][1]["name"],
            "industry_market_cap_neutralization",
        )
        self.assertEqual(plan.factor_plans[0].evaluation_cases[0]["required_data"]["controls"], ["industry", "market_cap"])


if __name__ == "__main__":
    unittest.main()
