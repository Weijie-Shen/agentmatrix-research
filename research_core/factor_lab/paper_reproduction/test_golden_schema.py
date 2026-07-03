from __future__ import annotations

import json
import unittest
from pathlib import Path


class GoldenSchemaTest(unittest.TestCase):
    def test_huatai_golden_uses_evaluation_case_schema(self) -> None:
        path = Path("research_core/factor_lab/paper_reproduction/golden/huatai_alpha3_13_15.json")
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], "paper_reproduction_golden_v0.2")
        self.assertIn("transform_definitions", payload)
        self.assertIn("evaluation_method_definitions", payload)

        alpha3 = payload["factors"]["Alpha3"]
        self.assertIn("formula_definition", alpha3)
        self.assertNotIn("preprocessing_rules", alpha3)
        self.assertNotIn("neutralization_rules", alpha3)
        self.assertIn("evaluation_cases", alpha3)

        case_ids = {case["case_id"] for case in alpha3["evaluation_cases"]}
        self.assertIn("alpha3_table52_industry_size_t20_ic_regression", case_ids)
        self.assertIn("alpha3_table14_unneutralized_t20_ic_decay", case_ids)
        self.assertIn("alpha3_table36_industry_size_t20_top_layer", case_ids)

        table52 = next(case for case in alpha3["evaluation_cases"] if case["case_id"] == "alpha3_table52_industry_size_t20_ic_regression")
        self.assertEqual(table52["evaluation_family"], "ic_regression")
        self.assertEqual(table52["transform_spec_id"], "industry_market_cap_neutralized")
        self.assertEqual(table52["evaluation_spec"]["return_horizon"], 20)
        self.assertEqual(table52["paper_truth"]["metrics"]["rank_ic_mean"], 0.0629)
        self.assertEqual(table52["required_data"]["controls"], ["industry", "market_cap_or_log_market_cap"])

        top_layer = next(case for case in alpha3["evaluation_cases"] if case["case_id"] == "alpha3_table36_industry_size_t20_top_layer")
        self.assertEqual(top_layer["evaluation_family"], "layered_portfolio_backtest")
        self.assertEqual(top_layer["evaluation_spec"]["execution_price"], "next_day_vwap")
        self.assertIn("vwap_or_amount_and_volume_for_portfolio_execution", top_layer["required_data"]["evaluation"])


if __name__ == "__main__":
    unittest.main()
