# Paper Reproduction Pipeline Improvement Notes: Resource-Bounded Evaluation

- Date: 2026-08-10
- Status: First resource-preflight/projected-execution tranche implemented; partition/checkpoint work pending
- Scope: General paper-factor reproduction pipeline
- Related notes:
  - `2026-08-10-paper-reproduction-data-requirements.md`
  - `2026-08-10-paper-reproduction-pipeline-integrity-and-evaluation.md`
- Motivation: Preserve correct calculation/evaluation-universe semantics without repeated full-panel copies or silent sample truncation

## Incident Summary

A full 2010-01-04 through 2019-04-30 evaluation was killed after the pipeline introduced separate calculation and evaluation panels, post-calculation filters, canonical keyed alignment, explicit control transformations, neutralization, and canonical plan execution.

These methodological changes are valid. The failure came from representing them with repeated in-memory DataFrame copies.

The full request contained 6,100,511 rows. The successful retry contained 1,141,310 rows. Loading only the shortened QFQ and HFQ panels reached a measured process peak of approximately 3.71 GB before canonical alignment and evaluation. The full sample has about 5.35 times as many rows.

The retry shortened the period to 2018-2019 and converted industry labels to numeric codes. Those actions reduced resource use but changed the scientific protocol and must not be silent performance fallbacks.

## Required Semantics

The default execution order remains:

1. Load complete calculation history.
2. Calculate raw factor values.
3. Align factors and evaluation inputs by date and security.
4. Apply evaluation eligibility.
5. Apply evaluation transformations or neutralization.
6. Calculate evaluation metrics.

ST/PT, next-day suspension, future tradability, and return-realizability filters must not change historical factor values unless the paper explicitly requires this.

Missing formula inputs are different from explicit filters. A factor can be null because of missing prices or insufficient rolling history even when the security was not explicitly excluded.

## Root Cause

The pipeline currently turns logical separation into multiple physical frames. A run may retain or create:

- raw, QFQ, and HFQ panels;
- calculation and evaluation copies;
- another executor copy;
- full sorted copies for snapshot hashing;
- a factor-callable input copy;
- a factor output frame;
- normalized key copies and an outer key merge;
- an aligned factor/evaluation frame;
- separate filter, transformation, and neutralization copies for each case.

Additional amplification occurs because:

- both adjustment views are built when only one is evaluated;
- shared universe filters are repeated for every factor;
- shared industry and size controls are transformed for every factor;
- alignment performs an outer merge before testing the exact-key fast path;
- evaluators receive the wide market panel instead of required columns only;
- Python/native allocators may retain released memory between cases.

Explicit neutralization is not inherently too large. Its present implementation adds several full-frame copies and repeated grouped passes for every selected factor.

## Agreed Improvements

### 1. Make the separation logical

Use one immutable base panel with separately declared factor columns, evaluation labels, controls, and a keyed evaluation-eligibility mask.

Separate calculation and evaluation universes must not automatically mean two full copies of identical data.

### 2. Add resource preflight

Estimate before execution:

- rows, columns, and dtype memory;
- active price scenarios;
- factor output width;
- selected cases;
- expected copy amplification;
- warm-up and label look-ahead;
- estimated peak memory and temporary storage.

If projected memory exceeds the configured budget, automatically select bounded execution. Do not shorten the paper period.

### 3. Execute one price scenario at a time

Build, calculate, persist, and release QFQ before loading HFQ. A sensitivity scenario should not remain resident during primary-scenario evaluation.

### 4. Project columns at each boundary

Examples:

- Alpha13 calculation: date, security, close, volume.
- Alpha13 IC: keys, Alpha13, forward return, eligibility.
- Alpha13 neutralized regression: keys, Alpha13, return, industry, size, weight, eligibility.

Do not copy the complete market panel into every evaluator.

### 5. Persist a narrow canonical FactorFrame

Calculate factors once and persist a keyed, partitioned artifact containing:

- date and security;
- factor columns;
- implementation and specification hashes;
- data snapshot and scenario identifiers.

IC, regression, portfolio, truth-value, and diagnostic evaluation should reuse it.

### 6. Use bounded date partitions

For factor calculation, load each target partition with the maximum required rolling warm-up, calculate values, discard warm-up outputs, persist the target partition, and release temporary frames.

For labels, add market-calendar look-ahead, construct exact `T+h` returns, and discard look-ahead-only rows.

Partitioned results must match a manageable unpartitioned reference run.

### 7. Reuse masks and transformed controls

Calculate shared ST/PT, suspension, tradability, label-availability, industry, size, winsorization, and standardization artifacts once per compatible scenario, period, and protocol.

### 8. Preserve categorical semantics

Industry must remain categorical. Acceptable implementations include categorical dtype, sparse per-date dummies, categorical fixed effects, or a proven equivalent transformation.

Arbitrary industry codes must never be treated as a continuous regressor.

### 9. Track transformation lineage

Record the paper field, physical source, materialized runtime field, applied transforms, and remaining transforms.

If `log_market_cap` is already materialized, the evaluator must not apply another log. Apply the same protection to winsorization, standardization, adjustment, and neutralization.

### 10. Make alignment compact

Normalize narrow key arrays, compare row counts and exact key equality, and use the verified positional fast path before constructing an outer merge.

Use compact indexes or partition anti-joins only when the keys differ.

### 11. Replace full-frame hashing

Construct data identity from source hashes, Parquet schema and row-group metadata, date/symbol boundaries, manifest versions, transformation hashes, and incremental partition hashes.

Do not copy and sort complete frames only to identify a run.

### 12. Make evaluators incremental

An evaluator should receive one factor and only its required columns. IC and regression should aggregate date-level statistics and release each date or partition instead of retaining the full transformed panel.

### 13. Add checkpoint and resume

Persist completed FactorFrame partitions, label partitions, evaluation partials, execution IDs, and resource telemetry.

After interruption, retry unfinished partitions instead of rerunning the entire paper period.

### 14. Separate resource adaptation from methodological deviation

Normally non-blocking and methodology-preserving:

- sequential scenarios;
- bounded date partitions with verified boundaries;
- column projection;
- cached masks and controls;
- incremental hashing;
- sequential evaluation;
- checkpoint/resume.

Must be reported as methodological deviations:

- shortening dates;
- reducing the security universe;
- converting categorical controls to continuous codes;
- dropping controls;
- changing horizons or adjustment views;
- changing missing-value behavior.

A diagnostic run may continue after a deviation, but comparability must be downgraded.

## Reporting Requirements

The report should state:

- requested and executed samples;
- requested and executed universes;
- scenario and partition strategies;
- measured peak memory;
- resource-triggered adaptations;
- methodology-preserving adaptations;
- methodological deviations;
- whether raw factor values were calculated before evaluation filters.

If an unpartitioned attempt is killed and a partitioned retry succeeds, report both without treating the interrupted attempt as a scientific failure.

## Implementation Order

1. Add resource estimates and execution-mode selection.
2. Execute one price scenario at a time.
3. Replace duplicate panels with one base panel and eligibility mask.
4. Add narrow column projection.
5. Persist partitioned FactorFrames.
6. Add verified warm-up and look-ahead partition execution.
7. Reuse masks and transformed controls.
8. Move the alignment fast-path check before outer joins.
9. Replace full-frame hashing.
10. Add checkpoints and resource telemetry.
11. Add categorical and duplicate-transform guards.
12. Reconcile requested versus executed methodology in reports.

## Implemented First Tranche

The canonical executor now provides:

- configurable memory preflight with standard/projected peak estimates;
- automatic `resource_bounded_projected` selection when projection fits the budget;
- explicit `partition_required` refusal before factor execution when projection does not fit;
- one logical base panel, shallow projected calculation/evaluation views, and one active scenario per context;
- required-column projection for factor calculation and each selected evaluator case;
- verified positional alignment before any merge and a single left join when keys differ;
- bounded incremental hashing, or metadata-derived identity when a source manifest is supplied;
- process peak-RSS telemetry and separate resource-adaptation/methodological-deviation reporting;
- sequential QFQ/HFQ loading guidance instead of retaining both full views by default.

Still pending are partitioned FactorFrame persistence, verified warm-up/look-ahead
partition execution, reusable mask/control caches, checkpoint/resume, duplicate-
transform lineage guards, and truly incremental per-date evaluator aggregation.

## Acceptance Criteria

The improvement is complete when:

1. A full paper period can execute within a configurable memory budget without shortening the sample.
2. Bounded and manageable unpartitioned factor calculations produce identical values.
3. Evaluation filters remain after raw factor calculation by default.
4. Calculation/evaluation separation does not duplicate full panels.
5. Only the active price scenario is normally resident.
6. Compatible cases reuse eligibility masks and transformed controls.
7. Categorical fields retain categorical semantics.
8. Materialized transforms cannot be applied twice.
9. Equal keys avoid a full outer merge.
10. Interrupted runs resume from completed partitions.
11. Resource adaptations and methodological deviations are reported separately.
12. OOM recovery cannot silently change dates, universes, controls, filters, or adjustment conventions.

## Non-Goals

This improvement does not:

- move evaluation filters into factor calculation by default;
- make large data blocking;
- require one fixed partition size;
- mandate one evaluator for all papers;
- treat missing inputs as explicit filters;
- permit performance optimizations to change methodology.
