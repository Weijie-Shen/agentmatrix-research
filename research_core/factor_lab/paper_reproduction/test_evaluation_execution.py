from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from contracts.factor_research import FactorResearchSpec
from research_core.factor_lab.paper_reproduction.evaluation_execution import (
    EvaluationDataContext,
    execute_evaluation_plan,
)
from research_core.factor_lab.paper_reproduction.implementation import build_factor_implementation_artifact
from research_core.factor_lab.paper_reproduction.paper_evaluation import (
    PaperEvaluationPlan,
    PaperFactorEvaluationPlan,
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
        self.assertFalse(any("not separately supplied" in item for item in record.limitations))

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

    def test_duplicate_factor_keys_block_canonical_artifact_certification(self) -> None:
        calculation = self._calculation_panel()
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaisesRegex(ValueError, "duplicate keys"):
                self._artifact(Path(tmp_dir), calculation, duplicate_keys=True)


if __name__ == "__main__":
    unittest.main()
