from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from contracts.factor_research import FactorResearchSpec
from research_core.factor_lab.paper_reproduction.evaluation_execution import (
    EvaluationDataContext,
    execute_evaluation_plan,
    export_evaluation_bundle,
    load_evaluation_bundle,
    merge_evaluation_bundles,
)
from research_core.factor_lab.paper_reproduction.implementation import build_factor_implementation_artifact
from research_core.factor_lab.paper_reproduction.paper_evaluation import (
    PaperEvaluationPlan,
    PaperFactorEvaluationPlan,
)
from research_core.factor_lab.paper_reproduction.resource_execution import (
    ResourceBudgetExceededError,
    ResourceExecutionConfig,
)


class CanonicalEvaluationExecutionTest(unittest.TestCase):
    def _spec(self) -> FactorResearchSpec:
        return FactorResearchSpec(
            factor_name="alpha",
            factor_id="demo_alpha",
            library="Demo",
            version="v1",
            formula="mean(close, 2)",
            required_fields=["close"],
        )

    def _case(self) -> dict[str, object]:
        return {
            "case_id": "table_1_ic",
            "truth_id": "table_1_ic",
            "source_truth_id": "table_1_ic",
            "evaluation_family": "ic_analysis",
            "evaluation_method": "daily rank IC",
            "comparability": "proxy",
            "truth_match_eligible_metrics": ["rank_ic_mean"],
            "diagnostic_only_metrics": ["rank_ic_std"],
            "resolved_protocol": {
                "evaluation_family": "ic_analysis",
                "evaluation_method": "daily rank IC",
                "evaluation_spec": {"return_col": "forward_return_1d", "ic_type": "spearman_rank_ic"},
                "required_data": {"evaluation": ["forward_return_1d"]},
                "transform_spec": {"steps": []},
            },
        }

    def _plan(self, case: dict[str, object] | None = None) -> PaperEvaluationPlan:
        return PaperEvaluationPlan(
            library="Demo",
            status="ready_for_evaluation",
            factor_plans=[
                PaperFactorEvaluationPlan(
                    factor_name="alpha",
                    status="ready_for_evaluation",
                    selected_evaluation_cases=[case or self._case()],
                )
            ],
        )

    def _calculation_panel(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": ["2026-01-01", "2026-01-02", "2026-01-03"] * 2,
                "code": ["A"] * 3 + ["B"] * 3,
                "close": [1.0, 10.0, 2.0, 5.0, 1.0, 4.0],
            }
        )

    def _module_source(self, *, duplicate_keys: bool = False) -> str:
        duplicate_line = "    result = pd.concat([result, result.iloc[[0]]], ignore_index=True)\n" if duplicate_keys else ""
        return (
            "import pandas as pd\n\n"
            "def compute_factors(panel, factor_names=None):\n"
            "    data = panel.sort_values(['code', 'date']).copy()\n"
            "    result = data[['date', 'code']].copy()\n"
            "    result['alpha'] = data.groupby('code')['close'].transform(lambda s: s.rolling(2).mean())\n"
            f"{duplicate_line}"
            "    return result.sample(frac=1.0, random_state=7).reset_index(drop=True)\n"
        )

    def _artifact(self, root: Path, panel: pd.DataFrame, *, duplicate_keys: bool = False):
        module_path = root / "factor.py"
        module_path.write_text(self._module_source(duplicate_keys=duplicate_keys), encoding="utf-8")
        return build_factor_implementation_artifact(
            [self._spec()],
            module_path=module_path,
            callable_import_path="compute_factors",
            probe_panel=panel,
        )

    def test_executor_computes_on_full_history_before_joining_filtered_evaluation_inputs(self) -> None:
        calculation = self._calculation_panel()
        evaluation = pd.DataFrame(
            {
                "date": ["2026-01-03", "2026-01-03"],
                "code": ["A", "B"],
                "forward_return_1d": [0.1, -0.1],
            }
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact = self._artifact(Path(tmp_dir), calculation)
            context = EvaluationDataContext(
                calculation_panel=calculation,
                evaluation_inputs=evaluation,
                scenario_id="evaluation_filter_only",
            )

            bundle = execute_evaluation_plan(self._plan(), artifact, context)

        self.assertEqual(len(bundle.records), 1)
        record = bundle.records[0]
        self.assertEqual(record.lifecycle_state, "executed")
        self.assertEqual(record.factor_id, "demo_alpha")
        self.assertEqual(record.truth_case_id, "table_1_ic")
        self.assertEqual(record.scenario_id, "evaluation_filter_only")
        self.assertAlmostEqual(record.evaluator_output["metrics"]["rank_ic_mean"], 1.0)
        self.assertEqual(record.evaluator_output["execution_mode"], "canonical_plan_executor")
        self.assertEqual(record.alignment_diagnostics["alignment_method"], "one_to_one_key_join")
        self.assertEqual(record.implementation_source_hash, artifact.source_hash)
        self.assertEqual(record.comparability, "proxy")
        self.assertEqual(record.truth_match_eligible_metrics, ["rank_ic_mean"])
        self.assertFalse(any("not separately supplied" in item for item in record.limitations))

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = export_evaluation_bundle(bundle, Path(tmp_dir) / "bundle.json")
            loaded = load_evaluation_bundle(path)
            merged = merge_evaluation_bundles([loaded, loaded])
        self.assertEqual(len(loaded.records), 1)
        self.assertEqual(loaded.records[0].comparability, "proxy")
        self.assertEqual(len(merged.records), 1)
        self.assertEqual(merged.scenario_id, "combined_scenarios")

    def test_executor_scores_only_declared_sample_while_retaining_context_rows(self) -> None:
        calculation = pd.DataFrame(
            {
                "date": [f"2026-01-0{day}" for day in range(1, 7)] * 2,
                "code": ["A"] * 6 + ["B"] * 6,
                "close": [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 8.0, 4.0, 2.0, 1.0, 0.5, 0.25],
            }
        )
        evaluation = calculation[["date", "code"]].copy()
        evaluation["forward_return_1d"] = [
            -1.0,
            -1.0,
            0.2,
            0.2,
            1.0,
            1.0,
            1.0,
            1.0,
            -0.2,
            -0.2,
            -1.0,
            -1.0,
        ]
        case = self._case()
        case["sample_period"] = "2026-01-03 to 2026-01-04"
        case["paper_protocol"] = {"sample_period": "2026-01-03 to 2026-01-04"}
        case["resolved_protocol"]["sample_period"] = "2026-01-03 to 2026-01-04"

        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact = self._artifact(Path(tmp_dir), calculation)
            bundle = execute_evaluation_plan(
                self._plan(case),
                artifact,
                EvaluationDataContext(
                    calculation_panel=calculation,
                    evaluation_inputs=evaluation,
                ),
            )

        record = bundle.records[0]
        diagnostics = record.scoring_sample_diagnostics
        self.assertEqual(record.alignment_diagnostics["factor_row_count"], 12)
        self.assertEqual(diagnostics["before_clip"]["row_count"], 12)
        self.assertEqual(diagnostics["after_clip"]["row_count"], 4)
        self.assertEqual(diagnostics["rows_removed_before_start"], 4)
        self.assertEqual(diagnostics["rows_removed_after_end"], 4)
        self.assertEqual(diagnostics["declared_sample"]["resolved_start_date"], "2026-01-03T00:00:00")
        self.assertEqual(diagnostics["declared_sample"]["resolved_end_date"], "2026-01-04T00:00:00")
        self.assertTrue(diagnostics["calculation_history_preserved"])
        self.assertTrue(diagnostics["label_history_preserved"])
        self.assertEqual(bundle.executed_execution["sample"]["row_count"], 4)
        self.assertEqual(bundle.resource_telemetry["evaluation_rows"], 12)
        self.assertEqual(bundle.resource_telemetry["scored_signal_rows"], 4)

    def test_missing_evaluation_column_is_case_level_insufficient_data(self) -> None:
        calculation = self._calculation_panel()
        evaluation = calculation.loc[calculation["date"] == "2026-01-03", ["date", "code"]]
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact = self._artifact(Path(tmp_dir), calculation)
            bundle = execute_evaluation_plan(
                self._plan(),
                artifact,
                EvaluationDataContext(calculation_panel=calculation, evaluation_inputs=evaluation),
            )

        self.assertEqual(bundle.records[0].lifecycle_state, "insufficient_data")
        self.assertEqual(bundle.records[0].error["type"], "MissingEvaluationInputs")

    def test_st_and_suspension_filters_run_after_full_history_factor_calculation(self) -> None:
        calculation = self._calculation_panel()
        evaluation = pd.DataFrame(
            {
                "date": ["2026-01-03", "2026-01-03"],
                "code": ["A", "B"],
                "forward_return_1d": [0.1, -0.1],
                "is_st": [0, 1],
                "next_is_suspended": [0, 0],
            }
        )
        case = self._case()
        case["resolved_protocol"]["universe_protocol"] = {
            "filters": [
                {
                    "filter_name": "exclude_st_pt",
                    "resolved_field": "is_st",
                    "application_stage": "factor_cross_section",
                    "operator": "falsy",
                },
                {
                    "filter_name": "exclude_next_day_suspension",
                    "resolved_field": "next_is_suspended",
                    "application_stage": "factor_cross_section",
                    "operator": "falsy",
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact = self._artifact(Path(tmp_dir), calculation)
            bundle = execute_evaluation_plan(
                self._plan(case),
                artifact,
                EvaluationDataContext(calculation_panel=calculation, evaluation_inputs=evaluation),
            )

        record = bundle.records[0]
        self.assertEqual(record.lifecycle_state, "executed")
        self.assertEqual(record.alignment_diagnostics["factor_row_count"], 6)
        self.assertEqual(record.universe_diagnostics["input_rows"], 2)
        self.assertEqual(record.universe_diagnostics["output_rows"], 1)
        self.assertEqual(record.universe_diagnostics["applied_filters"][0]["filter_name"], "exclude_st_pt")

    def test_v3_recipe_applies_global_policy_inside_canonical_execution(self) -> None:
        calculation = self._calculation_panel()
        evaluation = pd.DataFrame(
            {
                "date": ["2026-01-03", "2026-01-03"],
                "code": ["A", "B"],
                "forward_return_1d": [0.1, -0.1],
                "is_st": [False, True],
                "next_is_suspended": [False, False],
            }
        )
        case = self._case()
        recipe = {
            "global_policy_ref": "china_a_share_ic_evaluation_v1",
            "preprocessing_steps": [{"order": 1, "method_id": "factor_missing.drop"}],
            "return_label": {
                "method_id": "return.forward_close_to_close",
                "horizon_exchange_days": 1,
                "output_field": "forward_return_1d",
            },
            "ic_method": {"method_id": "ic.spearman_rank"},
            "metric_methods": [{"method_id": "metric.rank_ic_mean"}],
        }
        case["resolved_protocol"]["evaluation_recipe"] = recipe
        case["resolved_protocol"]["resolved_evaluation_recipe"] = recipe
        case["resolved_protocol"]["required_data"] = {
            "evaluation": ["forward_return_1d"],
            "universe_filter": ["is_st", "next_is_suspended"],
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact = self._artifact(Path(tmp_dir), calculation)
            bundle = execute_evaluation_plan(
                self._plan(case),
                artifact,
                EvaluationDataContext(calculation_panel=calculation, evaluation_inputs=evaluation),
            )

        record = bundle.records[0]
        self.assertEqual(record.lifecycle_state, "executed")
        global_trace = record.evaluator_output["resolved_parameters"]["recipe_execution_trace"]["global_policy"]
        self.assertEqual(global_trace["input_rows"], 2)
        self.assertEqual(global_trace["eligible_rows"], 1)
        self.assertEqual(record.alignment_diagnostics["factor_row_count"], 6)

    def test_skipped_neutralization_control_is_an_execution_limitation(self) -> None:
        calculation = self._calculation_panel()
        evaluation = pd.DataFrame(
            {
                "date": ["2026-01-03", "2026-01-03"],
                "code": ["A", "B"],
                "forward_return_1d": [0.1, -0.1],
            }
        )
        case = self._case()
        case["resolved_protocol"]["neutralization_spec"] = {
            "method": "cross_sectional_regression_residual",
            "dependent_variable": {"transforms": []},
            "controls": [
                {
                    "paper_field": "log_market_cap",
                    "resolved_field": None,
                    "runtime_status": "unavailable",
                    "transforms": [{"method": "log"}],
                }
            ],
            "output_transforms": [],
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact = self._artifact(Path(tmp_dir), calculation)
            bundle = execute_evaluation_plan(
                self._plan(case),
                artifact,
                EvaluationDataContext(calculation_panel=calculation, evaluation_inputs=evaluation),
            )

        record = bundle.records[0]
        self.assertEqual(record.lifecycle_state, "executed")
        self.assertTrue(any("log_market_cap" in item for item in record.limitations))
        self.assertEqual(
            record.evaluator_output["neutralization_diagnostics"]["skipped_controls"][0]["paper_field"],
            "log_market_cap",
        )

    def test_shared_panel_fallback_is_nonblocking_and_reported(self) -> None:
        calculation = self._calculation_panel()
        calculation["forward_return_1d"] = [0.0, 0.05, 0.1, 0.0, -0.05, -0.1]
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact = self._artifact(Path(tmp_dir), calculation)
            bundle = execute_evaluation_plan(
                self._plan(),
                artifact,
                EvaluationDataContext(calculation_panel=calculation),
            )

        self.assertEqual(bundle.records[0].lifecycle_state, "executed")
        self.assertTrue(any("not separately supplied" in item for item in bundle.limitations))

    def test_execution_identity_is_stable_for_same_artifact_context_and_case(self) -> None:
        calculation = self._calculation_panel()
        evaluation = pd.DataFrame(
            {"date": ["2026-01-03", "2026-01-03"], "code": ["A", "B"], "forward_return_1d": [0.1, -0.1]}
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact = self._artifact(Path(tmp_dir), calculation)
            context = EvaluationDataContext(calculation_panel=calculation, evaluation_inputs=evaluation)
            first = execute_evaluation_plan(self._plan(), artifact, context)
            second = execute_evaluation_plan(self._plan(), artifact, context)

        self.assertEqual(first.records[0].execution_id, second.records[0].execution_id)
        self.assertEqual(first.data_snapshot_hash, second.data_snapshot_hash)

    def test_executor_projects_columns_and_selects_bounded_mode_without_shortening(self) -> None:
        calculation = self._calculation_panel()
        calculation["unused_payload"] = ["x" * 10_000 for _ in range(len(calculation))]
        evaluation = pd.DataFrame(
            {
                "date": ["2026-01-03", "2026-01-03"],
                "code": ["A", "B"],
                "forward_return_1d": [0.1, -0.1],
                "unused_evaluation_payload": ["y" * 10_000, "y" * 10_000],
            }
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact = self._artifact(Path(tmp_dir), calculation[["date", "code", "close"]])
            first = execute_evaluation_plan(
                self._plan(),
                artifact,
                EvaluationDataContext(calculation_panel=calculation, evaluation_inputs=evaluation),
            )
            preflight = first.resource_preflight
            budget = (
                preflight["estimated_standard_peak_bytes"] + preflight["estimated_projected_peak_bytes"]
            ) // 2
            bounded = execute_evaluation_plan(
                self._plan(),
                artifact,
                EvaluationDataContext(
                    calculation_panel=calculation,
                    evaluation_inputs=evaluation,
                    resource_config=ResourceExecutionConfig(memory_budget_bytes=budget),
                    requested_sample={"start_date": "2026-01-01", "end_date": "2026-01-03"},
                ),
            )

        self.assertEqual(bounded.resource_preflight["execution_mode"], "resource_bounded_projected")
        self.assertEqual(bounded.resource_preflight["calculation_columns"], ["date", "code", "close"])
        self.assertEqual(
            bounded.resource_preflight["evaluation_columns"],
            ["date", "code", "forward_return_1d"],
        )
        self.assertEqual(bounded.requested_execution["sample"]["start_date"], "2026-01-01")
        self.assertEqual(bounded.executed_execution["sample"]["row_count"], 2)
        self.assertEqual(bounded.methodological_deviations, [])
        self.assertTrue(bounded.raw_factor_before_evaluation_filters)

    def test_factor_callable_receives_only_declared_calculation_columns(self) -> None:
        calculation = self._calculation_panel()
        calculation["unused_payload"] = "must_not_reach_callable"
        evaluation = pd.DataFrame(
            {"date": ["2026-01-03"], "code": ["A"], "forward_return_1d": [0.1], "unused": [99]}
        )
        module_source = (
            "import pandas as pd\n\n"
            "def compute_factors(panel, factor_names=None):\n"
            "    assert list(panel.columns) == ['date', 'code', 'close']\n"
            "    result = panel[['date', 'code']].copy()\n"
            "    result['alpha'] = panel.groupby('code')['close'].transform(lambda s: s.rolling(2).mean())\n"
            "    return result\n"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            module_path = Path(tmp_dir) / "factor.py"
            module_path.write_text(module_source, encoding="utf-8")
            artifact = build_factor_implementation_artifact(
                [self._spec()],
                module_path=module_path,
                callable_import_path="compute_factors",
                probe_panel=calculation[["date", "code", "close"]],
            )
            bundle = execute_evaluation_plan(
                self._plan(),
                artifact,
                EvaluationDataContext(calculation_panel=calculation, evaluation_inputs=evaluation),
            )

        self.assertEqual(bundle.records[0].lifecycle_state, "executed")

    def test_executor_stops_before_oom_risk_instead_of_changing_methodology(self) -> None:
        calculation = self._calculation_panel()
        evaluation = pd.DataFrame(
            {"date": ["2026-01-03"], "code": ["A"], "forward_return_1d": [0.1]}
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact = self._artifact(Path(tmp_dir), calculation)
            with self.assertRaises(ResourceBudgetExceededError) as raised:
                execute_evaluation_plan(
                    self._plan(),
                    artifact,
                    EvaluationDataContext(
                        calculation_panel=calculation,
                        evaluation_inputs=evaluation,
                        resource_config=ResourceExecutionConfig(memory_budget_bytes=1),
                    ),
                )

        self.assertTrue(raised.exception.preflight.partition_required)
        self.assertEqual(raised.exception.preflight.methodological_deviations, [])

    def test_duplicate_factor_keys_block_canonical_artifact_certification(self) -> None:
        calculation = self._calculation_panel()
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaisesRegex(ValueError, "duplicate keys"):
                self._artifact(Path(tmp_dir), calculation, duplicate_keys=True)


if __name__ == "__main__":
    unittest.main()
