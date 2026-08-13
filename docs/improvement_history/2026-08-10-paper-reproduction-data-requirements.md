# Paper Reproduction Pipeline Improvement Notes: Data Requirements and Replacements

- Date: 2026-08-10
- Status: Agreed direction; implementation pending
- Scope: General paper-factor reproduction pipeline
- Motivation: Improve automated reproduction across papers without hard-coding the requirements of any one paper

## Context

Paper reproduction frequently encounters incomplete data, ambiguous methodology, or data fields that are only approximate substitutes for the paper's original inputs. These conditions should not normally stop an automated run. The pipeline should execute the best-supported reproduction that available data permits and clearly report any resulting limitations.

The changes below must remain paper-agnostic. Paper-specific details, including particular industry taxonomies, capitalization definitions, or neutralization models, should enter the pipeline through extracted specifications rather than hard-coded evaluator behavior.

## Agreed Improvements

### 1. Extract neutralization and control transformations

Paper extraction should pay explicit attention to transformations applied to:

- the tested factor;
- neutralization controls;
- regression controls;
- regression weights;
- return labels or other evaluation inputs.

The extracted paper specification should preserve the ordered transformation sequence and distinguish explicitly stated methodology from inference or pipeline defaults.

Illustrative structure:

```json
{
  "neutralization": {
    "method": "cross_sectional_regression_residual",
    "dependent_variable": {
      "field": "factor_value",
      "transforms": [
        {"method": "median_mad", "threshold": 5}
      ]
    },
    "controls": [
      {
        "semantic_role": "size_control",
        "paper_field": "total_market_cap",
        "transforms": [
          {"method": "log"},
          {"method": "median_mad", "threshold": 5}
        ]
      },
      {
        "semantic_role": "industry_control",
        "paper_field": "industry_classification",
        "encoding": "dummy",
        "taxonomy": "paper_extracted_value",
        "level": "paper_extracted_value",
        "temporal_requirement": "paper_extracted_value"
      }
    ],
    "output_transforms": [
      {"method": "cross_section_zscore"}
    ]
  }
}
```

Each extracted choice or transformation should be attributable:

```json
{
  "source": "explicit | inferred | defaulted",
  "source_location": "page, table, figure, or section",
  "confidence": 0.0
}
```

The schema must support arbitrary ordered transformations rather than a fixed list designed for one paper.

### 2. Make the data gate diagnostic and normally non-blocking

For each semantic data requirement extracted from a paper, the data gate should report one of:

```text
exactly_available
constructible
available_with_missingness
replacement_available
missing
not_assessed
```

The assessment should record at least:

- the paper's requested semantic field or role;
- the selected physical field, if any;
- coverage and missingness;
- whether the value is exact, derived, or a replacement;
- known deviations;
- affected evaluation methods and metrics;
- whether the condition blocks execution.

Illustrative result:

```json
{
  "paper_requirement": "free_float_market_cap",
  "availability": "replacement_available",
  "selected_field": "total_market_cap",
  "replacement": true,
  "coverage_ratio": 0.998,
  "deviations": [
    "Capitalization definition differs from the paper"
  ],
  "affected_evaluations": [
    "weighted_cross_sectional_regression"
  ],
  "blocking": false
}
```

Missing or incomplete data should normally produce a limitation rather than stop the run. Blocking should be reserved for cases where no meaningful evaluation can be executed or where the requested workflow explicitly requires exact inputs.

### 3. Permit replacements but make them traceable

Replacement data is acceptable when exact data is unavailable, provided its use is explicitly recorded and reported.

Every replacement should preserve:

- the original semantic requirement;
- the paper's definition;
- the replacement field or method;
- why it was selected;
- the expected methodological effect;
- the resulting comparability level;
- whether the replacement was selected automatically or approved by the user.

Illustrative record:

```json
{
  "required_semantic_role": "regression_weight",
  "paper_definition": "sqrt_free_float_market_cap",
  "replacement_field": "sqrt_total_market_cap",
  "replacement_reason": "free-float capitalization unavailable",
  "selection_basis": "closest available capitalization measure",
  "expected_effect": "changes weighted regression coefficients and t-statistics",
  "comparability_after_replacement": "proxy",
  "selection_mode": "automatic"
}
```

Substitution should change comparability, not necessarily execution status. For example:

```text
Execution status: completed_with_limitations
Truth-validation status: proxy_comparable
```

Reports should distinguish among:

- missing data with no replacement;
- an automatically selected replacement;
- a constructed equivalent;
- a user-provided replacement;
- a candidate replacement rejected as semantically unsuitable.

### 4. Use typed field relationships

The data resolver should not silently treat semantically different fields as exact aliases. Candidate relationships should be typed as:

```text
exact_alias
derived_equivalent
proxy_substitute
unsupported_substitute
```

Example:

```json
{
  "from": "total_market_cap",
  "to": "free_float_market_cap",
  "relationship": "proxy_substitute",
  "requires_reporting": true
}
```

This preserves automation while preventing a replacement from being reported as exact paper-method compliance.

### 5. Connect data deviations to comparability and metrics

A deviation should identify which parts of evaluation it affects. For example, a missing regression weight may reduce comparability for coefficient and t-statistic metrics without invalidating a separately calculated rank IC.

The pipeline should therefore assess comparability at the evaluation-case and metric levels instead of applying one undifferentiated status to the entire reproduction.

## Deferred Data Decisions

Historical industry classification and free-float market-capitalization data are still under investigation. Project-level integration of these datasets is deferred until their sources, semantics, history, and coverage have been reviewed.

Until then:

- available industry data may be used as an explicitly reported proxy;
- available capitalization measures may be used as explicitly reported replacements;
- an unweighted or differently weighted regression may run as a diagnostic proxy;
- evaluation cases requiring unavailable exact data should be marked deferred or proxy-comparable, not silently treated as exact;
- less data-dependent truth sources may be selected as the primary available validation evidence.

This deferral must not block implementation of the generic extraction, data-assessment, replacement-tracking, and reporting improvements described above.

## Reporting Requirements

The final reproduction report should summarize:

- exact, constructed, replacement, missing, and unassessed requirements;
- coverage and missingness for each selected input;
- all substitutions and their expected effects;
- the evaluations and metrics affected by each deviation;
- the selected primary truth source and why it is best supported by available data;
- diagnostic or sensitivity results produced from alternative inputs;
- deferred exact evaluations that can be rerun when better data becomes available.

These limitations should remain visible even when the pipeline completes successfully.

## Non-Goals

This improvement does not:

- hard-code one paper's neutralization model;
- mandate a particular industry taxonomy or data vendor;
- require complete data before an automated run may proceed;
- forbid reasonable replacement data;
- resolve the pending historical-industry or free-float-data acquisition decision.

## Implementation Acceptance Criteria

The improvement is complete when:

1. Extraction can represent ordered transforms on factors, controls, weights, and labels.
2. Every extracted semantic requirement receives a structured data-gate assessment.
3. Replacement use is explicit, attributable, and included in the final report.
4. Exact aliases and proxy substitutes cannot be confused by the resolver.
5. Data limitations change comparability appropriately without unnecessarily blocking execution.
6. Deferred exact evaluations are preserved so they can be rerun when new data becomes available.
7. The behavior works through generic specifications and evaluator capabilities rather than paper-specific branches.
