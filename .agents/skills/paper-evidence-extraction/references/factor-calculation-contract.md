# Factor calculation contract

Fresh v3 extraction must attach `factor_calculation_contract/v1` to every factor whose formula has a temporal window, weighted aggregation, decay distance, or source parameter whose unit can be confused with a runtime row count.

```json
{
  "schema_version": "factor_calculation_contract/v1",
  "source_parameters": {
    "N": {"value": 6, "unit": "natural_month", "role": "lookback and decay scale"}
  },
  "window": {
    "method_id": "window.trailing_natural_months",
    "length": 6,
    "source_parameter": "N",
    "endpoint_rule": "exchange_month_end_to_exchange_month_end"
  },
  "aggregation": {
    "method_id": "aggregation.weighted_mean",
    "value_expression": "daily_return",
    "weight_expression": "turnover * exp(-exchange_session_distance / N / 4)",
    "normalization": "sum_weighted_values_divided_by_sum_weights"
  },
  "distance": {"method_id": "distance.exchange_sessions"},
  "runtime_conversions": [],
  "history": {
    "mode": "full_history_before_scoring",
    "required_pre_sample_periods": 6,
    "unit": "natural_month"
  },
  "required_semantic_test_ids": [
    "weighted_mean_denominator_is_sum_of_weights",
    "literal_source_parameter_units",
    "natural_month_window_boundaries",
    "exchange_session_distance_advances_on_missing_security_rows",
    "first_scoring_date_has_full_history"
  ]
}
```

Available window method IDs are:

- `window.trailing_natural_months`;
- `window.trailing_exchange_sessions`;
- `window.trailing_security_observations`.

Do not encode a natural month as 20, 21, or 22 observations. Do not replace a month-valued `N` in another part of the formula with a derived observation count. A weighted mean always divides the weighted-value sum by the same complete weight sum.

The history requirement is formula input lineage, not evaluation sampling. Stage 3 loads and validates history before the score-sample start. The first score is not silently discarded as rolling warm-up.
