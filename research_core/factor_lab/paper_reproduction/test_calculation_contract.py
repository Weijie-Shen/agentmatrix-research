from __future__ import annotations

import unittest

import pandas as pd

from contracts.factor_research import FactorResearchSpec
from research_core.factor_lab.paper_reproduction.calculation_contract import (
    CALCULATION_CONTRACT_SCHEMA_VERSION,
    TEST_EXCHANGE_SESSION_DISTANCE,
    TEST_LITERAL_PARAMETER_UNITS,
    TEST_NATURAL_MONTH_BOUNDARY,
    TEST_PRE_SAMPLE_HISTORY,
    TEST_WEIGHTED_DENOMINATOR,
    validate_factor_calculation_contract,
)
from research_core.factor_lab.paper_reproduction.data_validation import (
    DataFrameValidationRequest,
    validate_input_frame,
)
from research_core.factor_lab.paper_reproduction.evaluation_recipe import GLOBAL_EVALUATION_POLICY_ID
from research_core.factor_lab.paper_reproduction.extraction import (
    ExtractedFactorDefinition,
    ExtractedMetricDefinition,
    ExtractedRecipeTruthSource,
    ExtractedSemanticRequirement,
    ICRecipePaperExtraction,
    validate_paper_extraction,
)
from research_core.factor_lab.paper_reproduction.implementation import build_implementation_manifest
from research_core.factor_lab.paper_reproduction.normalization import normalize_extraction_to_specs


def _contract(months: int = 6) -> dict:
    return {
        "schema_version": CALCULATION_CONTRACT_SCHEMA_VERSION,
        "source_parameters": {
            "N": {"value": months, "unit": "natural_month", "role": "lookback and decay scale"}
        },
        "window": {
            "method_id": "window.trailing_natural_months",
            "length": months,
            "source_parameter": "N",
            "endpoint_rule": "exchange_month_end_to_exchange_month_end",
        },
        "aggregation": {
            "method_id": "aggregation.weighted_mean",
            "value_expression": "daily_return",
            "weight_expression": "turnover * exp(-exchange_session_distance / N / 4)",
            "normalization": "sum_weighted_values_divided_by_sum_weights",
        },
        "distance": {"method_id": "distance.exchange_sessions"},
        "runtime_conversions": [],
        "history": {
            "mode": "full_history_before_scoring",
            "required_pre_sample_periods": months,
            "unit": "natural_month",
        },
        "required_semantic_test_ids": [
            TEST_WEIGHTED_DENOMINATOR,
            TEST_LITERAL_PARAMETER_UNITS,
            TEST_NATURAL_MONTH_BOUNDARY,
            TEST_EXCHANGE_SESSION_DISTANCE,
            TEST_PRE_SAMPLE_HISTORY,
        ],
    }


def _recipe() -> dict:
    return {
        "global_policy_ref": GLOBAL_EVALUATION_POLICY_ID,
        "sampling": {
            "start": "2020-06-30",
            "end": "2020-12-31",
            "signal_schedule": "natural_month_end",
            "universe": {"description": "all A shares"},
        },
        "preprocessing_steps": [{"order": 1, "method_id": "factor_missing.drop"}],
        "return_label": {
            "method_id": "return.forward_close_to_close",
            "interval_type": "following_whole_natural_month",
            "horizon_natural_months": 1,
            "output_field": "forward_return_1m",
        },
        "ic_method": {"method_id": "ic.pearson"},
        "metric_methods": [{"method_id": "metric.ic_mean"}],
    }


def _extraction(*, contract: dict | None = None) -> ICRecipePaperExtraction:
    resolved_contract = dict(contract or {})
    source_n = ((resolved_contract.get("source_parameters", {}) or {}).get("N", {}) or {}).get(
        "value", 6
    )
    source_unit = ((resolved_contract.get("source_parameters", {}) or {}).get("N", {}) or {}).get(
        "unit", "natural_month"
    )
    factor = ExtractedFactorDefinition(
        factor_id="exp_wgt_return_6m",
        paper_label="exp_wgt_return_6m",
        formula=(
            "sum(daily_return * turnover * exp(-exchange_session_distance / N / 4)) / "
            "sum(turnover * exp(-exchange_session_distance / N / 4))"
        ),
        required_semantic_fields=["adjusted_close", "daily_turnover"],
        native_frequency="natural_month_end",
        parameters={"N": {"value": source_n, "unit": source_unit}},
        calculation_contract=resolved_contract,
    )
    truth = ExtractedRecipeTruthSource(
        truth_source_id="table_ic",
        source={"page": 10, "table": "IC results"},
        covered_factor_ids=[factor.factor_id],
        evaluation_recipe=_recipe(),
        reported_metric_ids=["ic_mean"],
        reported_results={factor.factor_id: {"ic_mean": -0.077}},
    )
    return ICRecipePaperExtraction(
        artifact_id="calculation-contract-test",
        paper={"paper_id": "calculation-contract-test", "title": "Contract test"},
        factor_family_name="contract_test",
        factor_definitions=[factor],
        semantic_requirements=[
            ExtractedSemanticRequirement("adjusted_close", "market_data", "adjusted_close"),
            ExtractedSemanticRequirement("daily_turnover", "market_data", "daily_turnover_rate"),
        ],
        metric_definitions=[
            ExtractedMetricDefinition("ic_mean", "IC mean", "mean Pearson IC", "decimal")
        ],
        truth_sources=[truth],
        factor_truth_selection={factor.factor_id: truth.truth_source_id},
    )


class FactorCalculationContractTest(unittest.TestCase):
    def test_v3_extraction_blocks_temporal_weighted_formula_without_contract(self) -> None:
        validation = validate_paper_extraction(_extraction())

        self.assertFalse(validation.valid)
        self.assertTrue(any("calculation_contract is required" in error for error in validation.errors))

    def test_contract_rejects_wrong_weighted_denominator(self) -> None:
        contract = _contract()
        contract["aggregation"]["normalization"] = "divide_by_observation_count"
        factor = _extraction(contract=contract).factor_definitions[0]

        errors = validate_factor_calculation_contract(factor)

        self.assertTrue(any("sum_weighted_values_divided_by_sum_weights" in error for error in errors))

    def test_contract_rejects_observation_count_substitution_for_literal_month_parameter(self) -> None:
        contract = _contract()
        contract["window"] = {
            "method_id": "window.trailing_security_observations",
            "length": 132,
            "source_parameter": "N",
        }
        contract["history"] = {
            "mode": "full_history_before_scoring",
            "required_pre_sample_periods": 132,
            "unit": "security_observation",
        }
        factor = _extraction(contract=contract).factor_definitions[0]

        errors = validate_factor_calculation_contract(factor)

        self.assertTrue(any("literal source parameter N" in error for error in errors))
        self.assertTrue(any("incompatible with literal source parameter unit" in error for error in errors))

    def test_contract_rejects_parameter_value_or_unit_that_differs_from_extraction(self) -> None:
        factor = _extraction(contract=_contract()).factor_definitions[0]
        factor.parameters["N"] = {"value": 132, "unit": "security_observation"}

        errors = validate_factor_calculation_contract(factor)

        self.assertTrue(any("parameters['N'].value differs" in error for error in errors))
        self.assertTrue(any("parameters['N'].unit differs" in error for error in errors))

    def test_normalization_preserves_contract_and_manifest_requires_semantic_tests(self) -> None:
        extraction = _extraction(contract=_contract())
        validation = validate_paper_extraction(extraction)
        self.assertTrue(validation.valid, validation.errors)

        spec = normalize_extraction_to_specs(extraction)[0]
        manifest = build_implementation_manifest([spec])

        self.assertEqual(spec.metadata["calculation_contract"], _contract())
        self.assertEqual(manifest.status, "ready_for_code")
        requirements = manifest.factors[0].test_requirements
        self.assertTrue(any(TEST_WEIGHTED_DENOMINATOR in item for item in requirements))
        self.assertTrue(any(TEST_NATURAL_MONTH_BOUNDARY in item for item in requirements))
        self.assertTrue(any(TEST_PRE_SAMPLE_HISTORY in item for item in requirements))

    def test_stage3_history_validation_blocks_panel_starting_at_score_sample(self) -> None:
        spec = normalize_extraction_to_specs(_extraction(contract=_contract(months=3)))[0]
        request = DataFrameValidationRequest.from_spec(spec)
        truncated = pd.DataFrame(
            {
                "date": pd.date_range("2020-06-01", "2020-06-30", freq="B"),
                "code": "A",
                "adjusted_close": 10.0,
                "turnover": 0.01,
            }
        )

        result = validate_input_frame(truncated, request)

        self.assertFalse(result.valid)
        self.assertTrue(any("starts after required pre-sample history" in error for error in result.errors))
        self.assertTrue(any("lacks the natural-month endpoint period" in error for error in result.errors))

    def test_stage3_history_validation_accepts_retained_natural_month_history(self) -> None:
        spec = normalize_extraction_to_specs(_extraction(contract=_contract(months=3)))[0]
        request = DataFrameValidationRequest.from_spec(spec)
        panel = pd.DataFrame(
            {
                "date": pd.date_range("2020-03-02", "2020-06-30", freq="B"),
                "code": "A",
                "adjusted_close": 10.0,
                "turnover": 0.01,
            }
        )

        result = validate_input_frame(panel, request)

        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.status, "passed")

    def test_security_observation_history_must_cover_every_scoring_security(self) -> None:
        contract = _contract(months=3)
        contract["source_parameters"]["N"]["unit"] = "security_observation"
        contract["window"] = {
            "method_id": "window.trailing_security_observations",
            "length": 3,
            "source_parameter": "N",
        }
        contract["history"]["unit"] = "security_observation"
        contract["required_semantic_test_ids"].remove(TEST_NATURAL_MONTH_BOUNDARY)
        spec = normalize_extraction_to_specs(_extraction(contract=contract))[0]
        request = DataFrameValidationRequest.from_spec(spec)
        panel = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    ["2020-06-24", "2020-06-25", "2020-06-26", "2020-06-30", "2020-06-30"]
                ),
                "code": ["A", "A", "A", "A", "B"],
                "adjusted_close": 10.0,
                "turnover": 0.01,
            }
        )

        result = validate_input_frame(panel, request)

        self.assertFalse(result.valid)
        self.assertTrue(any("1 scoring securities" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
