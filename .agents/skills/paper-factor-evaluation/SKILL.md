---
name: paper-factor-evaluation
description: Plan, execute, and truth-match paper-aware IC evaluations in AgentMatrix Factor Lab. Use for Stages 6-7, resolved IC truth sources, ordered transforms and neutralization, resource-bounded execution, metric eligibility, comparability, and paper-reported evaluation-result matching.
---

# Paper Factor Evaluation

Evaluate the implemented factor under the paper's protocol or an explicitly resolved approximation. Never mutate extracted truth to fit local capabilities.

## Plan before computing

Read candidate IC truth, data profiles, Stage-3 support assessments, implementation artifacts, and evaluator capabilities. For `paper_extraction.ic_analysis.v2`, a persisted Stage-3 data profile is mandatory: Stage 6 must not select a case from paper evidence alone. Use `build_paper_evaluation_plan(...)` to:

1. assess every candidate truth source;
2. select exactly one highest-supported, unconflicted IC truth source per factor without looking at metric closeness;
3. preserve `paper_protocol`;
4. create separate `resolved_protocol` records;
5. record structured deviations and affected metrics;
6. assign comparability and metric eligibility;
7. execute only selected cases.

Every truth case needs one lifecycle outcome: `selected`, `executed`, `deferred_by_budget`, `unsupported_evaluator`, `insufficient_data`, `paper_truth_conflict`, `superseded_by_better_supported_truth`, or `evaluation_error`.

Do not complete Stage 6 with zero selected cases merely because the first extracted case is data-heavy. Revisit alternative extracted truth, materialize constructible labels, and resolve accepted proxies first. Defer all cases only after those general recovery paths are exhausted and recorded.

If support assessment marks a case executable, Stage 6 requires an actual canonical execution attempt. A resource deferral requires a persisted preflight or caught `ResourceBudgetExceededError`; do not infer it from panel size or the absence of a preferred partition helper.

Resource evidence must describe the actual requested panel. Never substitute a probe or reduced frame while declaring a full-period request, and never choose an artificially tiny memory budget to manufacture a deferral. Set `memory_budget_bytes` from a real runtime limit when one is known; otherwise leave it unset and let the actual execution establish whether the environment can complete it.

The v2 workflow has only the `ic_analysis` evaluator type. Rank-IC mean, ICIR, IC standard deviation, and positive-ratio measures printed in the selected result block are computed together and compared together when eligible. Alternative raw/neutralized/horizon/sample protocols remain report-visible as superseded, conflicted, or unsupported cases; they are not additional selected methods.

## Resolve protocol safely

Keep paper requirements and runtime decisions side by side. Preserve shared protocol, universe, operation-pipeline, metric, and semantic-requirement IDs in `paper_protocol`; place only local bindings and substitutions in `resolved_protocol`. For substitutions record semantic relationship, reason, expected effect, affected metrics, selection mode, and downgraded comparability.

Do not silently:

- replace WLS with OLS;
- omit controls or weights;
- shorten samples or horizons;
- change return frequency;
- replace point-in-time classification with a current snapshot;
- change portfolio construction or execution price;
- treat a proxy as exact.

Before neutralization, WLS, or portfolio formation, verify that the resolved capitalization basis and industry taxonomy/level match the immutable paper protocol. Join point-in-time capitalization by security/date and resolve interval industry membership at the declared evaluation or formation date. Capitalization stays on its unadjusted basis in both QFQ and HFQ scenarios; industry codes are categorical controls. A different cap basis, taxonomy, level, static snapshot, or timing rule is a structured deviation, never an exact match.

Before fundamental, benchmark-relative, universe-constrained, or excess-return evaluation, verify financial announcement/version timing, benchmark identifier, constituent effective date, index-weight family, exchange-calendar horizon, and yield tenor/unit. Monthly and reconstructed daily index weights are not interchangeable. Benchmark levels remain provider-unadjusted and must not receive stock adjustment. Record any period-rate conversion before subtracting a risk-free rate.

A diagnostic proxy may execute, but affected metrics must be diagnostic-only or proxy-grade.

## Execute ordered transforms

Apply the resolved `transform_spec` exactly in order. Preserve structured transforms on factor exposure, controls, weights, labels, and outputs. Capability-check operations and encodings before execution.

Distinguish explicit `none`, inferred method, project default, and unknown. Never override explicit `none`. Do not flatten transformed controls into raw column names.

Keep the full calculation panel separate from evaluation inputs. Join certified factor output only by unique date/security keys. Apply ST/PT, suspension, future-tradability, and portfolio eligibility masks only at their declared evaluation stage. In the common all-A protocol, factor history includes ST and suspended observations when otherwise valid; the evaluation cross-section removes ST/PT at the signal date and securities suspended on the extracted next-evaluation date.

## Return and metric correctness

Use forward alignment for future returns. Use `materialize_forward_return(...)` only for security-observation horizons; use `materialize_calendar_forward_return(...)` for exact exchange-trading-day `T+h` horizons. Do not compute past returns or let suspension/missing observations redefine the paper horizon.

Respect frequency: `t+1` means the next relevant period, not automatically the next trading day. Build timing from the extracted signal date, status-filter effective dates, exchange-calendar `T+h` target, and paper-defined return interval; do not hardcode every case to an entry at `t+1`. Preserve Pearson-versus-Spearman IC type, horizon, preprocessing/control order, missing-exposure policy, and sign conventions. Apply a paper-declared absolute ICIR convention before truth matching; do not compare signed evaluator IR to an absolute paper statistic.

Run selected cases through `execute_evaluation_plan(...)` with `EvaluationDataContext.resource_config` for full-period work. Honor resource preflight, column projection, sequential execution, and verified partitions.

Treat Stage 3 profiling and Stage 6 execution as separate passes. During profiling, retain only serializable profiles and a bounded certification probe, then release the full panel. During evaluation, load exactly one scenario, materialize its labels, execute it, persist its bundle, delete all references to that panel, and release memory before loading the next scenario. Do not append full scenario frames to a list or keep QFQ and HFQ resident together.

Run long full-panel evaluations in a persistent command session. If the command tool yields a session or cell identifier, keep polling that same process with the matching continuation tool until it exits; a yield deadline is not an execution failure. Do not restart the calculation merely because one tool call returned before process completion, and do not wrap canonical execution in a short shell timeout.

Persist each completed scenario immediately with `export_evaluation_bundle(...)`. On resume, use `load_evaluation_bundle(...)`, validate implementation identity and scenario coverage, and run only missing work. Use `merge_evaluation_bundles(...)` before combined reporting/truth matching. A later failure must not downgrade or erase earlier durable `executed` records.

Only the direct `EvaluationBundle` returned by `execute_evaluation_plan(...)` is execution evidence. Never hand-author, reshape, summarize, or backfill an `executed` record or calculated metric from paper truth. A reviewable bundle retains its `evaluation_bundle/v2` schema, canonical execution IDs, `canonical_plan_executor` mode, certified source/specification hashes, SHA-256 snapshot identity, resource preflight/telemetry, requested/executed sample lineage, alignment diagnostics, universe diagnostics, persisted cross-sectional IC values, and every per-record field. Paper values enter only the subsequent truth-matching call.

## Truth matching

Use `compare_evaluation_metrics_to_paper_truth(...)` only on metrics reported by the selected IC truth source and marked truth-match eligible. Never use the resulting distance to revisit truth-source selection.

For persisted scenario bundles, use `compare_evaluation_bundle_to_paper_truth(...)` so comparability and metric-eligibility policy comes from each execution record rather than being reconstructed after interruption.

Assign:

- `exact_match` for exact/tolerance agreement under exact comparability;
- `approximately_consistent` for sufficiently comparable close agreement;
- `directionally_consistent` for a directional proxy;
- `inconclusive_due_to_protocol_gap` when comparison cannot support positive or negative evidence;
- `inconsistent` only when sufficiently comparable results materially disagree;
- `not_evaluated` for unsupported, deferred, or unexecuted cases.

Missing diagnostic-only metrics and unsupported cases are coverage gaps, not failed metric comparisons. Report numerator and denominator explicitly.

## Required outputs

- complete evaluation plan with assessed/selected/deferred cases;
- resolved protocols and structured deviations;
- evaluation artifacts for each executed price view and case;
- truth-match results with eligible metrics and denominators;
- Stage 6 and Stage 7 pipeline updates.
