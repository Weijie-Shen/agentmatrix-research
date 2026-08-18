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
python -m pytest research_core/factor_lab/paper_reproduction -q
See the latest validation run; do not copy a stale fixed count into workflow decisions.
```

Implemented capabilities:

- paper extraction dataclasses and validation
- truth-source-recipe `paper_extraction.ic_recipe.v3` schema, with v2 and legacy-load compatibility
- extraction artifact export/load
- normalization into `FactorResearchSpec`
- specs/catalog export through existing Factor Lab registry
- input dataframe validation
- reusable data profiling and evaluation-case support assessment
- typed semantic field relationships and reportable replacement-data provenance
- implementation readiness manifests
- safe unimplemented factor-family scaffolds
- probe-validated canonical `FactorImplementationArtifact` records with source/spec hashes
- keyed `FactorFrame` validation and one-to-one alignment diagnostics
- support-scored paper evaluation planning with selected/resolved runtime cases
- canonical selected-case execution with separate calculation and evaluation panels
- configurable resource preflight with methodology-preserving projected execution
- incremental data hashing, narrow evaluator boundaries, and compact alignment fast paths
- generic evaluator support for ordered factor/control transforms, neutralization, and IC analysis
- stage-aware calculation/evaluation universe protocols and post-calculation filters
- protocol-aware paper-reported evaluation metric matching
- final paper reproduction report generation
- persistent pipeline-stage state tracking with separate execution and truth-validation statuses
- Quant API daily kline normalization helper
- fresh-agent harness packet generation with bundled skill copy and skill hash

Current serious benchmark:

```text
research_core/factor_lab/paper_reproduction/golden/huatai_alpha3_13_15.json
```

This legacy golden artifact covers Huatai Alpha3, Alpha13, and Alpha15. New extraction artifacts use the IC-analysis v2 schema; legacy artifacts remain loadable for regression compatibility.

## Core Design Decisions

### 1. Paper Truth Means Evaluation Results

The current durable project decision is:

```text
paper_evidence_kind = evaluation_results
evaluator_type = ic_analysis
```

Legacy artifacts express the first line as `truth_type = evaluation_results`; v2 expresses it through the IC truth-source registry and contract.

For new jobs, paper truth is paper-reported IC-analysis evidence, such as:

- Rank IC
- IC / ICIR / IR
- Rank-IC mean
- IC standard deviation
- ICIR
- positive-IC ratio

Do not add or maintain paper-reported factor-value truth matching unless that design is explicitly reopened.

Do not use these in the current paper-truth workflow:

- `factor_values` truth sources
- point-in-time factor-value row schemas
- `paper_factor_value_match_ratio`
- `compare_factor_values_to_paper_truth`

External third-party truth data is a separate evidence type and is not the current paper-reproduction proof target.

### 2. Truth-Source-Owned IC Recipes Are First-Class

New artifacts use `schema_version = paper_extraction.ic_recipe.v3`. Raw factor definitions stay minimal. Each homogeneous truth source owns one declarative evaluation recipe and stores factor-keyed paper results. A single source/table block may cover many factors.

Raw factor definition:

- factor name
- formula
- formula-required fields
- parameters / windows
- frequency
- formula source notes

IC truth source:

- `truth_source_id`
- exactly one `evaluation_recipe`
- one narrow table/figure/row-block source
- all `reported_metric_ids` printed together in that block
- factor-keyed `reported_results`
- every covered factor row and optional notes/gaps

Do not put preprocessing, neutralization, portfolio construction, return horizon, execution price, benchmark, or evaluation-required fields at raw-factor level when they vary by paper result.

Stage 1 contains no local physical-field bindings. It selects exactly one truth source per factor in `factor_truth_selection`. Stage 3 owns local semantic and value-state resolution; Stage 6 executes without reselection.

### 3. Truth Granularity Must Be Tight

Split truth sources when the IC protocol differs in any of these ways:

- table / figure / appendix source
- return horizon
- preprocessing or neutralization
- regression controls or weights
- sample window
- return alignment or status-filter timing

Do not split Rank-IC mean, IC standard deviation, ICIR, or positive-ratio metrics when they appear together under the same recipe. They are metrics of one `ic_analysis` evaluator type. Split a table's row blocks when their preprocessing or neutralization recipes differ.

### 4. Known Limitations Are Not Automatically Blockers

Missing daily factor values, per-date IC series, or machine-readable portfolio curves is usually a known limitation, not a blocker, when aggregate paper evaluation metrics and methods are available.

Use `needs_human_review` only when automation cannot safely resolve ambiguity that changes the factor definition or the meaning of the selected truth.

Use `blocked_by_data` when formula-required data is unavailable after checking the available data path, including `/Users/mac/recommended_data_v2` first and Quant API v2 only as a fallback when applicable.

Evaluation-data limitations should normally produce a resolved case with deviations, a proxy/reduced-period evaluation, a deferred unsupported case, or `not_evaluated` truth status. They should not block factor implementation.

### 5. Stage 4 Starts With Readiness and Ends With a Canonical Artifact

For arbitrary papers, do not jump straight to factor implementation.

Stage 4A produces an implementation manifest and safe scaffold:

- per-factor status
- blocked reasons
- suggested function name
- known operator hints
- AI-designed helper candidates
- required implementation tests
- importable factor-family scaffold that raises `NotImplementedError`

Stage 4B may implement paper-specific factor logic only after extraction, normalization, and data-validation gates are clear. Implementation is complete only when the final module/callable is probe-validated and recorded as a `FactorImplementationArtifact`; an importable scaffold or an inline factor column is not the deliverable.

### 6. Generic Evaluators Stay Limited

The project should not become a universal paper evaluator or formula compiler.

The canonical v2 evaluator family is deliberately limited to:

- ordered transform specs
- median-MAD winsorization
- cross-sectional regression residual neutralization
- cross-sectional z-score standardization
- Rank/Pearson IC analysis
- `ic_analysis`

The legacy runtime still loads older regression/portfolio cases, but new v2 extraction does not create them. Unsupported paper evidence remains outside the selected IC truth workflow:

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

- `ICAnalysisPaperExtraction`
- `ExtractedFactorDefinition`
- `ExtractedSemanticRequirement`
- `ExtractedUniverseProtocol`
- `ExtractedOperationPipeline`
- `ExtractedICProtocol`
- `ExtractedMetricDefinition`
- `ExtractedICTruthSource`
- legacy `PaperExtraction` types for loading old jobs
- `ExtractionValidationResult`

Expected artifact:

```text
runtime/factor_lab/paper_specs/<paper_id>_extracted.json
```

Extraction should preserve shared registries for:

- paper id, title, authors, source, year
- factor family name
- explicit selected factor scope
- raw formulas
- formula-required fields
- factor frequency
- factor parameters
- typed paper semantics, including industry source/version/level and capitalization basis
- truth-source-owned sampling, ordered preprocessing, return-label, IC, and metric methods
- all selected paper-reported IC result blocks and every metric co-reported in each block
- exactly one Stage-1 truth-source selection per factor
- mandatory `china_a_share_ic_evaluation_v1` global-policy reference
- classified ambiguity notes
- known limitations

Validation checks:

- paper id, title, authors, and family name exist
- every target factor has ID, formula, and referenced semantic fields
- frequency exists or its absence is explicitly recorded
- every ID is unique and every reference resolves
- the only evaluator type is `ic_analysis`
- every truth source has one homogeneous recipe, covered-factor IDs match result rows, and metric IDs match each row
- duplicate truth IDs fail
- local data-binding keys fail
- unknown method IDs, non-contiguous step order, and invalid factor/source selections fail
- unresolved contradictory paper blocks are explicit conflict groups and require review
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
- paper-evaluation matching remains inactive until Stage 3 resolves and Stage 6 executes the selected source

Preserve in spec metadata:

- paper provenance
- extraction validation status and warnings
- the one Stage-1 selected truth source and immutable recipe
- truth source summary
- evaluation cases
- known limitations
- classified ambiguities
- Stage-3 recipe/value-state resolution and Stage-6 execution policy
- factor semantic-field IDs and evaluation-case refs
- preserved ordered recipe, without added transform defaults
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

For v3, assess the selected truth source against typed semantic requirements and operation capabilities. SWS and CITIC industry definitions, their levels/timing, and total/A-share/circulating/free-float capitalization bases are distinct relationships. Bind semantic concept plus unit, price basis, value space, transform chain, and temporal semantics. Mark requested transforms `apply`, `reuse_materialized`, `blocked_unknown_state`, or `incompatible`; never double-transform a materialized field.

Evaluation-data resolution must distinguish `exact_alias`, `derived_equivalent`,
`proxy_substitute`, and `unsupported_substitute`. A proxy may keep an evaluation
case executable, but it must downgrade comparability and create a metric-scoped
deviation/replacement record. A declared derivation is only executable after its
output column is materialized. Unsupported substitutes are reported and never
written into the resolved runtime protocol. These evaluation limitations do not
block factor implementation or unrelated truth cases.

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

After the paper-family implementation passes its direct tests, create and validate
a canonical `FactorImplementationArtifact`. It records the module/callable,
implemented factor IDs, declared inputs/outputs, source hash, implementation-relevant
spec hash, and probe evidence. Downstream canonical evaluation must call this
artifact; it must not substitute an unrelated prepared factor column.

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
apply_neutralization_spec(...)
apply_evaluation_recipe(...)
apply_global_evaluation_policy(...)
compute_ic_analysis(...)
compute_cross_sectional_regression(...)
execute_evaluation_plan(plan, implementation_artifact, data_context)
ResourceExecutionConfig(memory_budget_bytes=...)
```

`evaluate_paper_case(...)` remains a backward-compatible low-level evaluator. It
does not establish implementation identity and must not be used as canonical
reproduction evidence by itself.

Before execution, profile the available data and assess the Stage-1 selected evaluation case. The extracted source and recipe represent what the paper did and must not be mutated. The planner carries that source forward and creates a separate resolved runtime case containing:

- `source_truth_id`
- `paper_protocol`
- `resolved_protocol`
- `support_assessment`
- `deviations`
- `comparability`
- `truth_match_eligible_metrics`
- `diagnostic_only_metrics`
- `lifecycle_state`

Every semantic requirement also carries legacy availability plus canonical
availability (`exactly_available`, `constructible`,
`available_with_missingness`, `replacement_available`, `missing`, or
`not_assessed`), coverage, relationship type, execution readiness, and
pipeline-blocking scope. Repeated declarations of the same semantic requirement
are reconciled before support scoring so schema repetition cannot inflate or
penalize a case.

Evaluation execution consumes the single `selected_evaluation_case`. Unsupported, budget-deferred, or insufficient-data outcomes remain visible and do not enter metric truth matching; they never trigger source reselection.

Evaluation must follow the selected resolved case. After alignment, apply the mandatory global ST/PT and next-exchange-day-suspension policy, then apply the truth-source recipe in order,
including declared transformations of continuous/categorical controls. Capability
checks and replacement provenance decide whether each transform/control is
executable; skipped controls remain non-blocking limitations and must be reported.

Canonical execution computes factors from the complete `calculation_panel`, aligns
the artifact output to `evaluation_inputs` by unique date/security keys, and only
then applies the declared evaluation-universe filters. ST/PT, suspension, and future
tradability filters therefore do not delete rolling history unless the paper
explicitly assigns them to a calculation stage. Duplicate/ambiguous keys block the
affected execution; ordinary unmatched keys are reported limitations.

Do not assume:

- all papers use daily frequency
- `t+1` means one trading day
- all factors use the same neutralization

The v2 generic contract defines the IC correlation kind explicitly. Its timing comes from the signal date, extracted filter dates, exchange-calendar `T+h` target, and paper return interval; it is not hardcoded to entry at `t+1`.

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
- selected truth id, source location, paper method, sample period, universe, and paper-reported metrics
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
- direct paper-versus-calculated metric rows by factor and execution scenario
- signed error, absolute error, signed percentage error, absolute percentage error, and sign agreement
- primary IC and all-metric summaries including median absolute percentage error, mean absolute percentage error, MAE, RMSE, maximum percentage error, sign agreement, and paper/calculated correlation
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

Repository-scoped Codex coordinator skill:

```text
.agents/skills/paper-factor-reproduction/SKILL.md
```

Stage-specific Codex skills live beside it under `.agents/skills/`. The coordinator routes extraction, data readiness, implementation, evaluation, and review work to those smaller skills. Testing the project means testing whether a fresh Codex agent can follow the exact repository skill bundle and complete the gated workflow.

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

Canonical daily-panel files:

```text
kline_raw_rqdata.parquet          raw RQData OHLCV/amount, factors, ST/suspension status, price-observation flags
market_cap_history_rqdata.parquet PIT total, A-share, circulating-A, and derived free-float capitalization
financial_statements_pit_rqdata.parquet versioned PIT balance-sheet, income, and cash-flow fields
valuation_factors_rqdata.parquet  daily valuation ratios and decimal/raw dividend yields
dividend_events_rqdata.parquet    declaration/ex/pay-date dividend events
dividend_amount_history_rqdata.parquet information-date dividend history
trading_calendar.parquet          China exchange trading calendar
standard_index_daily_levels.parquet provider-unadjusted benchmark levels
index_components_rqdata/          annual point-in-time constituent partitions
index_weights_monthly_rqdata/     annual monthly index-weight partitions
index_weights_daily_rqdata/       annual daily index-weight partitions
china_government_yield_curve.parquet decimal annual government yields by tenor
security_master.parquet           security master
industry_membership_history_rqdata.parquet interval memberships by taxonomy source and level
industry_taxonomy_history_rqdata.parquet   historical taxonomy names and parent codes
```

Daily panel helper:

```python
from research_core.factor_lab.paper_reproduction.recommended_data import (
    IndustryClassificationSelection,
    load_recommended_daily_panel,
)

for price_view in ("qfq", "hfq"):
    calculation_panel = load_recommended_daily_panel(
        start_date=paper_data_start,
        end_date=paper_test_end,
        price_view=price_view,
        adjustment_end_date=paper_test_end if price_view == "qfq" else None,
        include_status=True,
        market_cap_fields=("market_cap", "free_float_market_cap"),
        industry_classification=IndustryClassificationSelection(paper_industry_source, paper_industry_level),
    )
    # Execute, persist the narrow FactorFrame/evaluation bundle, then release this
    # panel before loading the next price scenario.
```

Keep each active calculation panel intact. Supply status/return/control columns through
`EvaluationDataContext.evaluation_inputs` and let the resolved
`universe_protocol` apply eligibility filters after factor calculation.
`load_recommended_paper_panels(...)` remains a convenience API for manageable
diagnostics, but it keeps both views resident and is not the full-period default.
`apply_a_share_recommended_filters(...)` is retained only as a compatibility helper
for building a post-calculation evaluation panel; never feed its output into a
rolling factor callable.

Coverage notes:

- `kline_raw_rqdata.parquet` is the primary panel and covers 2000-01-04 to 2026-08-06. Its OHLC/limits/`prev_close` are unadjusted RQData values requested with `adjust_type="none"`.
- The same file contains complete listed-calendar ST and suspension status. Status-only rows retain null market fields and must not be forward-filled.
- Every reproduction runs two independent views: testing-end-anchored QFQ (`raw * F[t] / F[test_end]`) and initial-baseline HFQ (`raw * F[t]`). The paper test end is configuration, not a fixed date.
- Apply the same view multiplier to OHLC and `amount / volume` VWAP; leave volume and amount unchanged. Never mix QFQ and HFQ fields in one run.
- `market_cap_history_rqdata.parquet` covers 2000-01-04 to 2026-08-10. Select total, A-share, circulating-A, or free-float capitalization from paper wording; do not treat them as aliases or apply QFQ/HFQ multipliers.
- Industry history is interval-based. Select the paper taxonomy source and level explicitly, then resolve `start_date <= evaluation_or_formation_date < cancel_date`. The supported sources are `sws`, `citics`, `citics_2019`, and `gildata`; `sws` is not SWS 2021.
- Financial-statement selection is point-in-time: apply `ann_date <= T` before selecting a version of `(symbol, report_period)`. Record whether the run uses `latest_available`, `original_only`, or all versions. Q2/Q3/Q4 income and cash-flow fields may be year-to-date and must not be treated as standalone quarters without an explicit construction.
- `valuation_factors_rqdata.parquet` stores `dividend_yield` and `dividend_yield2` as decimal yields; retain the corresponding raw columns for audit rather than guessing units.
- Resolve benchmark IDs, membership effective dates, monthly versus daily weight frequency, and yield-curve tenors explicitly. Never substitute one reference family silently.
- Construct a `T+h` label from `trading_calendar.parquet`; if the target security lacks a price on that exact exchange date, leave the label missing rather than advancing to its next observation.
- For full-period work, load QFQ and HFQ sequentially with `load_recommended_daily_panel(...)`; use the two-view convenience loader only when preflight shows both views are manageable. `resolve_recommended_data_sources()` is diagnostic only.
- Require `has_price_observation=true` when a factor needs an actual price observation. Treat zero-volume/tradability, ST/PT, and suspension masks as staged universe decisions; the typical all-A-share protocol applies them to evaluation eligibility after factor calculation.
- Use `recommended_fundamentals.py` and `recommended_reference.py` for the versioned fundamentals, valuation/dividend, calendar, index, and yield-curve families. Their dataframe attributes carry the selections into the Stage 3 profile and final report.

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
- the local RQData bundle includes PIT capitalization and interval industry history, but exact fidelity still depends on matching the paper's capitalization basis, taxonomy source/version, classification level, and timing rule
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
- paper methods whose ordered transforms exceed the declared generic evaluator capabilities

Data gaps:

- classifications not provided by the supported RQData sources, including SWS 2021 exactly
- paper taxonomies or classification versions that cannot be mapped exactly to `sws`, `citics`, `citics_2019`, or `gildata`
- provider missing values and documented share inconsistencies affecting strict free-float protocols
- provider anomalies in a small minority of raw VWAP and zero-volume source rows
- benchmark return series for paper portfolio metrics

Implementation gaps:

- reviewed Stage 4B factor-library implementations are paper-specific and not yet the generic project core
- unknown formula functions should remain local helper candidates until repeated need justifies shared operators

## Near-Term Direction

Continue testing and hardening the fresh-agent loop, while adding the remaining
integrity contracts incrementally:

1. Generate a harness packet with the bundled skill.
2. Run a fresh AI agent in an isolated worktree.
3. Collect extraction/spec/report artifacts.
4. Compare those artifacts to golden JSON.
5. Classify failures as skill, schema, validation, normalization, data, evaluator, or reporting gaps.
6. Update the general workflow, not paper-specific hacks.
7. Retest the same paper.
8. Test a different paper to reduce overfitting.

The main deferred architecture work is typed evidence-derived stage completion,
calendar-based return labels, canonical metric lifecycle/reconciliation, and
immutable finalization snapshots. Industry-history and capitalization-basis
selection are now loader-supported; unresolved paper taxonomy/version semantics
and provider quality caveats must remain visible in support assessment and reports.

The most important missing tool is an automated or semi-automated golden comparator. It should report strict mismatches for formulas, fields, metrics, and source locations, and semantic review items for universe, sample period, transform specs, evaluation specs, and known limitations.
