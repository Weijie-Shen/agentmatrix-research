from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research_core.factor_lab.paper_reproduction.agent_harness_review import (
    EXPECTED_STAGES,
    assess_agent_harness_run,
)


class AgentHarnessRunAssessmentTest(unittest.TestCase):
    def test_complete_run_requires_reports_stages_factors_evaluation_and_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            runtime = root / "runtime" / "factor_lab"
            reports = runtime / "reports"
            artifacts = runtime / "implementation_plans"
            reports.mkdir(parents=True)
            artifacts.mkdir(parents=True)
            (runtime / "list_payload.json").write_text(json.dumps([{"not": "an artifact"}]), encoding="utf-8")
            factors = ["Alpha3", "Alpha13"]
            report = {
                "summary": {
                    "next_stage": "complete",
                    "overall_status": "completed_with_limitations",
                    "pipeline_overall_status": "completed_with_limitations",
                },
                "pipeline": {
                    "stages": [
                        {"name": name, "execution_status": "completed", "limitations": []}
                        for name in EXPECTED_STAGES
                    ]
                },
                "factors": [
                    {
                        "factor_name": factor,
                        "formula": "close",
                        "required_fields": ["close"],
                        "evaluation_executions": [{"lifecycle_state": "executed"}],
                        "truth_results": [{"status": "directionally_consistent"}],
                    }
                    for factor in factors
                ],
                "comparison_results": {
                    "primary_metric_rows": [
                        {
                            "factor_name": factor,
                            "paper_value": 0.05,
                            "calculated_value": 0.048,
                        }
                        for factor in factors
                    ]
                },
                "tests_run": ["python -m unittest"],
            }
            report_path = reports / "demo_paper_reproduction_report.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            report_path.with_suffix(".md").write_text("# Report\n", encoding="utf-8")
            artifact = {
                "schema_version": "factor_implementation_artifact/v1",
                "implemented_factor_ids": factors,
                "validation_status": "completed",
            }
            (artifacts / "implementation.json").write_text(json.dumps(artifact), encoding="utf-8")

            assessment = assess_agent_harness_run(root, expected_factors=factors)

            self.assertTrue(assessment.complete)
            self.assertEqual(assessment.defects, [])

    def test_missing_report_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            assessment = assess_agent_harness_run(tmp_dir, expected_factors=["Alpha3"])
            self.assertFalse(assessment.complete)
            self.assertIn("no JSON paper reproduction report was produced", assessment.defects)

    def test_formula_wide_required_field_superset_is_incomplete(self) -> None:
        records = [{"factor_name": "alpha", "formula": "rank(close)", "required_fields": ["open", "close", "volume"]}]
        from research_core.factor_lab.paper_reproduction.agent_harness_review import _formula_requirement_defects

        self.assertEqual(
            _formula_requirement_defects(records),
            ["factor alpha has formula-unrelated standard required fields: ['open', 'volume']"],
        )

    def test_deferred_evaluation_record_is_not_execution_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            runtime = root / "runtime" / "factor_lab"
            reports = runtime / "reports"
            artifacts = runtime / "implementation_artifacts"
            reports.mkdir(parents=True)
            artifacts.mkdir(parents=True)
            report = {
                "summary": {"next_stage": "complete"},
                "pipeline": {
                    "stages": [
                        {"name": name, "execution_status": "completed"}
                        for name in EXPECTED_STAGES
                    ]
                },
                "factors": [
                    {
                        "factor_name": "Alpha3",
                        "formula": "open",
                        "required_fields": ["open"],
                        "evaluation_executions": [{"lifecycle_state": "deferred_by_budget"}],
                        "truth_results": [{"status": "not_evaluated"}],
                    }
                ],
                "tests_run": ["python -m unittest"],
            }
            report_path = reports / "demo_paper_reproduction_report.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            report_path.with_suffix(".md").write_text("# Report\n", encoding="utf-8")
            (artifacts / "implementation.json").write_text(
                json.dumps(
                    {
                        "schema_version": "factor_implementation_artifact/v1",
                        "implemented_factor_ids": ["Alpha3"],
                        "validation_status": "completed",
                    }
                ),
                encoding="utf-8",
            )

            assessment = assess_agent_harness_run(root, expected_factors=["Alpha3"])

            self.assertFalse(assessment.complete)
            self.assertIn(
                "selected factors lack executed evaluation records: ['Alpha3']",
                assessment.defects,
            )


if __name__ == "__main__":
    unittest.main()
