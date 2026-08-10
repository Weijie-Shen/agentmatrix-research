from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from contracts.factor_research import FactorResearchSpec
from research_core.factor_lab.paper_reproduction.extraction import ExtractedFactor, ExtractedTruthSource, PaperExtraction
from research_core.factor_lab.paper_reproduction.evaluators import apply_transform_spec
from research_core.factor_lab.paper_reproduction.normalization import (
    default_transform_spec,
    normalize_extraction_to_specs,
    write_specs_module,
)
from research_core.factor_lab.registry import export_library_specs
from research_core.factor_lab.runtime import FactorLabWorkspaceConfig


class PaperNormalizationTest(unittest.TestCase):
    def _extraction(self) -> PaperExtraction:
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
                    sample_period="2020-01-01 to 2020-12-31",
                    universe="liquid common stocks",
                    description="Daily close-to-open return.",
                    truth_sources=[
                        ExtractedTruthSource(
                            truth_id="pv_close_to_open_table_3_evaluation",
                            truth_type="evaluation_results",
                            description="Table 3 reports rank IC and IR.",
                            source_location="Table 3",
                            evaluation_method="daily rank IC and long-short quintile spread",
                            evaluation_family="ic_analysis",
                            evaluation_spec={"return_horizon": 20, "ic_type": "spearman_rank_ic"},
                            transform_spec={"steps": [{"name": "adjust_prices", "source": "fixture"}]},
                            required_data={
                                "formula": ["open", "close"],
                                "evaluation": ["forward_return_20d", "vwap"],
                                "controls": ["industry", "market_cap"],
                            },
                            metrics={"rank_ic_mean": 0.042, "rank_ic_ir": 0.31},
                        ),
                    ],
                ),
                ExtractedFactor(
                    factor_name="pv_volume_momentum_5d",
                    formula="volume / mean(volume, 5) - 1",
                    required_fields=["volume"],
                    frequency="day",
                    sample_period="2020-01-01 to 2020-12-31",
                    universe="liquid common stocks",
                    description="Volume relative to its 5-day moving average.",
                    parameters={"window": 5},
                    truth_sources=[
                        ExtractedTruthSource(
                            truth_id="pv_volume_table_3_evaluation",
                            truth_type="evaluation_results",
                            description="Table 3 reports evaluation metrics.",
                            source_location="Table 3",
                            evaluation_method="daily rank IC and long-short quintile spread",
                            evaluation_family="ic_analysis",
                            evaluation_spec={"return_horizon": 20, "ic_type": "spearman_rank_ic"},
                            transform_spec={"steps": [{"name": "sort_panel", "source": "fixture"}]},
                            required_data={"formula": ["volume"], "evaluation": ["forward_return_20d"]},
                            metrics={"rank_ic_mean": 0.018, "rank_ic_ir": 0.12},
                        ),
                    ],
                ),
            ],
        )

    def test_normalize_extraction_to_factor_research_specs_preserves_evaluation_truth(self) -> None:
        specs = normalize_extraction_to_specs(self._extraction(), version="v2026.06")

        self.assertEqual(len(specs), 2)
        self.assertTrue(all(isinstance(spec, FactorResearchSpec) for spec in specs))

        first = specs[0]
        self.assertEqual(first.factor_name, "pv_close_to_open")
        self.assertEqual(first.library, "SimplePV")
        self.assertEqual(first.version, "v2026.06")
        self.assertEqual(first.source_document, "Simple Price-Volume Signals (Factor Lab fixture, 2026)")
        self.assertEqual(first.frequency, "day")
        self.assertEqual(first.sample_scope, "2020-01-01 to 2020-12-31; universe: liquid common stocks")
        self.assertEqual(first.required_fields, ["open", "close"])
        self.assertEqual(first.preprocessing, [])
        threshold_metrics = {threshold.metric for threshold in first.validation_targets}
        self.assertIn("formula_match_ratio", threshold_metrics)
        self.assertIn("field_mapping_match_ratio", threshold_metrics)
        self.assertIn("paper_evaluation_metric_match_ratio", threshold_metrics)
        self.assertEqual(first.metadata["paper_id"], "simple_price_volume_demo")
        self.assertEqual(first.metadata["proof_status_ceiling"], "paper_evaluation_match")
        self.assertEqual(first.metadata["implementation_stage"], "spec")
        self.assertEqual(first.metadata["extraction_validation"]["status"], "implemented")
        self.assertEqual(first.metadata["truth_sources"][0]["truth_type"], "evaluation_results")
        self.assertEqual(first.metadata["selected_truth_sources"][0]["truth_type"], "evaluation_results")
        self.assertEqual(first.metadata["data_requirements"]["formula_required_fields"], ["open", "close"])
        self.assertEqual(first.metadata["evaluation_cases"][0]["evaluation_family"], "ic_analysis")
        self.assertEqual(first.metadata["evaluation_cases"][0]["evaluation_spec"]["return_horizon"], 20)
        self.assertEqual(first.metadata["evaluation_cases"][0]["required_data"]["evaluation"], ["forward_return_20d", "vwap"])
        self.assertEqual(
            first.metadata["evaluation_cases"][0]["defaulted_transform_steps"],
            ["winsorization", "standardization", "missing_value_policy"],
        )
        self.assertEqual(first.metadata["truth_source_summary"]["available_truth_count"], 1)
        self.assertIn("paper-evaluation-truth", first.tags)

    def test_default_transform_spec_inserts_missing_common_steps(self) -> None:
        transform = default_transform_spec({"steps": []})

        steps = transform["steps"]
        self.assertEqual([step["name"] for step in steps], ["winsorization", "standardization", "missing_value_policy"])
        self.assertEqual(steps[0]["method"], "median_mad")
        self.assertEqual(steps[0]["threshold"], 5)
        self.assertEqual(steps[1]["method"], "cross_section_zscore")
        self.assertEqual(steps[2]["method"], "do_not_fill")
        self.assertEqual(transform["defaulted_transform_steps"], ["winsorization", "standardization", "missing_value_policy"])

    def test_default_transform_spec_does_not_override_explicit_none(self) -> None:
        transform = default_transform_spec(
            {
                "steps": [
                    {"name": "winsorization", "method": "none", "source": "explicit"},
                    {"name": "standardization", "method": "none", "source": "explicit"},
                    {"name": "missing_value_policy", "method": "none", "source": "explicit"},
                ]
            }
        )

        self.assertEqual([step["method"] for step in transform["steps"]], ["none", "none", "none"])
        self.assertEqual(transform["defaulted_transform_steps"], [])

    def test_default_transform_spec_replaces_unknown_not_specified_common_steps(self) -> None:
        transform = default_transform_spec(
            {
                "steps": [
                    {"name": "winsorization", "method": "unknown", "source": "not_specified"},
                    {"name": "standardization", "method": "unknown", "source": "not_specified"},
                    {"name": "missing_value_policy", "method": "unknown", "source": "not_specified"},
                ]
            }
        )

        self.assertEqual([step["method"] for step in transform["steps"]], ["median_mad", "cross_section_zscore", "do_not_fill"])
        self.assertTrue(all(step["source"] == "default_assumed" for step in transform["steps"]))
        self.assertTrue(all(step["original_method"] == "unknown" for step in transform["steps"]))

    def test_defaulted_transform_spec_is_executable(self) -> None:
        import pandas as pd

        frame = pd.DataFrame(
            {
                "date": ["2026-01-01", "2026-01-01", "2026-01-01", "2026-01-02", "2026-01-02", "2026-01-02"],
                "code": ["a", "b", "c", "a", "b", "c"],
                "factor": [1.0, 2.0, 100.0, 4.0, 5.0, 6.0],
            }
        )

        transformed = apply_transform_spec(frame, value_col="factor", transform_spec=default_transform_spec({}))

        self.assertIn("processed_factor", transformed.columns)
        self.assertEqual(len(transformed), len(frame))

    def test_structured_neutralization_does_not_receive_duplicate_global_transform_defaults(self) -> None:
        extraction = self._extraction()
        truth = extraction.target_factors[0].truth_sources[0]
        truth.transform_spec = {}
        truth.neutralization_spec = {
            "method": "cross_sectional_regression_residual",
            "source": "explicit",
            "dependent_variable": {
                "field": "factor_value",
                "source": "explicit",
                "transforms": [{"method": "median_mad", "source": "explicit"}],
            },
            "controls": [
                {
                    "paper_field": "market_cap",
                    "source": "explicit",
                    "transforms": [{"method": "log", "source": "explicit"}],
                }
            ],
            "output_transforms": [{"method": "cross_section_zscore", "source": "explicit"}],
        }

        case = normalize_extraction_to_specs(extraction)[0].metadata["evaluation_cases"][0]

        self.assertEqual(case["transform_spec"], {})
        self.assertEqual(case["defaulted_transform_steps"], [])
        self.assertEqual(case["neutralization_spec"]["controls"][0]["transforms"][0]["method"], "log")

    def test_normalization_preserves_human_review_status_and_factor_ambiguities(self) -> None:
        extraction = self._extraction()
        extraction.target_factors[0].ambiguous_or_missing_information = [
            "Formula rank direction is ambiguous.",
            "Evaluation uses IC but does not state whether it is Pearson or rank IC.",
        ]

        specs = normalize_extraction_to_specs(extraction, version="v2026.06")

        first = specs[0]
        self.assertEqual(first.metadata["status"], "needs_human_review")
        self.assertEqual(first.metadata["extraction_validation"]["status"], "needs_human_review")
        self.assertEqual(
            first.metadata["factor_ambiguities_by_category"],
            {
                "formula": ["target_factors[0]: Formula rank direction is ambiguous."],
                "field_mapping": [],
                "evaluation": [
                    "target_factors[0]: Evaluation uses IC but does not state whether it is Pearson or rank IC."
                ],
                "other": [],
            },
        )

    def test_normalized_specs_can_export_catalog_and_specs_json(self) -> None:
        specs = normalize_extraction_to_specs(self._extraction(), version="v2026.06")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workspace = FactorLabWorkspaceConfig(data_root=root / "data", runtime_root=root / "runtime")
            payload = export_library_specs(config=workspace, library="simplepv", specs=specs)

            self.assertEqual(payload["count"], 2)
            spec_payload = json.loads(workspace.specs_path("simplepv").read_text(encoding="utf-8"))
            catalog_payload = json.loads(workspace.catalog_path("simplepv").read_text(encoding="utf-8"))
            self.assertEqual(spec_payload["items"][0]["metadata"]["paper_id"], "simple_price_volume_demo")
            self.assertEqual(catalog_payload["items"][0]["status"], "planned")
            self.assertEqual(catalog_payload["items"][0]["implementation_stage"], "spec")

    def test_write_specs_module_creates_importable_specs_function_without_factor_code(self) -> None:
        specs = normalize_extraction_to_specs(self._extraction(), version="v2026.06")
        with tempfile.TemporaryDirectory() as tmp_dir:
            module_path = write_specs_module(Path(tmp_dir) / "simplepv", specs, function_name="simplepv_specs")

            self.assertEqual(module_path.name, "specs.py")
            content = module_path.read_text(encoding="utf-8")
            self.assertIn("def simplepv_specs() -> list[FactorResearchSpec]:", content)
            self.assertIn("pv_close_to_open", content)
            self.assertFalse((module_path.parent / "factors.py").exists())

            module_spec = importlib.util.spec_from_file_location("simplepv_specs", module_path)
            self.assertIsNotNone(module_spec)
            self.assertIsNotNone(module_spec.loader)
            module = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(module)
            imported_specs = module.simplepv_specs()
            self.assertEqual([spec.factor_name for spec in imported_specs], ["pv_close_to_open", "pv_volume_momentum_5d"])


if __name__ == "__main__":
    unittest.main()
