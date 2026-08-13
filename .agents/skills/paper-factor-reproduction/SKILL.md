---
name: paper-factor-reproduction
description: Coordinate end-to-end reproduction of quantitative factors from research papers in AgentMatrix Factor Lab. Use when Codex must extract selected paper factors, normalize specs, validate and resolve data, implement and test factor code, execute paper-aware evaluations, compare paper-reported evaluation truth, and produce an auditable final report. Also use when resuming or reviewing an existing paper-reproduction job.
---

# Paper Factor Reproduction

Coordinate the repository's existing Factor Lab workflow. Do not create a parallel framework.

## Start correctly

1. Work from the repository root.
2. Read `docs/PAPER_FACTOR_REPRODUCTION_PROJECT.md` and the public APIs in `research_core/factor_lab/paper_reproduction/`.
3. Identify the paper, selected factor scope, paper test window, available data roots, and output job ID.
4. Create or load one persistent `PaperReproductionPipelineState`. Treat it as the only authority for gate status.
5. Keep paper evidence immutable. Put runtime substitutions and degradation in separate resolved records.

Use paper-reported `evaluation_results` as paper truth. Do not add paper factor-value truth matching.

## Route work to stage skills

Read the matching repository skill before performing each stage:

- Stages 1-2: `.agents/skills/paper-evidence-extraction/SKILL.md`
- Stage 3: `.agents/skills/paper-factor-data-readiness/SKILL.md`
- Stages 4-5: `.agents/skills/paper-factor-implementation/SKILL.md`
- Stages 6-7: `.agents/skills/paper-factor-evaluation/SKILL.md`
- Stage 8 and final audit: `.agents/skills/paper-reproduction-review/SKILL.md`

Do not load every detailed reference up front. Load only the stage skill and repository files needed for the current gate.

## Required gates

Run stages in this order:

1. `paper_extraction`
2. `spec_normalization`
3. `input_dataframe_validation`
4. `factor_implementation`
5. `implementation_tests`
6. `evaluation`
7. `paper_truth_validation`
8. `final_report`

Before a stage, call `execution_decision(stage_name)`. After it, persist its artifacts, diagnostics, limitations, execution status, and truth status where applicable. Load and merge the existing job state; never reconstruct earlier stages from memory.

Execution statuses are `pending`, `running`, `completed`, `completed_with_limitations`, and `failed`. Truth statuses are `exact_match`, `approximately_consistent`, `directionally_consistent`, `inconclusive_due_to_protocol_gap`, `inconsistent`, and `not_evaluated`.

Only a genuine hard failure may stop dependent work. Missing evaluation-only fields, unsupported secondary evaluators, proxy controls, partial source coverage, and protocol differences normally produce structured deviations and `completed_with_limitations`, not an abandoned run.

## Multi-agent operating model

When subagents are available, act as coordinator and keep final integration responsibility:

- Give each worker a bounded artifact contract, its stage skill path, the paper path, selected factors, and working directory.
- Do not provide a golden answer, suspected defect, or prior attempt's conclusions to a fresh validation worker.
- Parallelize only independent factor groups or an implementation task and a read-only review task. Do not let multiple workers edit the same files.
- Require workers to return paths, commands run, test outcomes, and unresolved limitations.
- Inspect every worker artifact before advancing pipeline state. A worker's claim is not gate evidence.
- Keep one coordinator responsible for pipeline state, resolved evaluation-case selection, final truth denominators, and the report.

For a clean forward test, start from a fresh branch/worktree and bundle or point to the exact repository skill revision. Do not let artifacts from prior attempts remain discoverable.

After interruption or resource termination, inventory persisted stage and scenario artifacts before deciding what remains incomplete. Reload and merge every valid completed evaluation bundle. Never replace successful durable execution records with a blanket deferred result because a later scenario, partition, report build, or process failed.

## Cross-paper invariants

- Keep raw factor definitions separate from transforms, universes, return horizons, controls, weights, portfolio rules, and evaluation data.
- Preserve narrow source locations and provenance for formulas, transforms, methods, and metrics.
- Distinguish exact data, constructed equivalents, proxies, rejected substitutes, and missing requirements.
- Resolve capitalization basis from paper wording; never conflate total, A-share, circulating-A, and free-float capitalization or rescale them with price-adjustment multipliers.
- Resolve point-in-time industry controls by paper taxonomy source, level, and evaluation/formation date. Never silently select among `sws`, `citics`, `citics_2019`, and `gildata`, and never use numeric industry codes as continuous values.
- Apply financial-statement announcement cutoffs before version selection. Preserve restatement policy and fiscal-year-to-date versus standalone-quarter semantics.
- Resolve exact benchmark/index identifiers, constituent effective dates, monthly-versus-daily weight convention, exchange-calendar horizons, and government-curve tenor. Never substitute a current universe, another index, another weight family, or another tenor silently.
- Keep stock price adjustment isolated from capitalization, statements, valuation ratios, benchmark levels, index weights, and rates.
- Never shorten the requested sample, reduce the universe, drop controls, or recode categorical controls only to fit resources.
- Compute forward returns with forward alignment. Keep the factor-calculation panel separate from evaluation filtering.
- Run QFQ and HFQ as independent price-view scenarios when price adjustment is relevant; never mix views in one run.
- Never retain multiple full price-view panels. Profile and release each view during Stage 3; during Stage 6 reload, execute, persist, and release one view before loading the next.
- A resource deferral must come from the actual requested panel under a genuine runtime budget. A probe frame paired with full-period metadata or a deliberately tiny budget is invalid evidence.
- Use persistent command sessions for long evaluations and poll the same process to exit. Tool-call yield boundaries are not process failures and must not trigger a restart or deferral.
- Keep paper-local helpers and evaluators inside the paper family until reuse and tests justify promotion.
- Never claim full reproduction when comparison is proxy-grade, direction-only, inconclusive, or not evaluated.

## Completion contract

The run is complete only when:

- all selected factors have exported extraction and normalized specs;
- formula-required data passed validation or has an explicit hard blocker;
- implemented factors are backed by importable `FactorImplementationArtifact` records and passing implementation tests;
- every selected evaluation case has a lifecycle outcome and selected executable cases ran through the framework executor;
- every selected factor has at least one durable `executed` evaluation record for an automated reproduction-success verdict; deferred records document limitations but do not satisfy execution completion;
- paper truth matching uses only eligible metrics and correct denominators;
- all eight pipeline stages have persisted outcomes;
- both JSON and Markdown final reports exist and accurately state implementations, deviations, tests, comparisons, and unresolved gaps.

A report that merely describes planned work is not completion. An unimplemented scaffold is not a factor implementation. Inline factor columns without a certified module/callable are not implementation completion.

## Essential repository entry points

- `research_core/factor_lab/paper_reproduction/extraction.py`
- `research_core/factor_lab/paper_reproduction/normalization.py`
- `research_core/factor_lab/paper_reproduction/data_validation.py`
- `research_core/factor_lab/paper_reproduction/implementation.py`
- `research_core/factor_lab/paper_reproduction/evaluators.py`
- `research_core/factor_lab/paper_reproduction/paper_evaluation.py`
- `research_core/factor_lab/paper_reproduction/truth_matching.py`
- `research_core/factor_lab/paper_reproduction/pipeline.py`
- `research_core/factor_lab/paper_reproduction/reporting.py`
- `research_core/factor_lab/paper_reproduction/agent_harness.py`
