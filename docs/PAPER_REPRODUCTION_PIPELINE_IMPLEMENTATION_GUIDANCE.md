# Paper Reproduction Pipeline: Automated Degradation and Truth Validation

## Purpose

This document is an implementation handoff for improving the paper-factor reproduction pipeline.

The final objective remains:

1. implement the paper factor correctly in `factor.py`; and
2. use reproduction of paper-reported evaluation results as the primary and most convincing validation.

The pipeline is intended to run automatically across many factor papers. It must therefore continue under common data and evaluator limitations instead of repeatedly stopping for human review. Continuing does not mean hiding methodological differences: every limitation and substitution must remain machine-readable and visible in the final report.

This work must not replace truth validation with a separate factor-confidence framework. Unit and semantic tests are supporting controls; paper truth matching remains the main validation result.

## Core policy

Use the following principle throughout the implementation:

> Continue whenever a meaningful factor implementation or evaluation can be produced, select the most strongly supported paper truth available, record every deviation, and restrict truth claims to results that are sufficiently comparable.

Data insufficiency is normally a limitation, not a pipeline blocker.

Hard blocking should be rare and factor-local. Appropriate hard blockers include:

- the factor formula cannot be determined;
- formula-required data cannot be loaded or constructed by any supported route;
- an essential formula operator is unresolved;
- factor code cannot execute after bounded repair attempts;
- no paper evaluation truth was extracted and the workflow requires paper truth.

The following should normally not block factor implementation:

- incomplete paper sample coverage;
- unavailable neutralization controls;
- unavailable regression weights;
- unavailable benchmark data;
- an unsupported secondary evaluation family;
- a point-in-time limitation in industry or classification data;
- inability to reproduce every truth source in one run.

These conditions should instead trigger alternative truth selection, a proxy evaluation, or a completed run with limitations.

## Non-goals

- Do not build a universal formula compiler.
- Do not require human review for every material deviation.
- Do not put Huatai-specific conditions in shared pipeline modules.
- Do not silently change an extracted paper evaluation case.
- Do not choose a truth source after inspecting which computed result is closest.
- Do not modify factor code merely to force aggregate evaluation metrics to match.
- Do not count unsupported, skipped, or data-limited truth cases as metric failures.
- Do not treat unit tests as a replacement for paper truth validation.

## 1. Separate execution outcome from truth-validation outcome

The current stage status mixes operational completion, data adequacy, and validation strength. Introduce separate fields.

### Execution status

Recommended values:

```text
pending
running
completed
completed_with_limitations
failed
```

This controls whether automation may continue.

### Truth-validation status

Recommended values:

```text
exact_match
approximately_consistent
directionally_consistent
inconclusive_due_to_protocol_gap
inconsistent
not_evaluated
```

Only `inconsistent` is direct negative truth evidence. `not_evaluated` and `inconclusive_due_to_protocol_gap` are coverage/compatibility outcomes, not factor failures.

Keep backward-compatible aggregate stage statuses if external callers require them, but derive those statuses from the more precise fields.

### Human-review policy

`needs_human_review` should be reserved for ambiguity that automation cannot safely resolve and that materially changes the factor definition or the meaning of the selected truth.

Data limitations and documented proxy methods should normally produce `completed_with_limitations`, not `needs_human_review`.

## 2. Preserve extracted truth and resolve a separate runtime case

The extracted truth source represents what the paper did and must be immutable during execution.

Add a separate resolved evaluation artifact representing what the current run will do.

Suggested schema:

```json
{
  "factor_name": "Alpha3",
  "source_truth_id": "alpha3_table52_industry_size_t20_ic_regression",
  "selection_reason": "highest support score among extracted truth sources",
  "paper_protocol": {},
  "resolved_protocol": {},
  "support_assessment": {},
  "deviations": [],
  "comparability": "proxy",
  "truth_match_eligible_metrics": [
    "rank_ic_mean",
    "rank_ic_std",
    "ic_ir",
    "ic_positive_ratio"
  ],
  "diagnostic_only_metrics": [
    "factor_return_mean",
    "t_abs_mean",
    "t_abs_gt_2_ratio",
    "t_mean"
  ]
}
```

Do not overwrite fields such as `regression_type`, `weight_col`, sample period, transform specification, or return horizon on the extracted truth object.

Suggested comparability values:

```text
exact
materially_comparable
proxy
directional_only
not_comparable
```

## 3. Add evaluation-case-aware data assessment

Keep the existing formula dataframe validation, but add a second validation layer for every candidate evaluation truth source.

Suggested entry point:

```python
assess_evaluation_case_support(
    truth_source,
    data_profile,
    evaluator_capabilities,
) -> EvaluationCaseSupportAssessment
```

The assessment should cover:

- formula-required data;
- evaluation-required data;
- controls;
- filters;
- requested and available date ranges;
- trading-calendar support;
- adjusted/unadjusted field conventions;
- point-in-time properties;
- regression/backtest weights;
- execution-price requirements;
- benchmark requirements;
- evaluator feature support;
- expected metric coverage.

Suggested structured requirement result:

```json
{
  "requirement": "sqrt_free_float_market_cap",
  "category": "regression_weight",
  "paper_value": "sqrt_free_float_market_cap",
  "available_value": null,
  "availability": "missing",
  "substitute": null,
  "severity": "material",
  "affected_metrics": [
    "factor_return_mean",
    "t_abs_mean",
    "t_abs_gt_2_ratio",
    "t_mean"
  ],
  "recommended_action": "try_alternative_truth_then_proxy"
}
```

Recommended availability values:

```text
available
partially_available
constructible
available_with_quality_warning
missing
unknown
```

The existing `DataFrameValidationRequest.from_factor()` should remain focused on formula inputs. Do not overload it with every evaluation concept; add a dedicated evaluation support contract.

## 4. Build a reusable data profile

Before truth selection, generate one structured profile for each data source or joined panel.

It should contain:

- file/source identity and manifest information;
- actual date coverage by field;
- row, date, and security counts;
- missingness by field and period;
- duplicate keys;
- adjustment conventions;
- units and scaling where known;
- point-in-time status;
- static versus date-varying classifications;
- trading-status coverage;
- benchmark coverage;
- detected calendar;
- derived-field lineage.

Derived fields should record lineage. Example:

```json
{
  "field": "vwap",
  "sources": ["amount", "volume", "ex_cum_factor"],
  "raw_formula": "amount / volume",
  "adjustment_formula": "raw_vwap * price_multiplier",
  "price_basis": "qfq_or_hfq_selected_for_this_run",
  "compatible_with_selected_ohlc": true,
  "limitations": [
    "provider VWAP/candle sanity exceptions are retained and reported"
  ]
}
```

Do not make every quality warning blocking. Feed them into support scoring and the final limitation report.

## 5. Select the best-supported truth source automatically

Truth selection must occur after data profiling and evaluator capability discovery, but before evaluation metrics are calculated.

For each factor:

1. start from explicitly selected truth sources, if present;
2. include additional extracted truth sources allowed by the factor's `truth_selection_rule`;
3. assess support for every candidate;
4. rank candidates by support;
5. choose the best-supported candidate within the evaluation-method budget;
6. retain other cases as deferred, unsupported, or alternative evidence;
7. record the scoring and selection reason.

Suggested score components, each normalized to `[0, 1]`:

```text
sample_coverage
required_data_coverage
evaluator_capability_coverage
protocol_similarity
transform_support
universe_filter_support
metric_coverage
```

Use transparent weights stored in configuration. A reasonable initial priority is:

1. evaluator and required-data feasibility;
2. protocol similarity;
3. sample overlap;
4. metric coverage.

Do not score based on computed metric closeness.

Tie-breaking should be deterministic:

1. higher comparability;
2. greater date overlap;
3. more paper metrics supported;
4. fewer material deviations;
5. stable truth ID ordering.

### Alternative truth behavior

If a neutralized/WLS truth is poorly supported but an unneutralized/OLS or IC truth from the same paper is well supported, prefer the better-supported paper truth.

For the Huatai example, full-period Table 7 unneutralized truth should be considered when market-cap data prevents a full-period Table 52 reproduction. This behavior must arise from generic support scoring, not a Huatai-specific branch.

## 6. Automated degradation strategy

Use the following generic fallback sequence:

```text
exact paper case
    ↓ unavailable
alternative extracted paper truth with better data support
    ↓ unavailable
same truth with reduced sample but otherwise comparable protocol
    ↓ unavailable
proxy method with explicit deviations
    ↓ unavailable
directional or descriptive evaluation
    ↓ unavailable
factor implementation completed; truth not evaluated
```

Every fallback should create deviations and update comparability automatically.

Do not mark the entire factor family as blocked because one factor or one evaluation case is unsupported.

## 7. Add structured deviation records

All substitutions and omissions must be recorded in a common paper-agnostic schema.

Suggested fields:

```json
{
  "category": "sample_period",
  "paper_value": "2010-01-04/2019-04-30",
  "resolved_value": "2017-01-03/2019-04-30",
  "reason": "market-cap history begins in 2017",
  "severity": "material",
  "affected_metrics": ["*"],
  "truth_matching_policy": "proxy_or_partial_period",
  "source": "automatically_detected"
}
```

Suggested severity:

```text
cosmetic
minor
material
fundamental
```

Severity should influence comparability and eligible truth metrics, not normally stop execution.

Examples:

- shorter sample: usually `material`;
- total-cap proxy for free-float cap: usually `material`;
- OLS substituted for paper WLS: `material` or `fundamental` for regression metrics;
- missing benchmark for an IC-only case: irrelevant;
- static industry map used over history: `material` with point-in-time warning;
- rounding a reported window through the repository's documented convention: potentially `minor`.

## 8. Add granular evaluator capabilities

An evaluator family name is not enough. Evaluators should advertise supported features.

Example:

```json
{
  "evaluator_id": "generic_ic_regression_v1",
  "evaluation_families": ["ic_analysis", "ic_regression"],
  "capabilities": {
    "ic_types": ["spearman_rank_ic", "pearson_ic"],
    "regression_types": ["ols", "wls"],
    "categorical_controls": true,
    "continuous_controls": true,
    "weighting": true,
    "return_horizon_units": ["trading_day"],
    "standard_errors": ["classical"],
    "transform_steps": [
      "median_mad",
      "cross_sectional_regression_residual",
      "cross_section_zscore",
      "do_not_fill"
    ],
    "metrics": [
      "rank_ic_mean",
      "rank_ic_std",
      "ic_ir",
      "ic_positive_ratio",
      "factor_return_mean",
      "t_abs_mean",
      "t_abs_gt_2_ratio",
      "t_mean"
    ]
  }
}
```

The planner should match the requested evaluation specification field by field.

Do not infer that a case is supported merely because its family is `ic_regression`.

## 9. Grow evaluator coverage incrementally

Use an evaluator registry with two scopes:

```text
generic evaluators
paper-family-local evaluators
```

Recommended resolution order:

1. exact generic evaluator;
2. compatible generic evaluator with declared deviations;
3. best-supported alternative truth;
4. existing paper-family-local evaluator;
5. generate a paper-local evaluator implementation target;
6. defer the unsupported method while continuing other validation.

Paper-local evaluator targets should live under the paper/factor family, for example:

```text
research_core/factor_lab/libraries/<family>/paper_evaluators.py
```

When the same evaluator pattern appears across multiple papers, promote it into the generic registry with shared tests.

Initial high-value generic additions are:

- IC decay and half-life analysis;
- layered/quantile portfolio backtesting;
- configurable execution timing and transaction costs;
- metric-aware benchmark/excess-return reporting.

## 10. Make pipeline state persistent and framework-controlled

The pipeline state must be loaded and updated across stages. Later scripts must not reconstruct earlier stages and manually mark them passed.

Required behavior:

- one job ID maps to one persistent state;
- stage updates merge into the existing state;
- previous diagnostics and artifacts are preserved;
- stage success requires the expected artifact class;
- stage execution checks prerequisite execution status;
- soft limitations do not prevent continuation;
- hard failures prevent only dependent work;
- factor-local failures do not unnecessarily block unrelated factors.

The existing `ready_for_stage()` method should be used or replaced by an execution-policy method that distinguishes hard failures from limitations.

Suggested API:

```python
decision = pipeline.execution_decision("evaluation")

decision.allowed
decision.hard_blockers
decision.limitations
decision.deferred_dependencies
```

## 11. Respect the evaluation plan during execution

The executor must consume `selected_evaluation_cases`, not loop over every extracted truth source.

Each truth case should end in exactly one lifecycle state:

```text
selected
executed
deferred_by_budget
unsupported_evaluator
insufficient_data
superseded_by_better_supported_truth
evaluation_error
```

Only executed cases should enter metric truth matching.

Unsupported, skipped, or insufficient-data cases must remain visible in coverage reporting, but must not be counted as failed metric comparisons.

## 12. Preserve trading chronology and panel semantics

Add a resolved timing contract for each evaluation case:

```json
{
  "signal_date": "t",
  "history_cutoff": "t",
  "eligibility_date": "t",
  "tradability_filter_date": "t+1",
  "entry_date": "t+1",
  "entry_price": "paper_defined",
  "exit_date": "market_calendar_t_plus_20",
  "exit_price": "paper_defined",
  "return_interval": "entry_to_exit"
}
```

Keep separate:

- raw history used to compute the factor;
- signal-date universe filters;
- future entry/tradability filters;
- return-validity filters.

Do not remove rows from a stock's historical series before rolling factor calculation merely because the row is excluded from an evaluation cross-section.

Forward trading-day returns should be constructed using a market calendar or aligned date map, not the twentieth surviving observation after filtering.

The timing model must allow other paper frequencies such as weekly, monthly, quarterly, event-driven, and announcement-safe accounting factors.

## 13. Improve truth matching while keeping it primary

Truth validation remains the main validation result. Improve it so it understands protocol compatibility and metric type.

### Before matching

Truth matching should receive:

- computed metrics;
- original paper truth;
- resolved evaluation case;
- deviations;
- comparability classification;
- metric eligibility.

### Matching rules

Support:

- absolute tolerance;
- relative tolerance;
- sign agreement;
- direction agreement;
- rank-order agreement across factors;
- monotonicity agreement;
- paper rounding precision;
- chart-derived value uncertainty;
- optional confidence-interval overlap.

Truth sources may specify a matching policy. If absent, infer a default policy from metric names and source precision.

### Result semantics

Use:

```text
exact_match
approximately_consistent
directionally_consistent
inconclusive_due_to_protocol_gap
inconsistent
not_evaluated
```

Rules:

- A non-comparable proxy must not produce `exact_match`.
- A material deviation affecting a metric can make that metric diagnostic-only.
- Missing evaluator support produces `not_evaluated`, not `inconsistent`.
- Insufficient sample comparability may produce `inconclusive_due_to_protocol_gap`.
- An executed, sufficiently comparable method with material metric disagreement produces `inconsistent`.

### Aggregate reporting

Report separate counts:

```text
truth cases extracted
truth cases assessed
truth cases selected
truth cases executed
truth cases sufficiently comparable
truth cases matched
truth cases inconsistent
truth cases deferred
```

Do not use a denominator containing unsupported or deliberately skipped cases when reporting the truth-match pass rate.

## 14. Keep implementation tests as supporting controls

Improve generated implementation tests because obvious formula errors should be caught before expensive evaluation, but do not present them as a substitute for truth validation.

Generic supporting tests should cover:

- formula output schema;
- row-order invariance;
- absence of look-ahead under future-data perturbation;
- rolling warm-up behavior;
- extracted missing-value policy;
- no silent fill unless the formula/spec authorizes it;
- cross-sectional versus time-series axis behavior;
- per-factor calculation independence;
- agreement with a small slow/reference calculation where supported.

Paper-family tests should cover formula-specific operator composition and derived-field definitions.

For the Huatai implementation, the current use of `fillna(0)` and `fillna(0.5)` conflicts with the extracted `do_not_fill` behavior and should be caught by these supporting tests.

The authoritative final validation should still be the best-supported paper truth reproduction.

## 15. Reporting requirements

The final report should begin with:

1. whether `factor.py` was produced;
2. which paper truth was selected;
3. why it was selected;
4. whether evaluation was exact, comparable, proxy, or directional;
5. the truth-validation result;
6. the most important limitations.

Include:

- extracted versus resolved protocol diff;
- data coverage table;
- evaluator capability coverage;
- deviations and affected metrics;
- truth source selection scores;
- executed and deferred cases;
- metric comparison table;
- exact/approximate/directional/inconclusive/inconsistent status;
- formula implementation and supporting test status;
- unresolved evaluator targets.

The report must not describe unsupported cases as failed factors.

## 16. Skill-oriented implementation changes

The Hermes skill is the primary policy driver. Update it before or alongside framework changes.

The skill should explicitly instruct the agent to:

1. load and profile both canonical paper price views through `load_recommended_paper_panels(test_end_date=...)`: testing-end-anchored QFQ and initial-baseline HFQ, each derived from the same raw RQData panel;
2. preserve all extracted truth sources;
3. assess truth support before selecting a case;
4. select truth before computing results;
5. prefer the most supported paper truth;
6. continue with reduced-period or proxy evaluation when exact reproduction is unavailable;
7. never mutate the paper protocol silently;
8. generate a resolved evaluation case and deviation ledger;
9. use generic evaluator capabilities rather than family-name assumptions;
10. create paper-local evaluator targets for unsupported methods;
11. execute only selected cases;
12. keep unsupported cases out of the failed-match denominator;
13. report limitations without unnecessarily requesting human review;
14. keep paper truth validation as the primary validation;
15. avoid changing factor code solely to chase evaluation metrics.

Replace broad instructions such as “stop on `needs_human_review`” with a narrower policy:

```text
Stop only for unresolved factor-definition ambiguity, unavailable formula-required
data with no supported construction, or an unrecoverable implementation failure.
For evaluation-data and evaluator limitations, continue through automatic truth
selection or documented degradation and report the resulting limitation.
```

## 17. Suggested module-level changes

The exact class names may be adjusted to existing conventions.

### `data_validation.py`

- Keep formula dataframe validation.
- Add reusable data profiling.
- Add evaluation-case support assessment.
- Add structured availability and quality diagnostics.

### `paper_evaluation.py`

- Add truth-source support scoring.
- Add deterministic truth selection.
- Add resolved evaluation case construction.
- Add fallback/degradation policy.
- Add case lifecycle statuses.

### `evaluators.py`

- Register capability descriptors.
- Validate requested features before execution.
- Avoid hidden defaults or method substitutions.
- Return evaluator identity and resolved parameters with metrics.

### `truth_matching.py`

- Accept comparability and metric eligibility.
- Add metric-aware policies.
- Return the expanded truth-validation statuses.
- Keep protocol gaps separate from inconsistency.

### `pipeline.py`

- Load and merge persistent state.
- Separate execution and validation status.
- Enforce hard dependencies while permitting limitations.
- Preserve prior diagnostics.

### `reporting.py`

- Render data/evaluator support.
- Render protocol deviations.
- Render selection rationale.
- Use correct denominators.
- Lead with truth-validation outcome and limitations.

### `implementation.py`

- Carry evaluation-support summaries into the implementation manifest.
- Keep factor implementation possible when only evaluation data is limited.
- Generate supporting tests from explicit missing-value and operator semantics.

### `agent_harness.py` and bundled skill

- Add the automatic-degradation workflow.
- Require resolved-case and deviation artifacts.
- Update stopping rules.
- Emphasize best-supported truth selection and primary truth validation.

## 18. Backward compatibility

Avoid a single large schema break.

Recommended rollout:

1. add new fields with defaults;
2. preserve current serialized fields;
3. derive legacy status from new execution/truth statuses;
4. support loading older job artifacts;
5. migrate report rendering to prefer new fields;
6. deprecate direct mutation of extracted evaluation cases;
7. later remove obsolete fields after existing callers migrate.

Existing evaluator functions can be registered with capability metadata without rewriting them first.

## 19. Tests and acceptance criteria

### Generic unit tests

- A case with complete data is selected over a partial case.
- A partial alternative truth is selected over an impossible primary truth.
- Selection is unchanged when computed metric values change.
- An extracted truth object is unchanged after resolution and execution.
- A missing evaluation-only field does not block factor implementation.
- A missing formula-required field blocks only the affected factor.
- A material deviation produces `completed_with_limitations`.
- Unsupported cases do not count as inconsistent truth matches.
- Only selected and executed cases enter truth matching.
- Persistent state retains diagnostics from earlier stages.
- Evaluator family match without required feature support is rejected as exact support.
- Metric eligibility changes when a deviation affects only some metrics.
- A proxy case cannot be labeled `exact_match`.

### Huatai regression test

Given the known local-data constraints:

- factor implementation continues for all formula-supported factors;
- the planner detects that full-period Table 52 WLS is not exactly supported;
- it searches for a better-supported extracted truth, including unneutralized truth;
- if no better truth is available, it resolves a partial/proxy Table 52 case;
- it does not mutate WLS to OLS inside the original truth source;
- it records the 2017 start date and missing free-float weight;
- regression metrics affected by OLS substitution are diagnostic-only or proxy-grade;
- IC metrics may remain truth-match eligible according to sample comparability policy;
- IC decay and layered cases are deferred or targeted for evaluator implementation;
- deferred cases are not reported as factor failures;
- the final report uses the correct selected/executed/comparable denominator.

### End-to-end acceptance

The implementation is acceptable when an automated run can:

1. extract multiple paper truth cases;
2. profile incomplete data;
3. choose the best-supported truth without inspecting output closeness;
4. implement `factor.py`;
5. run supporting implementation tests;
6. execute the strongest feasible evaluator;
7. compare eligible metrics with paper truth;
8. classify the truth-validation result correctly;
9. continue despite non-fatal limitations;
10. produce a complete limitation and deviation report without unnecessary human review.

## 20. Recommended implementation order

### Phase 1: Correct orchestration

1. Persistent pipeline state.
2. Selected-case-only execution.
3. Correct truth-validation denominators.
4. Structured deviations.
5. Separate execution and truth-validation statuses.

### Phase 2: Adaptive planning

6. Data profiles.
7. Evaluation-case support assessment.
8. Evaluator capability descriptors.
9. Deterministic truth scoring and selection.
10. Resolved evaluation cases.

### Phase 3: Better validation

11. Protocol-aware metric eligibility.
12. Metric-aware truth matching.
13. Expanded final reports.
14. Supporting implementation tests for missing-value and timing behavior.

### Phase 4: Evaluator growth

15. Generic IC decay evaluator.
16. Generic layered portfolio evaluator.
17. Promotion workflow from repeated paper-local evaluators to generic evaluators.

## Final design test

For every proposed framework change, ask:

1. Does it help the agent choose or execute the strongest feasible paper truth?
2. Does it allow automation to continue under ordinary data limitations?
3. Does it preserve enough information to explain why results differ?
4. Is the logic generic across papers and evaluation methods?
5. Can a paper-specific behavior live in an evaluation case or paper-local evaluator instead?
6. Does the final report still make paper truth validation the primary conclusion?

If the answer to these questions is yes, the change is aligned with the project goal.
