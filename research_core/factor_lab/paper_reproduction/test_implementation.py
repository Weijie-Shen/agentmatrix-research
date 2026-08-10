from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from contracts.factor_research import FactorResearchSpec, ValidationThreshold
from research_core.factor_lab.paper_reproduction.data_validation import DataFrameValidationResult
from research_core.factor_lab.paper_reproduction.implementation import (
    FactorImplementationValidationError,
    build_implementation_manifest,
    build_factor_implementation_artifact,
    execute_factor_callable,
    export_factor_implementation_artifact,
    export_implementation_manifest,
    factor_specification_hash,
    load_factor_implementation_artifact,
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

    def test_manifest_keeps_data_warnings_as_implementation_limitations(self) -> None:
        manifest = build_implementation_manifest(
            [self._spec()],
            data_validation_results={
                "paper_alpha_1": DataFrameValidationResult(
                    valid=True,
                    status="needs_human_review",
                    warnings=["max history is shorter than requested lookback"],
                ),
            },
        )

        self.assertEqual(manifest.status, "ready_for_code_with_limitations")
        self.assertEqual(manifest.factors[0].status, "ready_for_code_with_limitations")
        self.assertEqual(
            manifest.factors[0].metadata["data_validation_warnings"],
            ["max history is shorter than requested lookback"],
        )

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

    def test_canonical_artifact_imports_probes_hashes_and_round_trips(self) -> None:
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            module_path = root / "factor.py"
            module_path.write_text(
                "import pandas as pd\n\n"
                "def compute_factors(panel, factor_names=None):\n"
                "    names = factor_names or ['paper_alpha_1']\n"
                "    result = panel[['date', 'code']].copy()\n"
                "    for name in names:\n"
                "        result[name] = pd.to_numeric(panel['close']) * 2\n"
                "    return result\n",
                encoding="utf-8",
            )
            probe = pd.DataFrame(
                {
                    "date": ["2026-01-01", "2026-01-01"],
                    "code": ["A", "B"],
                    "close": [1.0, 2.0],
                    "volume": [10.0, 20.0],
                }
            )

            artifact = build_factor_implementation_artifact(
                [self._spec()],
                module_path=module_path,
                callable_import_path="compute_factors",
                probe_panel=probe,
            )

            self.assertEqual(artifact.validation_status, "completed")
            self.assertEqual(artifact.factor_columns_by_id, {"paper_alpha_1": "paper_alpha_1"})
            output = execute_factor_callable(artifact, probe)
            self.assertEqual(output["paper_alpha_1"].tolist(), [2.0, 4.0])

            artifact_path = export_factor_implementation_artifact(artifact, root / "artifact.json")
            loaded = load_factor_implementation_artifact(artifact_path)
            self.assertEqual(loaded.source_hash, artifact.source_hash)
            self.assertEqual(loaded.factor_specification_hash, artifact.factor_specification_hash)

    def test_canonical_artifact_rejects_unimplemented_scaffold(self) -> None:
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmp_dir:
            module_path = Path(tmp_dir) / "factor.py"
            module_path.write_text(
                "def compute_factors(panel, factor_names=None):\n"
                "    raise NotImplementedError('scaffold')\n",
                encoding="utf-8",
            )
            probe = pd.DataFrame(
                {"date": ["2026-01-01"], "code": ["A"], "close": [1.0], "volume": [10.0]}
            )

            with self.assertRaises(FactorImplementationValidationError) as caught:
                build_factor_implementation_artifact(
                    [self._spec()],
                    module_path=module_path,
                    callable_import_path="compute_factors",
                    probe_panel=probe,
                )

            self.assertIn("unimplemented scaffold", str(caught.exception))

    def test_artifact_execution_rejects_source_changed_after_certification(self) -> None:
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmp_dir:
            module_path = Path(tmp_dir) / "factor.py"
            module_path.write_text(
                "def compute_factors(panel, factor_names=None):\n"
                "    result = panel[['date', 'code']].copy()\n"
                "    result['paper_alpha_1'] = panel['close']\n"
                "    return result\n",
                encoding="utf-8",
            )
            probe = pd.DataFrame(
                {"date": ["2026-01-01"], "code": ["A"], "close": [1.0], "volume": [10.0]}
            )
            artifact = build_factor_implementation_artifact(
                [self._spec()],
                module_path=module_path,
                callable_import_path="compute_factors",
                probe_panel=probe,
            )
            module_path.write_text(module_path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "source changed"):
                execute_factor_callable(artifact, probe)

    def test_factor_specification_hash_excludes_notes_but_changes_with_formula(self) -> None:
        spec = self._spec()
        original = factor_specification_hash([spec])
        spec.notes.append("report-only note")
        self.assertEqual(factor_specification_hash([spec]), original)
        spec.formula = "rank(close)"
        self.assertNotEqual(factor_specification_hash([spec]), original)


if __name__ == "__main__":
    unittest.main()
