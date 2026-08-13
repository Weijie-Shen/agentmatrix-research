# Paper Reproduction Pipeline Improvement Notes: Integrity and Evaluation

- Date: 2026-08-10
- Status: Agreed direction; implementation pending
- Scope: General paper-factor reproduction pipeline
- Related note: `2026-08-10-paper-reproduction-data-requirements.md`
- Motivation: Make automated reproductions structurally trustworthy while keeping data limitations, paper ambiguity, and incomplete evaluator coverage normally non-blocking

## Governing Principles

The pipeline is intended to support many different factor papers and eventually run without routine human review. Improvements must therefore be expressed as generic artifact contracts, execution semantics, evaluator capabilities, and reporting rules rather than branches for one paper.

The final implementation artifact remains the primary deliverable. Truth validation is the strongest available evidence that the implementation successfully reproduces the paper.

The following distinctions are important:

- execution completion is derived from artifacts and machine-checkable evidence;
- methodological limitations change comparability and are reported, but do not normally block execution;
- data insufficiency, substitutions, paper ambiguity, and unsupported secondary metrics are normally non-blocking;
- genuinely ambiguous data alignment, an unimportable implementation, or absent required execution evidence may prevent a stage from being described as completed;
- evaluation coverage must not be inferred from the number of diagnostic runs or sensitivity scenarios.

This note records the agreed improvements for previously identified problems 1, 2, 4, 5, 6, 7, 9, 10, 11, and 15.

## Priority Summary

| Priority | Problems | Objective |
| --- | --- | --- |
| P0 | 1, 2, 4, 11, 15 | Establish trustworthy artifacts, execution state, alignment, and finalization |
| P1 | 5, 7, 9, 10 | Make evaluation claims, temporal semantics, universes, and tests reliable |
| P2 | 6 | Expand evaluator metric coverage incrementally |

## Problem 1: No Canonical Final Factor Implementation

### Possible causes

The implementation stage currently behaves as a planner or scaffold generator. A generated scaffold can still contain `NotImplementedError` and empty implementation declarations, while the run script supplies a temporary inline factor implementation.

Downstream evaluation accepts arbitrary factor columns or frames, so it can evaluate the temporary implementation without proving that the declared final factor module exists or was used.

### Agreed improvement

Introduce a canonical `FactorImplementationArtifact` with at least:

```text
module_path
callable_import_path
implemented_factor_ids
factor_specification_hash
source_hash
required_input_columns
output_key_columns
output_factor_columns
```

The implementation stage may be completed only after the pipeline can:

1. import the declared module;
2. locate the declared callable;
3. execute it on a small probe panel;
4. confirm that declared factors are returned;
5. confirm that the module is not still an empty scaffold.

Downstream tests and evaluation must consume this artifact or its declared callable. They must not silently substitute an inline implementation or unrelated precomputed factor frame.

The contract should not hard-code a universal filename. It may support `factor.py`, `factors.py`, or another declared module. A project or reproduction specification may require `factor.py` when that is the intended deliverable.

Data limitations may produce `completed_with_limitations`, but an unimplemented scaffold cannot be described as a completed implementation.

## Problem 2: Stage Statuses Are Asserted Rather Than Derived

### Possible causes

Free-form stage-status mutation lets an agent mark a stage passed or completed without submitting the artifacts and validation evidence needed to justify that state. The pipeline state consequently behaves as a mutable progress log rather than an execution state machine.

### Agreed improvement

Replace direct status marking with typed stage results:

```text
StageResult
├── execution_status
├── input_artifacts
├── output_artifacts
├── validations
├── limitations
├── diagnostics
├── started_at
└── completed_at
```

Use controlled transitions such as:

```text
pending -> running -> completed
                   -> completed_with_limitations
                   -> failed
                   -> not_run
```

Stage completion should be derived from paper-agnostic evidence requirements:

- extraction: the extraction artifact parses and contains reconciled paper objects;
- normalization: normalized specifications reconcile with extracted factors and truth cases;
- implementation: the canonical implementation imports and executes;
- testing: test records prove that tests ran against the declared implementation hash;
- evaluation: every selected case is executed, deferred, failed, unsupported, or missing required data;
- reporting: the report is generated from a frozen run snapshot.

Limitations do not need to make a stage fail. The system should distinguish successful execution with limited comparability from absent or invalid execution evidence.

## Problem 4: The Generic Evaluation Planner Was Bypassed

### Possible causes

The framework contains evaluation-planning logic, but there is no mandatory orchestration boundary connecting plan construction to evaluator execution and truth comparison. A test script can manually compute selected metrics and pass arbitrary truth results into reporting.

### Agreed improvement

Add a canonical entry point:

```python
execute_evaluation_plan(
    plan,
    implementation_artifact,
    data_context,
) -> EvaluationBundle
```

Every executed evaluation must be linked to:

```text
truth_case_id
factor_id
evaluator_id
resolved_protocol
scenario_id
implementation_hash
data_snapshot_hash
metric_results
```

Paper-local evaluators may still be registered, but they must use the same evaluator protocol and result schema.

Manual or additional diagnostics can be attached to the result bundle. They do not count as executed paper truth cases unless they reference a selected `truth_case_id`, an evaluator, a resolved protocol, and an executed lifecycle state.

Planner bypass need not stop an automated run. It should create a visible limitation such as:

```text
evaluation_planner_bypassed: true
truth_validation_status: noncanonical
```

## Problem 5: Evaluation Coverage Was Overstated

### Possible causes

The reproduction conflated paper truth cases, factors, price-adjustment scenarios, execution attempts, and metrics. Multiple QFQ/HFQ or sensitivity executions of the same source comparison can therefore be counted as additional paper truth cases.

### Agreed improvement

Use separate stable identifiers:

- `truth_case_id`: one result or comparison defined by the paper;
- `execution_id`: one evaluator execution;
- `scenario_id`: one price view, universe choice, replacement-data setting, or other sensitivity scenario.

Coverage must be reported on separate dimensions, for example:

```text
paper truth cases extracted
paper truth cases assessed
paper truth cases selected
paper truth cases executed
execution runs
metrics requested
metrics eligible
metrics evaluated
metrics matched
```

QFQ, HFQ, alternative universes, and replacement-data runs are scenario variants. They must not increase the denominator or numerator for unique paper truth cases.

Add reconciliation rules:

```text
executed <= selected <= assessed <= extracted
```

Every selected case must end as executed, deferred, failed, unsupported, or missing required data. Narrative coverage claims should be generated from the structured counts rather than written independently by an agent.

## Problem 6: Limited Metric Truth Validation

### Current decision

This limitation is accepted for the current development stage. It is a P2 evaluator-roadmap item and should not block otherwise meaningful reproductions.

### Possible causes

The run selected the easiest available metric instead of accounting for every metric requested by the extracted truth source. Generic evaluators may also return nested metric structures, while the truth matcher expects canonical metric identifiers.

### Agreed improvement

Introduce a metric-level result lifecycle:

```text
MetricResult
├── metric_id
├── computed_value
├── paper_value
├── comparison_status
├── comparability
└── reason
```

Every requested metric should receive exactly one outcome:

```text
evaluated
diagnostic_only
unsupported
missing_data
deferred
not_extracted
```

Add canonical mappings from evaluator outputs to truth metric identifiers, for example:

```text
ic.rank_ic_mean -> rank_ic_mean
regression.t_abs_mean -> t_abs_mean
long_short.annualized_return -> long_short_annualized_return
```

Evaluator functionality can be filled incrementally. During that process, reports must state metric coverage precisely, such as `1 of 8 requested metrics evaluated`, rather than claiming that an entire table was reproduced.

## Problem 7: Forward-Return Label Semantics

### Possible causes

A label produced by shifting within each stock's remaining observations measures a number of surviving stock observations, not a number of market trading days. Pre-label filtering can therefore change the horizon. A data request ending on the evaluation end date can also omit the post-sample look-ahead needed to construct the last labels.

### Agreed convention

Represent labels using a generic `ReturnLabelSpec`:

```text
horizon
horizon_unit
anchor_date_rule
entry_offset
entry_price
exit_price
price_adjustment_view
missing_target_policy
```

When the paper defines `T+h` in trading days, use the global market calendar:

1. load the market calendar;
2. request sufficient post-sample look-ahead data;
3. map each anchor date to the exact market date at `T+h`;
4. join the target price by security and target date;
5. calculate the return;
6. apply evaluation-universe filters afterwards.

Do not implement a market-day horizon by shifting over a compressed per-security table. A missing target observation should remain missing unless the paper or provider explicitly specifies another convention. Any alternative convention must be recorded in the label specification and report.

## Problem 9: Filtering and Universe Timing

### Possible causes

ST/PT, suspension, listing-age, tradability, or other filters may be applied by physically deleting rows before time-series calculations or cross-sectional ranking. This can alter rolling windows, lags, ranks, and forward-return horizons. Papers often define the evaluation universe without fully specifying whether each filter also belongs inside factor calculation.

### Agreed convention

Represent calculation and evaluation universes separately:

```text
calculation_universe
evaluation_universe
```

Default behavior when the paper is not explicit:

- retain complete valid security history for time-series inputs;
- calculate raw factors using the declared calculation universe;
- apply ST/PT, suspension, future tradability, and return-realizability rules to the evaluation universe;
- never allow a future-state filter to modify a historical factor value unless the paper explicitly requires it;
- preserve the market calendar and avoid deleting rows before rolling and lag operations.

Every filter should record:

```text
filter_name
application_stage
effective_date_rule
source: explicit | inferred | defaulted
reason
```

Supported application stages should include:

```text
raw_data
factor_time_series
factor_cross_section
portfolio_formation
return_realization
```

If the paper is ambiguous, use the default convention, report the assumption, and optionally run a sensitivity scenario. Ambiguity is a limitation, not normally a blocking condition.

## Problem 10: Missing Formula-Level Tests

### Possible causes

Structural smoke tests can verify imports, shapes, numeric types, and non-null output, but cannot detect a mathematically wrong formula that produces plausible values. Scaffold tests also do not necessarily become tests of the completed implementation.

### Agreed improvement

Use reusable test tiers:

1. **Interface tests**: import, callable signature, required inputs, keys, and declared outputs.
2. **Deterministic formula tests**: tiny, hand-computable panels with exact expected values.
3. **Operator and property tests**: no cross-security leakage, no future leakage, correct warm-up, order stability, and mathematically justified invariance.
4. **External truth tests**: compare saved factor values or external paper truth when available.
5. **Smoke and performance tests**: realistic execution size, null rates, runtime, and memory.

Generate applicable requirements from normalized formula operators rather than from a particular paper. A formula using delay, rolling correlation, or cross-sectional rank should inherit reusable semantic tests for those operators.

Test evidence must include the tested implementation hash, executed command or runner identity, cases, and results. A non-null check alone cannot justify formula-correctness claims. Absence of external truth may remain a reported limitation rather than a blocking failure.

## Problem 11: Fragile Positional Alignment

### Possible causes

Assigning factor arrays by position assumes that market data and factor output have identical row counts and ordering. A sort, filter, duplicate, or missing observation can silently associate a factor value with the wrong security-date row.

### Agreed improvement

Define a canonical `FactorFrame` contract:

```text
key columns: date, security_id
key uniqueness: required
normalized key types: required
factor columns: numeric
```

Align factors to evaluation data through an explicit one-to-one join on the canonical keys. The alignment result should report:

```text
duplicate keys
left-only rows
right-only rows
matched-row ratio
factor null ratio
```

Duplicate keys or ambiguous many-to-many alignment should be blocking because the value mapping is undefined. Ordinary unmatched observations may remain non-blocking limitations, subject to the evaluation protocol.

A positional fast path may be retained for performance only after exact equality of the complete key arrays has been verified. Tests should cover shuffled rows, missing rows, and duplicate rows.

## Problem 15: Report Generated Before Final State Completion

### Possible causes

The final report is both a pipeline stage and an artifact generated from pipeline state. This creates a circular dependency: the report is built while its own stage is unfinished, and the state is then mutated after the report snapshot has already been taken.

### Agreed improvement

Separate scientific-run finalization from report packaging:

```text
finalize scientific stages
-> create immutable RunSnapshot
-> generate report from snapshot
-> register report artifact
-> export final job state
```

The immutable snapshot should include:

```text
stage results
artifact hashes
implementation hash
data provenance
evaluation coverage
limitations
truth-comparison results
```

The report and final job state should carry the same `run_snapshot_hash`. A consistency validator should reconcile stage summaries, evaluation counts, and artifact hashes across both outputs.

The report-packaging stage should not determine scientific reproduction success. If report export fails, the scientific run may remain completed while packaging is marked failed. A central `finalize_run()` operation should enforce the complete sequence.

## Recommended Implementation Order

1. Replace asserted stage statuses with typed results and derived transitions — problem 2.
2. Introduce and validate the canonical implementation artifact — problem 1.
3. Enforce keyed `FactorFrame` alignment — problem 11.
4. Implement calendar-based labels and staged universe filters — problems 7 and 9.
5. Generate formula-aware test evidence — problem 10.
6. Add the canonical evaluation-plan executor — problem 4.
7. Reconcile truth cases, executions, scenarios, and metric coverage — problem 5.
8. Finalize runs through immutable snapshots — problem 15.
9. Expand metric evaluator coverage incrementally — problem 6.

## Implementation Acceptance Criteria

The improvement is complete when:

1. Downstream stages can prove which canonical factor implementation they used.
2. Stage completion is derived from typed artifacts and validation evidence rather than agent assertions.
3. Planned truth cases, evaluator executions, sensitivity scenarios, and metrics have separate identities and reconciled counts.
4. Forward-return horizons use declared market-calendar semantics and retain required look-ahead data.
5. Calculation and evaluation universes are distinct, and every filter has an explicit application stage.
6. Generated tests verify formula semantics as well as structure and record the tested source hash.
7. Factor values are aligned by unique semantic keys, with unmatched and duplicate diagnostics.
8. Reports and final job state are produced from the same immutable run snapshot.
9. Unsupported metrics and methodological ambiguity remain visible limitations without unnecessarily preventing automated execution.
10. All behavior is driven by generic specifications, contracts, and evaluator capabilities rather than paper-specific conditions.

## Explicit Non-Goals

This improvement does not:

- make incomplete data globally blocking;
- require all evaluator metrics to be implemented immediately;
- require human approval for every inferred convention;
- hard-code this paper's factor formulas, truth tables, horizons, filters, or adjustment views;
- count sensitivity scenarios as additional paper truth cases;
- replace truth validation with internal tests alone.
