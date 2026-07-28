# Paper Factor Reproduction Project

## Current Purpose

Build a skill-driven AI workflow inside `agentmatrix-research` that can read a research paper, extract the factor reproduction method, map it into Factor Lab artifacts, validate each gate, and report what has or has not been reproduced.

The project has two outputs:

- reusable Factor Lab infrastructure under `research_core/factor_lab/paper_reproduction/`
- a reusable AI skill, `paper-factor-reproduction`, that directs fresh agents to run the workflow correctly

This is not a parallel research framework. The workflow must use existing Factor Lab contracts, registries, operators, evaluation utilities, runtime paths, and report conventions whenever possible.

## Current Status

Implemented package:

```text
research_core/factor_lab/paper_reproduction/
```

Current test status:

```text
python -m unittest discover research_core/factor_lab/paper_reproduction
76 passed
```

Implemented capabilities:

- paper extraction dataclasses and validation
- evaluation-result truth-source schema
- extraction artifact export/load
- normalization into `FactorResearchSpec`
- specs/catalog export through existing Factor Lab registry
- input dataframe validation
- reusable data profiling and evaluation-case support assessment
- implementation readiness manifests
- safe unimplemented factor-family scaffolds
- support-scored paper evaluation planning with selected/resolved runtime cases
- generic evaluator support for transform specs, IC analysis, and IC regression
- protocol-aware paper-reported evaluation metric matching
- final paper reproduction report generation
- persistent pipeline-stage state tracking with separate execution and truth-validation statuses
- Quant API daily kline normalization helper
- fresh-agent harness packet generation with bundled skill copy and skill hash

Current serious benchmark:

```text
research_core/factor_lab/paper_reproduction/golden/huatai_alpha3_13_15.json
```

This golden artifact covers Huatai Alpha3, Alpha13, and Alpha15 using the current evaluation-case schema.

## Core Design Decisions

### 1. Paper Truth Means Evaluation Results

The current durable project decision is:

```text
truth_type = evaluation_results
```

For this workflow, paper truth is paper-reported evaluation evidence, such as:

- Rank IC
- IC / ICIR / IR
- long-short return or spread
- factor return
- t-statistics
- Sharpe
- portfolio return metrics
- IC decay / half-life metrics

Do not add or maintain paper-reported factor-value truth matching unless that design is explicitly reopened.

Do not use these in the current paper-truth workflow:

- `factor_values` truth sources
- point-in-time factor-value row schemas
- `paper_factor_value_match_ratio`
- `compare_factor_values_to_paper_truth`

External third-party truth data is a separate evidence type and is not the current paper-reproduction proof target.

### 2. Evaluation Cases Are First-Class

Raw factor definitions must stay minimal. Evaluation-specific details belong to each paper-reported evaluation case / truth source.

Raw factor definition:

- factor name
- formula
- formula-required fields
- parameters / windows
- frequency
- formula source notes

Evaluation case / truth source:

- `truth_id`
- `truth_type = evaluation_results`
- `evaluation_family`
- `evaluation_method`
- `evaluation_spec`
- `transform_spec`
- `required_data`
- paper-reported `metrics`
- narrow `source_location`
- sample period / universe when case-specific

Do not put preprocessing, neutralization, portfolio construction, return horizon, execution price, benchmark, or evaluation-required fields at raw-factor level when they vary by paper result.

### 3. Truth Granularity Must Be Tight

Split truth sources when any of these differ:

- table / figure / appendix source
- metric family
- return horizon
- preprocessing or neutralization
- regression controls or weights
- sample window
- portfolio construction
- transaction cost
- execution price
- benchmark

Do not merge IC/regression metrics, IC decay metrics, and portfolio TOP-layer metrics into one broad truth source.

### 4. Known Limitations Are Not Automatically Blockers

Missing daily factor values, per-date IC series, or machine-readable portfolio curves is usually a known limitation, not a blocker, when aggregate paper evaluation metrics and methods are available.

Use `needs_human_review` only when automation cannot safely resolve ambiguity that changes the factor definition or the meaning of the selected truth.

Use `blocked_by_data` when formula-required data is unavailable after checking the available data path, including `/Users/mac/recommended_data_v2` first and Quant API v2 only as a fallback when applicable.

Evaluation-data limitations should normally produce a resolved case with deviations, a proxy/reduced-period evaluation, a deferred unsupported case, or `not_evaluated` truth status. They should not block factor implementation.

### 5. Stage 4 Starts With Readiness, Not Code

For arbitrary papers, do not jump straight to factor implementation.

Stage 4A produces an implementation manifest and safe scaffold:

- per-factor status
- blocked reasons
- suggested function name
- known operator hints
- AI-designed helper candidates
- required implementation tests
- importable factor-family scaffold that raises `NotImplementedError`

Stage 4B may implement paper-specific factor logic only after extraction, normalization, and data-validation gates are clear.

### 6. Generic Evaluators Stay Limited

The project should not become a universal paper evaluator or formula compiler.

Currently supported generic evaluator pieces:

- ordered transform specs
- median-MAD winsorization
- cross-sectional regression residual neutralization
- cross-sectional z-score standardization
- Rank/Pearson IC analysis
- cross-sectional OLS/WLS regression summaries
- `ic_analysis`
- `ic_regression`

Unsupported families should stop cleanly or use paper-local evaluator code:

- `layered_portfolio_backtest`
- `ic_decay`
- custom paper-specific methods

## Current Workflow

### Stage 1: Paper Extraction

Module:

```text
research_core/factor_lab/paper_reproduction/extraction.py
```

Main types:

- `PaperExtraction`
- `ExtractedFactor`
- `ExtractedTruthSource`
- `ExtractionValidationResult`

Expected artifact:

```text
runtime/factor_lab/paper_specs/<paper_id>_extracted.json
```

Extraction should preserve:

- paper id, title, authors, source, year
- factor family name
- explicit selected factor scope
- raw formulas
- formula-required fields
- factor frequency
- factor parameters
- factor sample period / universe when applicable
- paper-reported evaluation cases
- selected truth source ids or truth selection rule
- classified ambiguity notes
- known limitations

Validation checks:

- paper id, title, authors, and family name exist
- every target factor has name, formula, required fields
- frequency exists or its absence is explicitly recorded
- every truth source is `evaluation_results`
- every truth source has non-empty metrics
- evaluation method exists
- selected truth ids exist and are not duplicated
- duplicate truth ids fail
- multiple truth sources without a selection rule or selected ids require human review
- broad or missing source locations require human review
- unrecognized metric names require human review
- ambiguities are classified as formula, field mapping, evaluation, or other

### Stage 2: Spec Normalization

Module:

```text
research_core/factor_lab/paper_reproduction/normalization.py
```

Relevant contract:

```text
contracts/factor_research.py
```

Expected artifacts:

```text
runtime/factor_lab/specs/<family>_specs.json
runtime/factor_lab/catalogs/<family>_catalog.json
research_core/factor_lab/libraries/<family>/specs.py
```

Normalization is a preservation step. It should not invent missing assumptions or overclaim proof.

Validation targets:

- `formula_match_ratio >= 1.0`
- `field_mapping_match_ratio >= 1.0`
- `paper_evaluation_metric_match_ratio >= 1.0` when selected evaluation truth exists

Preserve in spec metadata:

- paper provenance
- extraction validation status and warnings
- all truth sources
- selected truth sources
- truth source summary
- evaluation cases
- known limitations
- classified ambiguities
- truth selection rule
- proof status ceiling
- implementation stage

If extraction needs human review, spec metadata should also indicate `needs_human_review`.

### Stage 3: Input DataFrame Validation

Module:

```text
research_core/factor_lab/paper_reproduction/data_validation.py
```

Main API:

```python
DataFrameValidationRequest.from_factor(factor)
validate_input_frame(panel, request)
```

Formula-stage validation checks:

- `date` exists and parses
- `code` exists
- formula-required fields exist
- no duplicate `date` x `code` rows
- frame is sorted by `code,date`, or the status records review
- enough per-code history exists for window parameters

Keep formula-required fields separate from evaluation-required fields.

Example: for Huatai Alpha3/13/15, VWAP is not a formula field. It is an evaluation/backtest execution requirement.

### Stage 4A: Implementation Readiness Manifest and Scaffold

Module:

```text
research_core/factor_lab/paper_reproduction/implementation.py
```

Main API:

```python
build_implementation_manifest(...)
export_implementation_manifest(...)
write_factor_family_scaffold(...)
```

Expected artifact:

```text
runtime/factor_lab/implementation_plans/<family>_implementation_manifest.json
```

Expected scaffold:

```text
research_core/factor_lab/libraries/<family>/
  __init__.py
  factors.py
  test_factors.py
```

The generated scaffold should be importable but intentionally unimplemented until reviewed.

Per-factor statuses:

- `ready_for_code`
- `ready_for_code_with_limitations`
- `needs_human_review`
- `blocked_by_data`

Unknown formula identifiers should be recorded as AI-designed helper candidates, not silently promoted into shared Factor Lab operators.

### Stage 4B: Paper-Specific Factor Implementation

This stage is not generic code generation. It is paper-specific engineering guided by the extraction/spec/manifest.

Implementation rules:

- keep data loading outside factor functions
- accept normalized panels
- return `date`, `code`, and requested factor columns
- preserve row count unless the paper explicitly filters rows
- replace infinities with nulls
- keep paper-specific helpers local until reused across papers
- add tests before marking a factor usable

For WorldQuant/Huatai-style formulas that mix cross-sectional rank and rolling operations, wide-format implementation may be appropriate:

```text
long panel
-> cross-sectional rank by date
-> pivot to date x code
-> rolling corr/cov/sum by code
-> cross-sectional transform by date
-> unstack back to long panel
```

### Stage 5: Implementation Tests

Tests should cover:

- importability
- requested factor dispatch
- required input columns
- output shape
- row-count preservation
- numeric-or-null factor columns
- no infinite outputs
- hand-computable toy panels for formula semantics
- transform order when applicable
- evaluation alignment when applicable

Current package tests live beside the implementation:

```text
research_core/factor_lab/paper_reproduction/test_*.py
```

### Stage 6: Paper-Aware Evaluation Planning and Execution

Planning module:

```text
research_core/factor_lab/paper_reproduction/paper_evaluation.py
```

Generic evaluator module:

```text
research_core/factor_lab/paper_reproduction/evaluators.py
```

Main APIs:

```python
build_paper_evaluation_plan(specs, data_profiles={...})
apply_transform_spec(...)
compute_ic_analysis(...)
compute_cross_sectional_regression(...)
evaluate_paper_case(...)
```

Before selecting truth, profile the available data and assess every candidate evaluation case. The extracted truth source represents what the paper did and must not be mutated during execution. The planner creates a separate resolved runtime case containing:

- `source_truth_id`
- `paper_protocol`
- `resolved_protocol`
- `support_assessment`
- `deviations`
- `comparability`
- `truth_match_eligible_metrics`
- `diagnostic_only_metrics`
- `lifecycle_state`

Evaluation execution must consume `selected_evaluation_cases`, not loop over every extracted truth source. Unsupported, budget-deferred, or insufficient-data cases remain visible in reports but do not enter metric truth matching.

Evaluation must follow the selected resolved case. Before computing metrics, apply the evaluation-case `transform_spec` in order.

Do not assume:

- all papers use daily frequency
- `t+1` means one trading day
- all IC is Rank IC
- all factors use the same neutralization
- all portfolio tests use the same execution price

Forward returns must look forward:

```python
future_price = panel.groupby("code")["close"].shift(-periods)
forward_return = future_price / panel["close"] - 1
```

Using `shift(+periods)` computes past returns and corrupts IC results.

### Stage 7: Paper Truth Matching

Module:

```text
research_core/factor_lab/paper_reproduction/truth_matching.py
```

Main API:

```python
compare_evaluation_metrics_to_paper_truth(...)
interpret_truth_match_quality(...)
```

Truth matching compares computed evaluation metrics to paper-reported evaluation metrics.

Statuses:

- `exact_match`
- `approximately_consistent`
- `directionally_consistent`
- `inconclusive_due_to_protocol_gap`
- `inconsistent`
- `not_evaluated`

Use exact matching as a strong signal, but do not require perfect equality for useful implementation confidence. Data vendor, sample period, adjustment, universe, and rounding differences may make approximate consistency the correct outcome.

Only `inconsistent` is direct negative truth evidence. Unsupported, skipped, deferred, insufficient-data, and protocol-gap cases are coverage/comparability outcomes and must not be counted as failed metric comparisons.

### Stage 8: Final Report

Module:

```text
research_core/factor_lab/paper_reproduction/reporting.py
```

Expected artifacts:

```text
runtime/factor_lab/reports/<job_id>_paper_reproduction_report.json
runtime/factor_lab/reports/<job_id>_paper_reproduction_report.md
```

Report contents:

- job id
- paper metadata
- whether factor implementation was produced
- selected paper truth and selection reason
- exact/comparable/proxy/directional comparability
- truth-validation result
- most important limitations
- factor definitions
- formulas and required fields
- evaluation truth sources
- assessed, selected, deferred, and unsupported evaluation cases
- extracted versus resolved protocol information
- data coverage and evaluator support summaries when supplied
- structured deviations and affected metrics
- truth match results
- correct truth-match denominators
- pipeline stage state
- artifacts
- tests run
- known gaps
- no-overclaiming note

Never claim:

- fully reproduced
- zero bias
- passed proof

unless the relevant paper-truth comparison has actually run and passed under the agreed policy.

## Pipeline State

Module:

```text
research_core/factor_lab/paper_reproduction/pipeline.py
```

Expected artifact:

```text
runtime/factor_lab/paper_jobs/<job_id>.json
```

Stages:

```text
paper_extraction
spec_normalization
input_dataframe_validation
factor_implementation
implementation_tests
evaluation
paper_truth_validation
final_report
```

Execution statuses:

- `pending`
- `running`
- `completed`
- `completed_with_limitations`
- `failed`

Truth-validation statuses:

- `exact_match`
- `approximately_consistent`
- `directionally_consistent`
- `inconclusive_due_to_protocol_gap`
- `inconsistent`
- `not_evaluated`

Legacy stage `status` remains serialized for compatibility. New code should use `execution_status`, `truth_validation_status`, and `execution_decision(stage_name)`.

Soft limitations do not block later stages. Hard failures block only dependent work; factor-local failures should not unnecessarily block unrelated factors.

## Skill and Fresh-Agent Testing

Skill path used during current development:

```text
/Users/mac/.hermes/skills/research/paper-factor-reproduction/SKILL.md
```

The skill is a primary project output. Testing the project means testing whether a fresh AI agent can follow this skill and reproduce the methodology extraction.

Harness module:

```text
research_core/factor_lab/paper_reproduction/agent_harness.py
```

Main API:

```python
prepare_agent_harness_bundle(...)
```

Harness output:

```text
runtime/factor_lab/agent_harness/<harness_id>/
  fresh_agent_prompt.md
  harness_metadata.json
  skills/paper-factor-reproduction/SKILL.md
```

The harness copies the exact skill into the test packet and records its SHA-256 hash. This makes each fresh-agent test auditable.

Fresh-agent test goal:

```text
Can a new AI agent, given the repo and bundled skill, extract and operationalize
the paper reproduction method correctly?
```

The first comparison target is the golden JSON, not final numeric paper reproduction.

Current missing automation:

```text
fresh agent artifacts -> golden JSON comparison report
```

At present, comparison against golden JSON is still mostly manual/semantic.

## Golden JSON Artifacts

Golden JSON is a manually curated benchmark for whether an AI agent extracted the reproduction method correctly.

It is not proof that computed factor values or evaluation metrics match the paper.

Current schema version:

```text
paper_reproduction_golden_v0.2
```

Current benchmark:

```text
research_core/factor_lab/paper_reproduction/golden/huatai_alpha3_13_15.json
```

Golden artifacts should capture:

- selected factor scope
- formula definitions
- formula-required fields
- parameters
- frequency
- transform definitions
- evaluation method definitions
- per-factor evaluation cases
- required data by stage
- paper metrics
- source locations
- known limitations
- comparison policy

## Representative Papers

### Huatai Technical Factors

Paper:

```text
Huatai Securities, 2019-05-21, mass technical factors
```

Current selected benchmark:

```text
Alpha3, Alpha13, Alpha15
```

Canonical formulas:

```text
Alpha3  = (-1 * correlation(rank(OPEN), rank(VOLUME), 10))
Alpha13 = (-1 * rank(covariance(rank(CLOSE), rank(VOLUME), 5)))
Alpha15 = (-1 * sum(rank(correlation(rank(HIGH), rank(VOLUME), 3)), 3))
```

Important paper method:

- all A-shares
- exclude ST/PT and next-day suspended stocks
- sample period `2010/1/4-2019/4/30`
- daily frequency
- T=5/10/20 forward returns
- selected truth generally uses T=20
- median-MAD winsorization
- neutralization variant
- z-score standardization
- no missing-value fill
- portfolio tests use 20 equal-count layers and default one-way fee 0.15%

Important extraction pitfalls:

- VWAP is evaluation/backtest data, not a formula field for Alpha3/13/15
- Table 52, Table 14, and portfolio tables are separate evaluation cases
- missing daily factor values are known limitations, not blockers
- Quant API v2 does not cover the original 2010-2019 sample

### GTJA191

Paper:

```text
Guotai Junan 191 short-cycle price-volume factors
```

Use case:

- large-scale formula extraction from PDF text
- state-machine parsing of formulas
- required-field extraction with derived-indicator fallback
- aggregate-only evaluation truth

Important distinction:

The paper does not provide per-factor evaluation tables. Aggregate evaluation metrics can be attached, but factors may remain `needs_human_review` because per-factor paper truth is unavailable.

## Recommended Local Data Notes

Use `/Users/mac/recommended_data_v2` before Quant API v2 when real data is needed.

Curated files:

```text
kline_daily_adjusted.parquet      daily OHLCV, amount, adjustment factors, adjusted OHLC
security_status_through_2026-04-09.parquet
                                  trading/ST/suspension/limit status
st_status_2010_2016.parquet       ST-only status, 2010-01-04 to 2016-12-30
st_status_full.parquet            ST-only status, 2017-01-03 to 2026-07-22
market_cap_2010_2026.parquet      daily market capitalization, 2010-01-04 to 2026-07-22
trading_calendar.parquet          trading calendar
security_master.parquet           security master
income_statement.parquet          point-in-time income values
balance_sheet.parquet      point-in-time balance-sheet values
dividend_yield.parquet     daily dividend yield
industry_map.parquet       current industry mapping snapshot
```

Daily panel helper:

```python
from research_core.factor_lab.paper_reproduction.recommended_data import (
    apply_a_share_recommended_filters,
    load_recommended_daily_panel,
)

panel = load_recommended_daily_panel(
    start_date="2020-01-02",
    end_date="2026-07-22",
    adjusted=True,
    include_status=True,
    include_market_cap=True,
    include_industry=True,
)
panel = apply_a_share_recommended_filters(panel)
```

Coverage notes:

- `kline_daily_adjusted.parquet` and `trading_calendar.parquet` cover roughly 2010-01-04 to 2026-07-22.
- `security_status_through_2026-04-09.parquet` covers trading/suspension/limit status through 2026-04-09.
- `st_status_2010_2016.parquet` and `st_status_full.parquet` provide ST-only coverage from 2010-01-04 to 2026-07-22. They do not contain suspension/trading fields.
- `market_cap_2010_2026.parquet` is the preferred market-cap file and covers 2010-01-04 to 2026-07-22. The loader falls back to legacy `market_cap.parquet` only when the expanded file is absent.
- For all-A-share filters outside full status coverage, ST filtering can still run from the ST-only files, but next-day suspension filtering is unavailable and must be reported as a universe-filter limitation.
- `income_statement.parquet`, `balance_sheet.parquet`, and `dividend_yield.parquet` include data back to 2010.

## Quant API v2 Data Notes

Quant API v2 is now a fallback when no explicit artifact or `/Users/mac/recommended_data_v2` file can satisfy the required fields/date window.

Base URL:

```text
http://115.159.73.134:8765
```

Security rule:

- do not commit tokens
- do not write tokens into source, docs, runtime artifacts, reports, generated specs, or logs
- prefer `QUANT_API_TOKEN`

Useful table:

```text
ods_kline_1d
```

Relevant columns:

```text
symbol, trade_date, open, high, low, close, volume, amount
```

Normalized panel:

```text
date, code, open, high, low, close, volume, amount
```

Known limits:

- `ods_kline_1d` coverage starts around 2020
- Huatai's 2010-2019 full sample cannot be fully reproduced from this API instance; check recommended local financial/dividend files before declaring a data blocker for non-kline fields
- recent windows can validate implementation/data flow but not full sample reproduction

Date encoding pitfall:

```python
pd.to_datetime(raw["trade_date"].astype(int), unit="D", origin="1970-01-01")
```

Do not parse Quant API parquet `trade_date` with plain `pd.to_datetime(raw["trade_date"])`; it can produce 1970 dates.

## Current Known Gaps

High-priority gaps:

- automated golden JSON comparator for fresh-agent outputs
- clearer command/script for creating harness packets from CLI
- documentation cleanup across the remaining `docs/PAPER_FACTOR_REPRODUCTION_*.md` files
- richer current-state examples for Huatai and GTJA191

Evaluation gaps:

- generic `layered_portfolio_backtest`
- generic `ic_decay`
- exact paper-specific portfolio execution support
- neutralization details requiring industry and market-cap data

Data gaps:

- pre-2020 A-share history for papers like Huatai
- industry classification panel
- market-cap / free-float market-cap panel
- ST/PT and suspension filters
- benchmark return series for paper portfolio metrics

Implementation gaps:

- reviewed Stage 4B factor-library implementations are paper-specific and not yet the generic project core
- unknown formula functions should remain local helper candidates until repeated need justifies shared operators

## Near-Term Direction

The next project step should be testing and hardening the fresh-agent loop:

1. Generate a harness packet with the bundled skill.
2. Run a fresh AI agent in an isolated worktree.
3. Collect extraction/spec/report artifacts.
4. Compare those artifacts to golden JSON.
5. Classify failures as skill, schema, validation, normalization, data, evaluator, or reporting gaps.
6. Update the general workflow, not paper-specific hacks.
7. Retest the same paper.
8. Test a different paper to reduce overfitting.

The most important missing tool is an automated or semi-automated golden comparator. It should report strict mismatches for formulas, fields, metrics, and source locations, and semantic review items for universe, sample period, transform specs, evaluation specs, and known limitations.
