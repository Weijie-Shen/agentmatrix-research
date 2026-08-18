from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from research_core.factor_lab.paper_reproduction.evaluation_recipe import (
    GLOBAL_EVALUATION_POLICY_ID,
    resolve_recipe_value_states,
)
from research_core.factor_lab.paper_reproduction.evaluators import apply_evaluation_recipe, evaluate_paper_case
from research_core.factor_lab.paper_reproduction.extraction import (
    ExtractedFactorDefinition,
    ExtractedMetricDefinition,
    ExtractedRecipeTruthSource,
    ExtractedSemanticRequirement,
    ICRecipePaperExtraction,
    load_paper_extraction,
    validate_paper_extraction,
)
from research_core.factor_lab.paper_reproduction.normalization import normalize_extraction_to_specs
from research_core.factor_lab.paper_reproduction.paper_evaluation import build_paper_evaluation_plan


def _recipe(*steps: dict) -> dict:
    return {
        "global_policy_ref": GLOBAL_EVALUATION_POLICY_ID,
        "sampling": {
            "start": "2020-01-01",
            "end": "2020-12-31",
            "signal_schedule": "every_trading_day",
            "universe": {"description": "all A shares"},
        },
        "preprocessing_steps": list(steps),
        "return_label": {
            "method_id": "return.forward_close_to_close",
            "horizon_exchange_days": 1,
            "output_field": "forward_return_1d",
        },
        "ic_method": {"method_id": "ic.spearman_rank", "ic_ir_convention": "signed"},
        "metric_methods": [
            {"method_id": "metric.rank_ic_mean"},
            {"method_id": "metric.rank_ic_ir"},
        ],
    }


def _extraction() -> ICRecipePaperExtraction:
    metrics = [
        ExtractedMetricDefinition("rank_ic_mean", "Rank IC", "mean daily rank IC", "decimal"),
        ExtractedMetricDefinition("rank_ic_ir", "Rank ICIR", "mean divided by sample std", "ratio"),
    ]
    truth = ExtractedRecipeTruthSource(
        truth_source_id="table_52_plain",
        source={"page": 20, "table": "Table 52", "row_block": "plain factors"},
        covered_factor_ids=["alpha_a", "alpha_b"],
        evaluation_recipe=_recipe(
            {
                "order": 1,
                "method_id": "factor_missing.drop",
                "semantic_input": "factor_exposure",
            },
            {
                "order": 2,
                "method_id": "winsorize.median_mad",
                "parameters": {"threshold": 5},
                "semantic_input": "factor_exposure",
            },
            {
                "order": 3,
                "method_id": "standardize.cross_sectional_zscore",
                "semantic_input": "factor_exposure",
            },
        ),
        reported_metric_ids=["rank_ic_mean", "rank_ic_ir"],
        reported_results={
            "alpha_a": {"rank_ic_mean": 0.03, "rank_ic_ir": 0.4},
            "alpha_b": {"rank_ic_mean": 0.02, "rank_ic_ir": 0.3},
        },
    )
    return ICRecipePaperExtraction(
        artifact_id="paper-v3",
        paper={"paper_id": "paper-v3", "title": "Recipe test", "authors": ["Researcher"], "year": 2020},
        factor_family_name="recipe_test",
        factor_definitions=[
            ExtractedFactorDefinition("alpha_a", "Alpha A", "close / open", ["daily_close", "daily_open"], "daily"),
            ExtractedFactorDefinition("alpha_b", "Alpha B", "high / low", ["daily_high", "daily_low"], "daily"),
        ],
        semantic_requirements=[
            ExtractedSemanticRequirement("daily_close", "market_data", "daily_close_price"),
            ExtractedSemanticRequirement("daily_open", "market_data", "daily_open_price"),
            ExtractedSemanticRequirement("daily_high", "market_data", "daily_high_price"),
            ExtractedSemanticRequirement("daily_low", "market_data", "daily_low_price"),
        ],
        metric_definitions=metrics,
        truth_sources=[truth],
        factor_truth_selection={"alpha_a": "table_52_plain", "alpha_b": "table_52_plain"},
    )


class ICRecipeExtractionTests(unittest.TestCase):
    def test_one_truth_source_recipe_covers_many_factors_and_selection_is_stage_1(self) -> None:
        extraction = _extraction()
        validation = validate_paper_extraction(extraction)
        self.assertTrue(validation.valid, validation.errors)
        specs = normalize_extraction_to_specs(extraction)
        self.assertEqual(len(specs), 2)
        for spec in specs:
            self.assertEqual(spec.metadata["selected_truth_source_ids"], ["table_52_plain"])
            self.assertEqual(spec.metadata["truth_source_summary"]["selection_stage"], 1)
            self.assertEqual(len(spec.metadata["evaluation_cases"]), 1)
            self.assertIn("evaluation_recipe", spec.metadata["evaluation_cases"][0])

    def test_each_factor_must_select_exactly_one_source_that_contains_its_row(self) -> None:
        extraction = _extraction()
        extraction.factor_truth_selection.pop("alpha_b")
        validation = validate_paper_extraction(extraction)
        self.assertFalse(validation.valid)
        self.assertTrue(any("missing factors" in error for error in validation.errors))

    def test_v3_json_round_trip_preserves_recipe_and_selection(self) -> None:
        extraction = _extraction()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "extraction.json"
            path.write_text(json.dumps(asdict(extraction)), encoding="utf-8")
            loaded = load_paper_extraction(path)
        self.assertIsInstance(loaded, ICRecipePaperExtraction)
        self.assertEqual(loaded.factor_truth_selection, extraction.factor_truth_selection)
        self.assertEqual(
            loaded.truth_sources[0].evaluation_recipe["preprocessing_steps"],
            extraction.truth_sources[0].evaluation_recipe["preprocessing_steps"],
        )

    def test_stage_3_support_resolution_does_not_reselect_truth(self) -> None:
        specs = normalize_extraction_to_specs(_extraction())
        profile = {
            "source_id": "test",
            "columns": ["date", "code", "forward_return_1d", "is_st", "next_is_suspended"],
            "date_min": "2020-01-01",
            "date_max": "2020-12-31",
            "missingness": {"forward_return_1d": 0.0, "is_st": 0.0, "next_is_suspended": 0.0},
            "derived_fields": [
                {"field": "forward_return_1d", "method": "forward_return", "horizon": 1}
            ],
            "conventions": {},
        }
        plan = build_paper_evaluation_plan(specs, data_profiles={"*": profile})
        for factor_plan in plan.factor_plans:
            self.assertEqual(len(factor_plan.selected_evaluation_cases), 1)
            selected = factor_plan.selected_evaluation_cases[0]
            self.assertEqual(selected["truth_id"], "table_52_plain")
            self.assertIn("fixed during Stage 1", selected["selection_reason"])


class RecipeValueStateTests(unittest.TestCase):
    def test_raw_market_cap_applies_log_and_logged_market_cap_is_reused(self) -> None:
        recipe = _recipe(
            {
                "order": 1,
                "method_id": "neutralize.cross_sectional_regression_residual",
                "controls": [
                    {
                        "semantic_input": "market_cap",
                        "encoding": "continuous",
                        "transforms": [{"method_id": "transform.natural_log"}],
                    }
                ],
            }
        )
        raw_profile = {
            "columns": ["market_cap"],
            "conventions": {
                "market_cap_lineage": {
                    "market_cap": {"value_space": "level", "transform_chain": [], "unit": "CNY"}
                }
            },
        }
        raw_resolved = resolve_recipe_value_states(recipe, raw_profile)
        raw_transform = raw_resolved["preprocessing_steps"][0]["controls"][0]["transforms"][0]
        self.assertEqual(raw_transform["execution_mode"], "apply")

        logged_profile = {
            "columns": ["log_market_cap"],
            "conventions": {"semantic_bindings": {"market_cap": "log_market_cap"}},
            "derived_fields": [
                {
                    "field": "log_market_cap",
                    "semantic_concept": "market_cap",
                    "value_space": "log_level",
                    "transform_chain": ["transform.natural_log"],
                }
            ],
        }
        logged_resolved = resolve_recipe_value_states(recipe, logged_profile)
        logged_transform = logged_resolved["preprocessing_steps"][0]["controls"][0]["transforms"][0]
        self.assertEqual(logged_transform["execution_mode"], "reuse_materialized")


class RecipeExecutionTests(unittest.TestCase):
    def _frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2020-01-02"] * 3 + ["2020-01-03"] * 3),
                "code": ["A", "B", "C", "A", "B", "C"],
                "factor": [1.0, np.nan, 3.0, np.nan, 2.0, 4.0],
                "forward_return_1d": [0.01, 0.02, 0.03, 0.03, 0.01, 0.02],
                "is_st": [False, True, False, False, False, False],
                "next_is_suspended": [False, False, False, False, True, False],
            }
        )

    def test_global_policy_runs_before_ordered_factor_missing_policy(self) -> None:
        recipe = _recipe(
            {
                "order": 1,
                "method_id": "factor_missing.fill_zero",
                "semantic_input": "factor_exposure",
            }
        )
        processed, diagnostics = apply_evaluation_recipe(self._frame(), value_col="factor", recipe=recipe)
        self.assertEqual(diagnostics["global_policy"]["input_rows"], 6)
        self.assertEqual(diagnostics["global_policy"]["eligible_rows"], 4)
        self.assertEqual(len(processed), 4)
        self.assertEqual(processed.loc[processed["code"] == "A", "processed_factor"].iloc[-1], 0.0)

    def test_previous_exchange_day_fill_has_maximum_age_one(self) -> None:
        recipe = _recipe(
            {
                "order": 1,
                "method_id": "factor_missing.use_previous_exchange_day",
                "semantic_input": "factor_exposure",
                "parameters": {"maximum_age_exchange_days": 1},
            }
        )
        frame = self._frame()
        frame["is_st"] = False
        frame["next_is_suspended"] = False
        processed, _ = apply_evaluation_recipe(frame, value_col="factor", recipe=recipe)
        value = processed.loc[(processed["date"] == pd.Timestamp("2020-01-03")) & (processed["code"] == "A"), "processed_factor"]
        self.assertEqual(value.iloc[0], 1.0)

    def test_case_evaluator_reports_recipe_trace_and_rank_icir(self) -> None:
        case = {
            "truth_id": "truth",
            "evaluation_family": "ic_analysis",
            "evaluation_recipe": _recipe({"order": 1, "method_id": "factor_missing.drop"}),
            "evaluation_spec": {"return_col": "forward_return_1d", "ic_type": "spearman_rank_ic"},
            "required_data": {"evaluation": ["forward_return_1d"]},
        }
        frame = self._frame()
        frame["is_st"] = False
        frame["next_is_suspended"] = False
        result = evaluate_paper_case(case, frame, factor_col="factor")
        self.assertIn("rank_ic_ir", result["metrics"])
        self.assertEqual(
            result["resolved_parameters"]["recipe_execution_trace"]["preprocessing_trace"][0]["method_id"],
            "factor_missing.drop",
        )

    def test_sequential_neutralizations_remain_two_ordered_steps(self) -> None:
        recipe = _recipe(
            {
                "order": 1,
                "method_id": "neutralize.cross_sectional_regression_residual",
                "controls": [{"semantic_input": "industry", "resolved_field": "industry", "encoding": "categorical"}],
            },
            {
                "order": 2,
                "method_id": "neutralize.cross_sectional_regression_residual",
                "controls": [
                    {
                        "semantic_input": "market_cap",
                        "resolved_field": "market_cap",
                        "encoding": "continuous",
                        "transforms": [{"method_id": "transform.natural_log"}],
                    },
                    {"semantic_input": "beta", "resolved_field": "beta", "encoding": "continuous"},
                ],
            },
        )
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(["2020-01-02"] * 5),
                "code": list("ABCDE"),
                "factor": [1.0, 2.0, 4.0, 8.0, 16.0],
                "forward_return_1d": [0.01, 0.02, 0.03, 0.04, 0.05],
                "industry": ["x", "x", "y", "y", "z"],
                "market_cap": [10.0, 20.0, 30.0, 50.0, 80.0],
                "beta": [0.8, 1.0, 1.1, 0.9, 1.2],
                "is_st": False,
                "next_is_suspended": False,
            }
        )
        _, diagnostics = apply_evaluation_recipe(frame, value_col="factor", recipe=recipe)
        self.assertEqual([item["order"] for item in diagnostics["neutralization_steps"]], [1, 2])


if __name__ == "__main__":
    unittest.main()
