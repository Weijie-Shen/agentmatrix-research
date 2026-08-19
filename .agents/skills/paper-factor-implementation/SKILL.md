---
name: paper-factor-implementation
description: Implement and test selected paper factors inside AgentMatrix Factor Lab after extraction and data gates pass. Use for Stages 4-5, implementation manifests, safe scaffolds, paper-family factor modules, operator semantics, FactorImplementationArtifact certification, and formula-focused TDD.
---

# Paper Factor Implementation

Implement paper-specific formulas inside the existing factor-family library. Do not build a universal formula compiler.

## Gate and manifest

Require validated extraction/spec artifacts and Stage 3 formula-input readiness. Run `build_implementation_manifest(...)` before coding. Preserve per-factor statuses and unresolved operators.

The manifest validates every `factor_calculation_contract/v1` and lists mandatory semantic assertion IDs. Do not code around a missing or invalid contract; return it to extraction. The certified implementation artifact must preserve the exact contract map and hash.

Use scaffolding only before hand-written implementation. `write_factor_family_scaffold(...)` can overwrite `factors.py`; never run it after implementation exists.

Keep unknown or paper-specific operators local to `research_core/factor_lab/libraries/<family>/`. Promote an operator to shared Factor Lab code only after paper-independent reuse and standalone tests.

## Implementation contract

Factor functions must:

- accept normalized panels; keep data loading outside;
- validate required columns and sorting;
- compute only requested factors when dispatch supports selection;
- return stable date/security keys plus numeric-or-null factor columns;
- preserve input row count unless the paper formula explicitly filters;
- replace positive and negative infinity with null at intermediate fragile operations and final output;
- avoid lookahead and preserve chronological semantics;
- keep calculation-universe logic separate from evaluation-universe masks.

For formulas mixing cross-sectional ranks and time-series operators, preserve operator order exactly. A typical safe pattern is long panel → cross-sectional operation by date → wide date/security rolling operation → cross-sectional post-transform → long output.

Keep source parameters and derived runtime constants distinct. Use a parameter in the exact unit and algebraic position stated by the paper; converting a lookback window to observations does not authorize replacing a separate month-valued decay parameter with that observation count. When a conversion is explicitly supported, document its dimensional rationale and provenance in the implementation artifact and test the converted value independently. Leave an unresolved unit/index mismatch as a formula limitation rather than choosing a convenient interpretation.

When a paper measures an operator distance in exchange trading days, advance the distance on the exchange calendar, including sessions where a security has no valid observation. Do not count only retained or non-null stock rows. Preserve a calendar/session index or the full per-security calendar grid through factor calculation, and test that a suspension or missing stock observation advances distance while a market holiday does not.

Use safe rolling correlation/covariance wrappers on sparse or low-variance panels. Scrub infinity immediately after the rolling operation so downstream ranks and sums do not propagate it.

## TDD sequence

For each factor or coherent factor group:

1. Write a failing semantics test.
2. Confirm it fails for the expected reason.
3. Implement the smallest correct formula.
4. Run the focused test.
5. Run the paper-family tests.
6. Run relevant paper-reproduction framework tests.

Test:

- module import and dispatcher behavior;
- missing required columns;
- stable sorting and row count;
- warm-up nulls and numeric output;
- absence of infinity;
- hand-computable formula semantics;
- source-parameter units and any independently derived conversion constants;
- rank direction and rolling window boundaries;
- adjusted-price view consistency for price-derived inputs;
- no accidental evaluation filtering during calculation.

For weighted formulas, use asymmetric weights and assert `weighted_mean_denominator_is_sum_of_weights`. For unit-sensitive formulas, assert `literal_source_parameter_units` against the source equation, not an implementation-derived constant. For natural-month windows, assert `natural_month_window_boundaries` with unequal month lengths. For rolling factors, assert `first_scoring_date_has_full_history`. Use the exact assertion IDs in test names or constants and in durable assertion coverage.

Do not tune formula code to make paper metrics closer. Formula correctness comes from evidence and semantic tests.
Do not build a test oracle by repeating the implementation's unsupported parameter conversion. For hand-computable tests, calculate expected values from the literal source equation and source-level parameter values so a wrong unit, scale, normalization, or index direction fails.

## Certification

Create and validate a `FactorImplementationArtifact` naming the final module, callable/dispatcher, implemented factors, required inputs, and probe evidence. An inline notebook/script column, an unimplemented scaffold, or a manifest alone does not complete Stage 4.

Run the artifact on a small probe panel and verify keys, columns, row count, numeric output, and finite values. Persist artifact and test paths in pipeline state.

## Parallel factor work

When multiple agents implement disjoint factor groups:

- assign non-overlapping modules or functions;
- share one evidence/spec baseline;
- prohibit shared-file edits without coordinator ownership;
- require focused tests per group;
- integrate through one coordinator and rerun the complete family suite.

## Required outputs

- implementation manifest;
- importable factor-family code;
- focused and family tests;
- certified `FactorImplementationArtifact`;
- Stage 4 and Stage 5 pipeline updates with exact test commands and outcomes.
