# Golden JSON Building Context for Paper Factor Reproduction

This note is a handoff for future sessions that build manually curated golden JSON artifacts for paper-factor-reproduction tests.

## Purpose

The golden JSON is **not** a proof that our implementation reproduces paper results. It is a manually curated benchmark for whether an AI agent correctly extracted the paper's reproduction method.

For each selected paper/factor set, the golden JSON should capture the expected:

1. formulas,
2. formula-required data fields,
3. preprocessing rules,
4. neutralization rules,
5. evaluation methods,
6. evaluation-required data fields,
7. paper-reported evaluation truth metrics,
8. source locations,
9. known limitations.

Use the golden JSON to compare a fresh agent's extraction/spec artifacts against the expected reproduction method.

## Current project decisions

- Paper truth matching is evaluation-results-only.
- Do not use paper-reported factor-value truth matching unless this design is explicitly reopened.
- Missing daily factor values or per-date IC series is usually a known limitation, not an extraction blocker, when aggregate evaluation metrics are reported.
- Formula-required fields must be separated from preprocessing, neutralization, and evaluation-required fields.
- Truth sources should be split by metric group/evaluation setting/table. Do not combine unrelated metrics from multiple tables into one truth source.
- `source_location` should be narrow and auditable.
- Fields like VWAP may be evaluation/backtest execution requirements rather than formula inputs.

## Reference implementation files

- `research_core/factor_lab/paper_reproduction/extraction.py`
- `research_core/factor_lab/paper_reproduction/normalization.py`
- `research_core/factor_lab/paper_reproduction/implementation.py`
- `research_core/factor_lab/paper_reproduction/paper_evaluation.py`
- `research_core/factor_lab/paper_reproduction/truth_matching.py`
- `research_core/factor_lab/paper_reproduction/reporting.py`

## Existing golden artifact

The first manually curated golden JSON is:

```text
research_core/factor_lab/paper_reproduction/golden/huatai_alpha3_13_15.json
```

It covers the Huatai paper:

```text
华泰单因子测试之海量技术因子
2019-05-21
Selected factors: Alpha3, Alpha13, Alpha15
```

## Recommended golden JSON construction workflow

1. Read the paper directly.
2. Select a small factor scope.
3. Extract formula evidence and source locations.
4. Extract common variable/operator definitions.
5. Extract universe/sample/frequency.
6. Extract preprocessing rules.
7. Extract neutralization rules.
8. Extract evaluation method and return horizon.
9. Extract paper-reported evaluation metrics.
10. Split truth sources by source table and evaluation setting.
11. Record known limitations separately from blocking ambiguities.
12. Validate JSON syntax.
13. Ask the user to review the golden file before treating it as stable.

## Golden JSON comparison dimensions

Strict comparison fields:

- selected factors,
- factor names,
- formulas,
- formula-required fields,
- parameters/windows,
- frequency,
- paper metric values,
- source locations for metrics.

Semantic comparison fields:

- universe,
- sample period,
- preprocessing rules,
- neutralization rules,
- evaluation method,
- portfolio construction,
- known limitations.

## Huatai-specific lessons

From the Huatai Alpha3/13/15 review:

- Missing daily factor values/per-date IC should be a known limitation, not a blocker.
- Table 52 IC/regression metrics, Table 14 half-life metrics, and factor-specific top-layer portfolio metrics should be separate truth sources.
- Table 9 can be selection evidence but should not be cited as the source for metrics copied from other tables.
- VWAP is not a formula input for Alpha3/13/15; it is an evaluation/backtest execution requirement.
- Formula-required fields should remain formula-only: Alpha3 uses open+volume, Alpha13 uses close+volume, Alpha15 uses high+volume.
