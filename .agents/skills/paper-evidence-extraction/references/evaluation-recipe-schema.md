# IC evaluation recipe schema

New jobs use `paper_extraction.ic_recipe.v3`.

Each factor definition is formula-only. Each truth source owns one homogeneous evaluation recipe and may contain many factor rows. `factor_truth_selection` maps every factor ID to exactly one truth source ID during Stage 1.

```json
{
  "schema_version": "paper_extraction.ic_recipe.v3",
  "factor_definitions": [],
  "semantic_requirements": [],
  "metric_definitions": [],
  "truth_sources": [{
    "truth_source_id": "table_7_financial",
    "source": {"page": 12, "table": "Table 7", "row_block": "financial factors"},
    "covered_factor_ids": ["factor_a", "factor_b"],
    "evaluation_recipe": {},
    "reported_metric_ids": ["rank_ic_mean", "rank_ic_ir"],
    "reported_results": {"factor_a": {}, "factor_b": {}}
  }],
  "factor_truth_selection": {"factor_a": "table_7_financial"}
}
```

A recipe contains `global_policy_ref`, `sampling`, ordered `preprocessing_steps`, `return_label`, `ic_method`, and `metric_methods`. Steps have contiguous one-based `order`, a catalog `method_id`, named semantic inputs/outputs, parameters, scope, and evidence. Split a printed table into multiple truth sources when row blocks use different recipes.

Extraction never stores local columns, physical files, resolved fields, or data value states.
