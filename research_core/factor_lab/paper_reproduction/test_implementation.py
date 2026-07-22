from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from contracts.factor_research import FactorResearchSpec, ValidationThreshold
from research_core.factor_lab.paper_reproduction.data_validation import DataFrameValidationResult
from research_core.factor_lab.paper_reproduction.implementation import (
    build_implementation_manifest,
    export_implementation_manifest,
    write_factor_family_scaffold,
)
from research_core.factor_lab.runtime import FactorLabWorkspaceConfig


class PaperImplementationScaffoldTest(unittest.TestCase):
    def _spec(self, *, ambiguous: bool = False) -> FactorResearchSpec:
        return FactorResearchSpec(
            factor_name="paper_alpha_1",
            library="PaperDemo",
            version="v0.1",
            formula="rank(custom_signal(close, volume, 20))",
            required_fields=["close", "volume"],
            frequency="day",
            parameters={"window": 20},
            validation_targets=[ValidationThreshold("formula_match_ratio", ">=", 1.0)],
            metadata={
                "paper_id": "paper_demo",
                "status": "needs_human_review" if ambiguous else "planned",
                "evaluator_implementation_targets": [
                    {
                        "evaluation_family": "layered_portfolio_backtest",
                        "suggested_function_name": "evaluate_paperdemo_layered_portfolio_backtest",
                        "reason": "No generic evaluator exists and no IC/regression truth source was available.",
                    }
                ],
                "factor_ambiguities_by_category": {
                    "formula": ["target_factors[0]: custom_signal is not defined"] if ambiguous else [],
                    "field_mapping": [],
                    "evaluation": [],
                    "other": [],
                },
                "truth_source_summary": {
                    "selected_truth_types": ["evaluation_results"],
                },
                "data_requirements": {
                    "formula_required_fields": ["close", "volume"],
                    "preprocessing_required_fields": ["adjusted_close"],
                    "neutralization_required_fields": ["industry", "market_cap"],
                    "evaluation_required_fields": ["forward_return_20d", "vwap"],
                },
                "known_limitations": ["Only aggregate paper evaluation metrics are available."],
            },
        )

    def test_manifest_marks_clear_factor_ready_and_lists_ai_function_design_items(self) -> None:
        manifest = build_implementation_manifest(
            [self._spec()],
            data_validation_results={
                "paper_alpha_1": DataFrameValidationResult(valid=True, status="passed"),
            },
        )

        self.assertEqual(manifest.family_name, "PaperDemo")
        self.assertEqual(manifest.factors[0].status, "ready_for_code")
        self.assertEqual(manifest.factors[0].suggested_function_name, "compute_paper_alpha_1")
        self.assertIn("custom_signal", manifest.factors[0].ai_designed_functions)
        self.assertIn("rank", manifest.factors[0].required_operator_hints)
        self.assertEqual(
            manifest.factors[0].metadata["data_requirements"]["evaluation_required_fields"],
            ["forward_return_20d", "vwap"],
        )
        self.assertEqual(manifest.factors[0].metadata["known_limitations"], ["Only aggregate paper evaluation metrics are available."])
        self.assertEqual(manifest.paper_local_evaluators[0]["evaluation_family"], "layered_portfolio_backtest")

    def test_manifest_blocks_ambiguous_factor_for_human_review(self) -> None:
        manifest = build_implementation_manifest(
            [self._spec(ambiguous=True)],
            data_validation_results={
                "paper_alpha_1": DataFrameValidationResult(valid=True, status="passed"),
            },
        )

        self.assertEqual(manifest.factors[0].status, "needs_human_review")
        self.assertIn("formula ambiguities must be resolved", manifest.factors[0].blocked_reasons)

    def test_manifest_blocks_missing_data_fields_as_blocked_by_data(self) -> None:
        manifest = build_implementation_manifest(
            [self._spec()],
            data_validation_results={
                "paper_alpha_1": DataFrameValidationResult(
                    valid=False,
                    status="failed",
                    errors=["missing required columns: volume"],
                ),
            },
        )

        self.assertEqual(manifest.factors[0].status, "blocked_by_data")
        self.assertIn("missing required columns: volume", manifest.factors[0].blocked_reasons)

    def test_manifest_exports_json_artifact(self) -> None:
        manifest = build_implementation_manifest([self._spec()])
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = FactorLabWorkspaceConfig(data_root=Path(tmp_dir) / "data", runtime_root=Path(tmp_dir) / "runtime")
            path = export_implementation_manifest(manifest, config=workspace)

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["family_name"], "PaperDemo")
            self.assertEqual(payload["factors"][0]["factor_name"], "paper_alpha_1")
            self.assertEqual(payload["paper_local_evaluators"][0]["suggested_function_name"], "evaluate_paperdemo_layered_portfolio_backtest")

    def test_scaffold_writer_creates_importable_unimplemented_dispatcher(self) -> None:
        manifest = build_implementation_manifest([self._spec()])
        with tempfile.TemporaryDirectory() as tmp_dir:
            family_dir = Path(tmp_dir) / "paperdemo"
            paths = write_factor_family_scaffold(manifest, family_dir)

            self.assertTrue(paths["factors"].exists())
            self.assertTrue(paths["tests"].exists())
            spec = importlib.util.spec_from_file_location("paperdemo_factors", paths["factors"])
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            self.assertEqual(module.IMPLEMENTED_PAPERDEMO_FACTORS, ())
            self.assertEqual(
                module.IMPLEMENTATION_MANIFEST["paper_local_evaluators"][0]["evaluation_family"],
                "layered_portfolio_backtest",
            )
            with self.assertRaises(NotImplementedError):
                module.compute_paperdemo_factors(None)


if __name__ == "__main__":
    unittest.main()
