from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from research_core.factor_lab.paper_reproduction.agent_harness_review import (
    EXPECTED_STAGES,
    _execution_protocol_defects,
    _sample_boundary_defects,
    _v3_extraction_contract_defects,
    _v3_resolved_recipe_defects,
    assess_agent_harness_run,
)


class AgentHarnessRunAssessmentTest(unittest.TestCase):
    def _v3_recipe(self) -> dict[str, object]:
        return {
            "global_policy_ref": "china_a_share_ic_evaluation_v1",
            "sampling": {"signal_schedule": "every_trading_day"},
            "preprocessing_steps": [
                {"order": 1, "method_id": "factor_missing.drop", "execution_mode": "apply"},
                {
                    "order": 2,
                    "method_id": "neutralize.cross_sectional_regression_residual",
                    "execution_mode": "apply",
                    "controls": [
                        {
                            "semantic_input": "market_cap",
                            "resolved_field": "market_cap",
                            "transforms": [
                                {
                                    "method_id": "transform.natural_log",
                                    "execution_mode": "reuse_materialized",
                                    "resolved_field": "log_market_cap",
                                }
                            ],
                        }
                    ],
                },
            ],
            "return_label": {
                "method_id": "return.forward_close_to_close",
                "horizon_exchange_days": 1,
            },
            "ic_method": {"method_id": "ic.spearman_rank"},
            "metric_methods": [{"method_id": "metric.rank_ic_mean"}],
            "global_policy_bindings": {
                "st_or_pt_status": "is_st",
                "next_day_suspension_status": "next_is_suspended",
            },
            "resolution": {"status": "resolved", "blocked_reasons": []},
        }

    def test_v3_gate_requires_stage1_selection_and_resolved_value_states(self) -> None:
        recipe = self._v3_recipe()
        immutable_recipe = json.loads(json.dumps(recipe))
        immutable_recipe.pop("global_policy_bindings")
        immutable_recipe.pop("resolution")
        for step in immutable_recipe["preprocessing_steps"]:
            step.pop("execution_mode")
            for control in step.get("controls", []):
                control.pop("resolved_field", None)
                for transform in control.get("transforms", []):
                    transform.pop("execution_mode", None)
                    transform.pop("resolved_field", None)
        extraction = {
            "schema_version": "paper_extraction.ic_recipe.v3",
            "factor_definitions": [
                {"factor_id": "alpha", "required_semantic_fields": ["close"]}
            ],
            "semantic_requirements": [
                {"semantic_field_id": "close", "kind": "market_data", "concept": "daily_close_price"}
            ],
            "metric_definitions": [{"metric_id": "rank_ic_mean"}],
            "truth_sources": [
                {
                    "truth_source_id": "truth",
                    "covered_factor_ids": ["alpha"],
                    "evaluation_recipe": immutable_recipe,
                    "reported_metric_ids": ["rank_ic_mean"],
                    "reported_results": {"alpha": {"rank_ic_mean": 0.05}},
                }
            ],
            "factor_truth_selection": {"alpha": "truth"},
        }
        self.assertEqual(_v3_extraction_contract_defects(extraction), [])
        selected = {
            "truth_id": "truth",
            "evaluation_recipe": immutable_recipe,
            "selection_reason": "truth source fixed during Stage 1 extraction",
            "support_assessment": {"assessment_id": "support-1"},
            "resolved_protocol": {"resolved_evaluation_recipe": recipe},
        }
        self.assertEqual(
            _v3_resolved_recipe_defects("alpha", selected, extraction["truth_sources"][0]),
            [],
        )
        selected["selection_reason"] = "highest support score"
        defects = _v3_resolved_recipe_defects("alpha", selected, extraction["truth_sources"][0])
        self.assertTrue(any("Stage-1 authority" in defect for defect in defects))

    def test_v3_protocol_gate_checks_global_policy_and_ordered_recipe_trace(self) -> None:
        recipe = self._v3_recipe()
        selected = {
            "truth_id": "truth",
            "paper_protocol": {"evaluation_recipe": recipe},
            "resolved_protocol": {
                "resolved_evaluation_recipe": recipe,
                "evaluation_spec": {"ic_type": "spearman_rank_ic"},
            },
        }
        output = {
            "status": "passed",
            "transform_applied": True,
            "neutralization_diagnostics": [
                {"order": 2, "controls": [{"resolved_field": "market_cap"}]}
            ],
            "metrics": {"rank_ic_mean": 0.01},
            "resolved_parameters": {
                "evaluation_recipe": recipe,
                "evaluation_spec": {"ic_type": "spearman_rank_ic"},
                "recipe_execution_trace": {
                    "global_policy": {
                        "policy_id": "china_a_share_ic_evaluation_v1",
                        "input_rows": 10,
                        "eligible_rows": 8,
                        "excluded_rows": 2,
                        "status_bindings": {
                            "st_or_pt_status": "is_st",
                            "next_day_suspension_status": "next_is_suspended",
                        },
                    },
                    "preprocessing_trace": [
                        {"order": 1, "method_id": "factor_missing.drop", "execution_mode": "apply"},
                        {
                            "order": 2,
                            "method_id": "neutralize.cross_sectional_regression_residual",
                            "execution_mode": "apply",
                        },
                    ],
                    "neutralization_steps": [{"order": 2}],
                },
            },
        }
        execution = {
            "source_truth_id": "truth",
            "evaluator_output": output,
            "universe_diagnostics": {"skipped_filters": []},
        }
        factor_plan = {"selected_evaluation_cases": [selected]}
        self.assertEqual(_execution_protocol_defects("alpha", execution, factor_plan), [])
        output["resolved_parameters"]["recipe_execution_trace"]["preprocessing_trace"].reverse()
        defects = _execution_protocol_defects("alpha", execution, factor_plan)
        self.assertTrue(any("preprocessing trace differs" in defect for defect in defects))

    def test_complete_run_requires_reports_stages_factors_evaluation_and_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            factors = ["Alpha3", "Alpha13"]
            self._write_complete_fixture(root, factors)

            assessment = assess_agent_harness_run(root, expected_factors=factors)

            self.assertTrue(assessment.complete)
            self.assertEqual(assessment.defects, [])

    def test_claimed_factor_test_coverage_requires_a_real_source_assertion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            factors = ["exp_wgt_return_3m", "exp_wgt_return_6m"]
            self._write_complete_fixture(root, factors)
            test_source = root / "research_core" / "factor_lab" / "libraries" / "demo" / "test_factors.py"
            test_source.write_text(
                "from .factors import compute\n\n"
                "def test_formula_exp_wgt_return_6m():\n"
                "    values = {'exp_wgt_return_6m': 1}\n"
                "    assert values['exp_wgt_return_6m'] == 1\n",
                encoding="utf-8",
            )
            source_hash = hashlib.sha256(test_source.read_bytes()).hexdigest()
            result_path = root / "runtime" / "factor_lab" / "test_results" / "pytest.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["test_source_hash"] = source_hash
            result_path.write_text(json.dumps(result), encoding="utf-8")
            report_path = root / "runtime" / "factor_lab" / "reports" / "demo_paper_reproduction_report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["tests_run"][0]["test_source_hash"] = source_hash
            report_path.write_text(json.dumps(report), encoding="utf-8")

            assessment = assess_agent_harness_run(root, expected_factors=factors)

            self.assertFalse(assessment.complete)
            self.assertTrue(
                any("no factor-specific assertion" in item for item in assessment.defects),
                assessment.defects,
            )

    def test_complete_run_accepts_shared_registry_ic_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            factors = ["alpha3", "alpha13"]
            self._write_complete_fixture(root, factors)
            extraction = {
                "schema_version": "paper_extraction.ic_analysis.v2",
                "factor_definitions": [
                    {
                        "factor_id": factor,
                        "formula": "close",
                        "required_semantic_fields": ["close"],
                        "formula_gap_ids": [],
                    }
                    for factor in factors
                ],
                "semantic_requirements": [
                    {"semantic_field_id": "close", "kind": "market_field", "concept": "close"}
                ],
                "universe_protocols": [{"universe_protocol_id": "all_a"}],
                "sample_periods": [{"sample_period_id": "full"}],
                "operation_pipelines": [{"operation_pipeline_id": "raw"}],
                "metric_definitions": [{"metric_id": "rank_ic_mean"}],
                "ic_analysis_contract": {"universe_protocol_id": "all_a"},
                "ic_protocols": [
                    {
                        "protocol_id": "raw_h20",
                        "sample_period_id": "full",
                        "operation_pipeline_id": "raw",
                    }
                ],
                "truth_sources": [
                    {
                        "truth_source_id": f"{factor}_truth",
                        "protocol_id": "raw_h20",
                        "source": {"page": 8, "table": "Table 7", "row": factor},
                        "reported_metric_ids": ["rank_ic_mean"],
                        "reported_results": {factor: {"rank_ic_mean": 0.05}},
                    }
                    for factor in factors
                ],
            }
            path = root / "runtime" / "factor_lab" / "paper_specs" / "extraction.json"
            path.write_text(json.dumps(extraction), encoding="utf-8")

            assessment = assess_agent_harness_run(root, expected_factors=factors)

            self.assertTrue(assessment.complete)
            self.assertEqual(assessment.defects, [])

    def test_complete_run_allows_additional_merged_cross_scenario_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_complete_fixture(root, ["Alpha3"])
            bundle_path = root / "runtime" / "factor_lab" / "evaluation_bundles" / "default.json"
            payload = json.loads(bundle_path.read_text(encoding="utf-8"))
            merged = dict(payload)
            merged["scenario_id"] = "combined_scenarios"
            merged["records"] = [payload["records"][0]]
            (bundle_path.parent / "combined.json").write_text(json.dumps(merged), encoding="utf-8")

            assessment = assess_agent_harness_run(root, expected_factors=["Alpha3"])

            self.assertTrue(assessment.complete, assessment.defects)

    def test_comparison_rows_are_bound_to_exact_execution_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_complete_fixture(root, ["Alpha3"])
            report_path = root / "runtime" / "factor_lab" / "reports" / "demo_paper_reproduction_report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["comparison_results"]["metric_rows"][0]["execution_id"] = "another-execution"
            report["comparison_results"]["primary_metric_rows"][0]["execution_id"] = "another-execution"
            report_path.write_text(json.dumps(report), encoding="utf-8")

            assessment = assess_agent_harness_run(root, expected_factors=["Alpha3"])

            self.assertFalse(assessment.complete)
            self.assertTrue(any("omits comparison row for" in item for item in assessment.defects))

    def test_comparison_row_requires_canonical_scenario_and_execution_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_complete_fixture(root, ["Alpha3"])
            report_path = root / "runtime" / "factor_lab" / "reports" / "demo_paper_reproduction_report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["comparison_results"]["metric_rows"][0]["scenario_id"] = ""
            report["comparison_results"]["primary_metric_rows"][0]["scenario_id"] = ""
            report_path.write_text(json.dumps(report), encoding="utf-8")

            assessment = assess_agent_harness_run(root, expected_factors=["Alpha3"])

            self.assertFalse(assessment.complete)
            self.assertTrue(any("comparison row lacks scenario_id" in item for item in assessment.defects))

    def test_gate_rejects_execution_with_reordered_immutable_operation_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_complete_fixture(root, ["Alpha3"])
            runtime = root / "runtime" / "factor_lab"
            pipeline_path = runtime / "evaluation_plans" / "plan.json"
            plan = json.loads(pipeline_path.read_text(encoding="utf-8"))
            selected = plan["factor_plans"][0]["selected_evaluation_cases"][0]
            selected["paper_protocol"] = {
                "operation_pipeline": {
                    "operations": [
                        {"order": 1, "type": "winsorize", "target": "factor"},
                        {"order": 2, "type": "standardize", "target": "factor"},
                        {"order": 3, "type": "neutralize", "target": "factor"},
                    ]
                }
            }
            pipeline_path.write_text(json.dumps(plan), encoding="utf-8")
            report_path = runtime / "reports" / "demo_paper_reproduction_report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["evaluation_plan"] = plan
            report["factors"][0]["selected_evaluation_cases"] = plan["factor_plans"][0]["selected_evaluation_cases"]
            output = report["factors"][0]["evaluation_executions"][0]["evaluator_output"]
            output["resolved_parameters"] = {
                "operation_pipeline_trace": [
                    {"order": 1, "type": "winsorize", "target": "factor", "method": "median_mad"},
                    {"order": 2, "type": "neutralize", "target": "factor", "method": "cross_sectional_regression_residual"},
                    {"order": 3, "type": "standardize", "target": "factor", "method": "cross_section_zscore"},
                ]
            }
            report_path.write_text(json.dumps(report), encoding="utf-8")

            assessment = assess_agent_harness_run(root, expected_factors=["Alpha3"])

            self.assertFalse(assessment.complete)
            self.assertTrue(any("operation pipeline does not preserve" in item for item in assessment.defects))

    def test_missing_report_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            assessment = assess_agent_harness_run(tmp_dir, expected_factors=["Alpha3"])
            self.assertFalse(assessment.complete)
            self.assertIn("[report] no JSON paper reproduction report was produced", assessment.defects)
            self.assertEqual(assessment.earliest_invalid_stage, "final_report")

    def test_formula_wide_required_field_superset_is_incomplete(self) -> None:
        records = [{"factor_name": "alpha", "formula": "rank(close)", "required_fields": ["open", "close", "volume"]}]
        from research_core.factor_lab.paper_reproduction.agent_harness_review import _formula_requirement_defects

        self.assertEqual(
            _formula_requirement_defects(records),
            ["[extraction] factor alpha has formula-unrelated standard required fields: ['open', 'volume']"],
        )

    def test_stage3_profiles_may_include_declared_sample_lookback_and_lookahead(self) -> None:
        factor_plans = {
            "alpha": {
                "selected_evaluation_cases": [
                    {"sample_period": "2020-01-31 to 2020-12-31"}
                ]
            }
        }
        covering_profiles = {
            "qfq": {
                "profiles": {
                    "alpha": {"date_min": "2019-07-31", "date_max": "2021-01-31"}
                }
            }
        }
        truncated_profiles = {
            "qfq": {
                "profiles": {
                    "alpha": {"date_min": "2020-02-29", "date_max": "2020-11-30"}
                }
            }
        }

        self.assertEqual(_sample_boundary_defects(covering_profiles, factor_plans), [])
        defects = _sample_boundary_defects(truncated_profiles, factor_plans)
        self.assertEqual(len(defects), 2)
        self.assertTrue(all("does not cover expected" in defect for defect in defects))

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
                "[evaluation] selected factors lack executed evaluation records: ['Alpha3']",
                assessment.defects,
            )

    def test_hand_shaped_execution_bundle_cannot_restate_paper_truth_as_calculated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_complete_fixture(root, ["Alpha3"])
            bundle_path = root / "runtime" / "factor_lab" / "evaluation_bundles" / "default.json"
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            record = bundle["records"][0]
            bundle_path.write_text(
                json.dumps(
                    {
                        "scenario_id": "default",
                        "records": [
                            {
                                "factor_name": "Alpha3",
                                "source_truth_id": record["source_truth_id"],
                                "truth_case_id": record["truth_case_id"],
                                "scenario_id": "default",
                                "lifecycle_state": "executed",
                                "implementation_source_hash": record["implementation_source_hash"],
                                "data_snapshot_hash": "a1" * 32,
                                "evaluator_output": {
                                    "status": "passed",
                                    "metrics": {"ic_mean": 0.05},
                                },
                                "universe_diagnostics": {"skipped_filters": []},
                                "error": "",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            assessment = assess_agent_harness_run(root, expected_factors=["Alpha3"])

            self.assertFalse(assessment.complete)
            self.assertTrue(any("not an evaluation_bundle/v2" in item for item in assessment.defects))

    def test_canonical_ic_summary_must_recompute_from_persisted_cross_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_complete_fixture(root, ["Alpha3"])
            bundle_path = root / "runtime" / "factor_lab" / "evaluation_bundles" / "default.json"
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["records"][0]["evaluator_output"]["metrics"]["ic_mean"] = 0.05
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

            assessment = assess_agent_harness_run(root, expected_factors=["Alpha3"])

            self.assertFalse(assessment.complete)
            self.assertTrue(any("inconsistent with ic_values" in item for item in assessment.defects))

    def test_rejects_zero_assessed_selected_lineage_and_missing_neutralization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_complete_fixture(root, ["Growth"])
            runtime = root / "runtime" / "factor_lab"
            plan_path = runtime / "evaluation_plans" / "plan.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["factor_plans"][0]["assessed_evaluation_cases"] = []
            plan["factor_plans"][0]["selected_evaluation_cases"] = []
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            report_path = runtime / "reports" / "demo_paper_reproduction_report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["evaluation_plan"] = plan
            report["factors"][0]["assessed_evaluation_cases"] = []
            report["factors"][0]["selected_evaluation_cases"] = []
            report["summary"]["truth_case_counts"]["truth_cases_assessed"] = 0
            report["summary"]["truth_case_counts"]["truth_cases_selected"] = 0
            report_path.write_text(json.dumps(report), encoding="utf-8")

            assessment = assess_agent_harness_run(root, expected_factors=["Growth"])

            self.assertFalse(assessment.complete)
            self.assertIn("[evaluation-lineage] Growth has zero assessed evaluation cases", assessment.defects)
            self.assertIn("[evaluation-lineage] Growth has zero selected evaluation cases", assessment.defects)
            self.assertEqual(assessment.earliest_invalid_stage, "evaluation")

    def test_rejects_skipped_protocol_empty_profiles_and_wrong_truth_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_complete_fixture(root, ["Growth"])
            report_path = root / "runtime" / "factor_lab" / "reports" / "demo_paper_reproduction_report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            execution = report["factors"][0]["evaluation_executions"][0]
            execution["universe_diagnostics"] = {
                "skipped_filters": [{"filter_name": "exclude_st_pt", "reason": "unresolved_filter_field"}]
            }
            report["data_profile_summaries"] = [{"source_id": "qfq", "row_count": 0}]
            truth_stage = next(stage for stage in report["pipeline"]["stages"] if stage["name"] == "paper_truth_validation")
            truth_stage["diagnostics"] = {"eligible_denominator": 56}
            report_path.write_text(json.dumps(report), encoding="utf-8")

            assessment = assess_agent_harness_run(root, expected_factors=["Growth"])

            self.assertFalse(assessment.complete)
            self.assertTrue(any("required universe filters skipped" in item for item in assessment.defects))
            self.assertTrue(any("zero-row data-profile" in item for item in assessment.defects))
            self.assertTrue(any("eligible denominator 56" in item for item in assessment.defects))
            self.assertTrue(
                any(action.startswith("Apply the mandatory global policy") for action in assessment.repair_actions)
            )

    def test_harvest_must_include_every_completed_stage_runtime_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_complete_fixture(root, ["Alpha3"])
            report_path = root / "runtime" / "factor_lab" / "reports" / "demo_paper_reproduction_report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            source_manifest = root / "runtime" / "factor_lab" / "source_evidence" / "source_manifest.json"
            source_manifest.parent.mkdir(parents=True, exist_ok=True)
            source_manifest.write_text("{}", encoding="utf-8")
            report["pipeline"]["stages"][0]["artifact_paths"] = [str(source_manifest)]
            report_path.write_text(json.dumps(report), encoding="utf-8")
            harvest_path = root / "harvest_manifest.json"
            harvest_path.write_text(
                json.dumps(
                    {
                        "review_ready": True,
                        "worktree": str(root),
                        "files": [],
                        "missing_required_artifact_families": [],
                        "omitted_files": [],
                    }
                ),
                encoding="utf-8",
            )

            assessment = assess_agent_harness_run(
                root,
                expected_factors=["Alpha3"],
                harvest_manifest_path=harvest_path,
            )

            self.assertFalse(assessment.complete)
            self.assertTrue(
                any("source_evidence/source_manifest.json" in item for item in assessment.defects),
                assessment.defects,
            )

    def _write_complete_fixture(self, root: Path, factors: list[str]) -> None:
        runtime = root / "runtime" / "factor_lab"
        for directory in (
            "reports",
            "implementation_artifacts",
            "paper_specs",
            "specs",
            "paper_jobs",
            "data_profiles",
            "evaluation_plans",
            "evaluation_bundles",
            "truth_matches",
            "test_results",
        ):
            (runtime / directory).mkdir(parents=True, exist_ok=True)
        module = root / "research_core" / "factor_lab" / "libraries" / "demo" / "factors.py"
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("def compute(panel):\n    return panel\n", encoding="utf-8")
        test_source = module.parent / "test_factors.py"
        test_source.write_text(
            "from .factors import compute\n\n"
            + "\n".join(
                f"def test_formula_{factor}():\n"
                f"    values = {{'{factor}': 1}}\n"
                f"    assert values['{factor}'] == 1\n"
                for factor in factors
            ),
            encoding="utf-8",
        )
        source_hash = hashlib.sha256(module.read_bytes()).hexdigest()
        test_source_hash = hashlib.sha256(test_source.read_bytes()).hexdigest()
        specification_hash = hashlib.sha256(b"demo-factor-specification").hexdigest()
        truth_id = {factor: f"{factor}_truth" for factor in factors}
        def selected_case(factor: str) -> dict[str, object]:
            return {
                "truth_case_id": truth_id[factor],
                "truth_id": truth_id[factor],
                "source_truth_id": truth_id[factor],
                "sample_period": "2020-01-31 to 2020-12-31",
                "resolved_protocol": {"transform_spec": {"steps": []}, "neutralization_spec": {}},
            }
        factor_plans = [
            {
                "factor_name": factor,
                "status": "ready_for_evaluation",
                "assessed_evaluation_cases": [{**selected_case(factor), "lifecycle_state": "assessed"}],
                "selected_evaluation_cases": [{**selected_case(factor), "lifecycle_state": "selected"}],
                "skipped_evaluation_cases": [],
                "unsupported_evaluation_cases": [],
                "deferred_evaluation_cases": [],
            }
            for factor in factors
        ]
        evaluation_plan = {"library": "demo", "status": "ready_for_evaluation", "factor_plans": factor_plans}
        extraction = {
            "paper_id": "demo",
            "title": "Demo",
            "authors": ["Author"],
            "factor_family_name": "demo",
            "target_factors": [
                {
                    "factor_name": factor,
                    "formula": "close",
                    "required_fields": ["close"],
                    "selected_truth_source_ids": [truth_id[factor]],
                    "ambiguous_or_missing_information": [],
                    "truth_sources": [
                        {
                            "truth_id": truth_id[factor],
                            "truth_type": "evaluation_results",
                            "source_location": "p. 8, Table 2",
                            "metrics": {"ic_mean": 0.05},
                        }
                    ],
                }
                for factor in factors
            ],
        }
        specs = {
            "items": [
                {"factor_name": factor, "metadata": {"status": "planned"}}
                for factor in factors
            ]
        }
        pipeline = {
            "job_id": "demo-job",
            "stages": [
                {"name": name, "execution_status": "completed", "limitations": []}
                for name in EXPECTED_STAGES
            ],
        }
        artifact = {
            "schema_version": "factor_implementation_artifact/v1",
            "module_path": str(module),
            "callable_import_path": "research_core.factor_lab.libraries.demo.factors:compute",
            "implemented_factor_ids": factors,
            "output_factor_columns": factors,
            "source_hash": source_hash,
            "factor_specification_hash": specification_hash,
            "validation_status": "completed",
        }
        executions: dict[str, dict[str, object]] = {}
        for factor in factors:
            resolved_protocol = selected_case(factor)["resolved_protocol"]
            identity = {
                "truth_case_id": truth_id[factor],
                "factor_id": factor,
                "scenario_id": "default",
                "evaluator_id": "generic_ic_v1",
                "implementation_source_hash": source_hash,
                "factor_specification_hash": specification_hash,
                "data_snapshot_hash": hashlib.sha256(b"snapshot-default").hexdigest(),
                "resolved_protocol": resolved_protocol,
            }
            encoded = json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
            executions[factor] = {
                "execution_id": f"execution-{hashlib.sha256(encoded).hexdigest()[:20]}",
                "source_truth_id": truth_id[factor],
                "truth_case_id": truth_id[factor],
                "factor_id": factor,
                "factor_name": factor,
                "scenario_id": "default",
                "evaluator_id": "generic_ic_v1",
                "lifecycle_state": "executed",
                "implementation_source_hash": source_hash,
                "factor_specification_hash": specification_hash,
                "data_snapshot_hash": hashlib.sha256(b"snapshot-default").hexdigest(),
                "resolved_protocol": resolved_protocol,
                "truth_match_eligible_metrics": ["ic_mean"],
                "diagnostic_only_metrics": [],
                "alignment_diagnostics": {"matched_rows": 100},
                "universe_diagnostics": {
                    "input_rows": 100,
                    "output_rows": 100,
                    "skipped_filters": [],
                },
                "evaluator_output": {
                    "status": "passed",
                    "execution_mode": "canonical_plan_executor",
                    "transform_applied": True,
                    "neutralization_diagnostics": {"used_controls": [], "skipped_controls": []},
                    "metrics": {
                        "ic_mean": 0.048,
                        "ic_std": 0.0014142135623730963,
                        "ic_ir": 33.94112549695425,
                        "ic_positive_ratio": 1.0,
                        "cross_section_count": 2,
                        "ic_values": [0.047, 0.049],
                    },
                },
                "error": None,
                "schema_version": "evaluation_execution_record/v1",
            }
        comparison_rows = [
            {
                "factor_name": factor,
                "scenario_id": "default",
                "execution_id": executions[factor]["execution_id"],
                "truth_id": truth_id[factor],
                "metric": "ic_mean",
                "paper_value": 0.05,
                "calculated_value": 0.048,
                "truth_match_eligible": True,
                "metric_role": "truth_match_eligible",
            }
            for factor in factors
        ]
        report = {
            "job_id": "demo-job",
            "summary": {
                "next_stage": "complete",
                "overall_status": "completed",
                "pipeline_overall_status": "completed",
                "truth_case_counts": {
                    "truth_cases_assessed": len(factors),
                    "truth_cases_selected": len(factors),
                    "truth_cases_executed": len(factors),
                },
            },
            "pipeline": {
                "job_id": "demo-job",
                "stages": [
                    {
                        "name": name,
                        "execution_status": "completed",
                        "limitations": [],
                        "diagnostics": {"status": "implemented"} if name == "paper_extraction" else {},
                    }
                    for name in EXPECTED_STAGES
                ],
            },
            "evaluation_plan": evaluation_plan,
            "data_profile_summaries": [{"source_id": "default", "row_count": 100}],
            "factors": [
                {
                    "factor_name": factor,
                    "formula": "close",
                    "required_fields": ["close"],
                    "assessed_evaluation_cases": factor_plans[index]["assessed_evaluation_cases"],
                    "selected_evaluation_cases": factor_plans[index]["selected_evaluation_cases"],
                    "evaluation_executions": [executions[factor]],
                    "diagnostic_only_metrics": [],
                    "truth_results": [
                        {
                            "source_truth_id": truth_id[factor],
                            "status": "approximately_consistent",
                            "lifecycle_state": "executed",
                            "diagnostics": {"eligible_metrics": ["ic_mean"]},
                        }
                    ],
                }
                for index, factor in enumerate(factors)
            ],
            "comparison_results": {
                "primary_metric_rows": comparison_rows,
                "metric_rows": comparison_rows,
            },
            "tests_run": [
                {
                    "command": "python -m pytest research_core/factor_lab/libraries/demo/test_factors.py -q",
                    "exit_code": 0,
                    "outcome": f"{len(factors)} passed",
                    "covered_factors": factors,
                    "test_source": str(test_source),
                    "test_source_hash": test_source_hash,
                    "frozen_implementation_hash": source_hash,
                    "assertion_coverage": {factor: ["exact_value"] for factor in factors},
                }
            ],
        }
        (runtime / "paper_specs" / "extraction.json").write_text(json.dumps(extraction), encoding="utf-8")
        (runtime / "specs" / "specs.json").write_text(json.dumps(specs), encoding="utf-8")
        (runtime / "paper_jobs" / "job.json").write_text(json.dumps(pipeline), encoding="utf-8")
        (runtime / "data_profiles" / "default.json").write_text(
            json.dumps({"row_count": 100}), encoding="utf-8"
        )
        (runtime / "evaluation_plans" / "plan.json").write_text(json.dumps(evaluation_plan), encoding="utf-8")
        (runtime / "implementation_artifacts" / "implementation.json").write_text(
            json.dumps(artifact), encoding="utf-8"
        )
        snapshot_hash = hashlib.sha256(b"snapshot-default").hexdigest()
        (runtime / "evaluation_bundles" / "default.json").write_text(
            json.dumps(
                {
                    "library": "demo",
                    "scenario_id": "default",
                    "data_snapshot_hash": snapshot_hash,
                    "implementation_artifact": {
                        "source_hash": source_hash,
                        "factor_specification_hash": specification_hash,
                    },
                    "records": list(executions.values()),
                    "limitations": [],
                    "resource_preflight": {
                        "schema_version": "resource_preflight/v1",
                        "execution_mode": "projected_in_memory",
                        "partition_required": False,
                        "active_scenario_count": 1,
                    },
                    "resource_telemetry": {
                        "calculation_rows": 100,
                        "evaluation_rows": 100,
                        "factor_rows": 100,
                        "active_scenario_count": 1,
                    },
                    "requested_execution": {"scenario_id": "default", "sample": {"row_count": 100}},
                    "executed_execution": {"scenario_id": "default", "sample": {"row_count": 100}},
                    "raw_factor_before_evaluation_filters": True,
                    "schema_version": "evaluation_bundle/v2",
                }
            ),
            encoding="utf-8",
        )
        (runtime / "truth_matches" / "truth.json").write_text(json.dumps({"results": []}), encoding="utf-8")
        (runtime / "test_results" / "pytest.json").write_text(
            json.dumps(
                {
                    "command": "python -m pytest research_core/factor_lab/libraries/demo/test_factors.py -q",
                    "exit_code": 0,
                    "outcome": f"{len(factors)} passed",
                    "covered_factors": factors,
                    "test_source": str(test_source),
                    "test_source_hash": test_source_hash,
                    "frozen_implementation_hash": source_hash,
                    "assertion_coverage": {factor: ["exact_value"] for factor in factors},
                }
            ),
            encoding="utf-8",
        )
        report_path = runtime / "reports" / "demo_paper_reproduction_report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        report_path.with_suffix(".md").write_text("# Report\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
