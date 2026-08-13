---
name: paper-factor-implementation
description: Implement and test selected paper factors inside AgentMatrix Factor Lab after extraction and data gates pass. Use for Stages 4-5, implementation manifests, safe scaffolds, paper-family factor modules, operator semantics, FactorImplementationArtifact certification, and formula-focused TDD.
---

# Paper Factor Implementation

Implement paper-specific formulas inside the existing factor-family library. Do not build a universal formula compiler.

## Gate and manifest

Require validated extraction/spec artifacts and Stage 3 formula-input readiness. Run `build_implementation_manifest(...)` before coding. Preserve per-factor statuses and unresolved operators.

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
- rank direction and rolling window boundaries;
- adjusted-price view consistency for price-derived inputs;
- no accidental evaluation filtering during calculation.

Do not tune formula code to make paper metrics closer. Formula correctness comes from evidence and semantic tests.

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
