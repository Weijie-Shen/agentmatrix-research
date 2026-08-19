---
name: paper-evidence-extraction
description: Extract selected quantitative factor definitions and paper-reported IC evidence into AgentMatrix shared-registry PaperExtraction artifacts, then normalize them into FactorResearchSpec records. Use for paper-reproduction Stages 1-2, extraction review, or correction of formula, provenance, truth-source, transform, and evaluation-case schemas.
---

# Paper Evidence Extraction

Produce faithful `paper_extraction.ic_recipe.v3` evidence artifacts for selected factors. Do not implement factor code in this stage. The v2 shared-registry and legacy factor-local schemas remain compatibility inputs; new extraction uses truth-source-owned declarative recipes.

## Read first

- `contracts/factor_research.py`
- `research_core/factor_lab/paper_reproduction/extraction.py`
- `research_core/factor_lab/paper_reproduction/normalization.py`
- every file in `references/`, especially `evaluation-recipe-schema.md`, `factor-calculation-contract.md`, the method catalogs, and `truth-source-selection.md`
- the relevant extraction and normalization schema tests, without reading prior paper-specific attempts during a fresh forward test

## Build formula registries and truth-source recipes

Keep immutable paper evidence separate from runtime decisions. Populate factor definitions, semantic requirements, metric definitions, and truth sources. Each truth source owns one homogeneous evaluation recipe and may cover many factors. Select exactly one source per factor in `factor_truth_selection`; never duplicate a recipe on every factor.

For every selected factor capture:

- canonical name and aliases only when supported;
- exact formula and narrow source location;
- formula-required raw fields and derived-field construction;
- parameters and windows;
- intrinsic factor frequency;
- formula, field-mapping, evaluation, and other ambiguities;
- its row in every relevant IC truth source's `reported_results` map.

Formula-required fields must be factor-specific. Do not copy a family-wide OHLCVW superset onto every factor.

Do not invent missing formula semantics. Classify material ambiguity and retain source text or location.

Record every formula source locator literally: page plus the visible table or figure title/number. When a paper-level known gap affects a formula, give it `scope: formula` and an `affects` list, then include the same `gap_id` in every affected factor's `formula_gap_ids`. Do not leave formula ambiguity only in paper-level notes where normalization and review cannot bind it to factors.

Preserve every formula parameter as a source-level symbol with its literal value, unit, and domain. Keep derived runtime quantities—such as an estimated number of trading observations in a month—in separate fields with explicit conversion provenance. Never substitute a derived observation count for a parameter stated in months, years, calendar days, or another unit merely because the rolling window is implemented with observations. If a formula combines variables whose units or indexing conventions are unclear, record a formula gap instead of silently making the expression dimensionally convenient.

Attach `factor_calculation_contract/v1` to every temporal, weighted, decay, or unit-sensitive formula. The extraction validator blocks risky formulas without it. Declare window method, literal parameters, weighted-mean normalization, distance semantics, required pre-sample history, and semantic test IDs as specified in `references/factor-calculation-contract.md`.

If the selected paper reports a factor only as a comparison row and cites a companion paper for its formula, do not treat the row as formula evidence. Locate the cited source only within the user's authorized paper set, record its path and SHA-256 identity as formula provenance, and keep the selected paper as the evaluation-truth source. If the cited source is unavailable, leave formula fidelity unverified.

Semantic requirements describe paper meaning only. They may specify industry provider/version/level/effective-date rule, capitalization basis, status meaning, timing, or construction, but must never contain a selected local column, physical file, or resolved field. Stage 3 owns those bindings.

## Model IC analysis truth narrowly

The canonical evaluator type is only `ic_analysis`. Rank-IC mean, ICIR, IC standard deviation, and positive-ratio measures are metrics within that evaluator type, not separate evaluator cases. Define formulas and units once in `metric_definitions`; encode rank/return/alignment semantics in each truth-source recipe using catalog method IDs.

Split truth sources whenever the semantic protocol differs: sample, horizon, return alignment, universe, ordered preprocessing, neutralization controls, control timing, or other IC inputs. Do not split a table merely because it reports several IC metrics together. A table block under one protocol is one truth source and lists every reported metric ID; its `reported_results` map stores the values for all factors printed in that block.

Each source should contain:

- stable `truth_source_id` and one `evaluation_recipe`;
- one narrow table/figure/row-block source location;
- all `reported_metric_ids` printed together for that block;
- factor-keyed `reported_results`, with normalized values and original labels/units retained as provenance;
- optional notes and extraction gaps;
- no local-data binding; selection is only the factor-to-source ID map.

For reported count ratios or percentages, test whether multiple rows imply one unique integer observation denominator at the printed precision. Record that inferred denominator and compare it with the stated sample dates/schedule. If they disagree, preserve an explicit paper-evidence gap or conflict; do not silently let execution coverage choose the denominator.

Keep paper protocol immutable. Do not rewrite WLS as OLS, a paper sample as local coverage, or an unavailable field as a proxy during extraction.
Encode the paper's return interval semantically. “Following whole natural month” is a natural-month horizon, not a conventional 20/21-trading-day approximation.
Read `references/return-label-method-catalog.md` before encoding any return label. Treat `T+1` as the next declared evaluation period until nearby evidence establishes a trading-day, exchange-calendar, natural-month, or fixed-date interval. Run recipe validation before normalization; a missing typed interval or a monthly-`T+1`/one-day contradiction is blocking extraction evidence, not a Stage-3 guess.

Extract the result blocks needed to support the Stage-1 selection and preserve relevant alternatives only when they provide necessary provenance or expose a paper conflict. Apply `truth-source-selection.md` during extraction. Stage 3 assesses the selected source's support and Stage 6 executes it; neither stage reselects truth.

Normalize metric names and units to the framework's computational convention while retaining the original paper label/unit as provenance. For example, a percentage IC mean must be represented consistently with the evaluator's decimal output; do not compare `6.29` directly with `0.0629` or invent incompatible metric keys. Extract whether IC is ordinary Pearson correlation or Spearman/rank correlation; never infer rank IC merely from the label `IC`. Preserve signed-versus-absolute conventions for IR and other derived metrics in their definitions.

Missing daily factor values or curves are limitations, not blockers, when aggregate evaluation metrics and a meaningful method exist. Aggregate-only family evidence must not be fabricated into per-factor metrics.

## Extract transforms and controls

Define one ordered preprocessing list on each truth-source recipe and preserve operations on:

- factor exposure;
- neutralization and regression controls;
- regression weights;
- return labels and evaluation inputs;
- output residuals or standardized exposures.

For each operation record method, parameters, scope, source (`explicit`, `inferred`, `default_assumed`, or `not_specified`), source location, and confidence. Distinguish explicit `none` from unknown. Apply a workflow default only where the project explicitly defines a safe default, and retain original provenance.

For every industry control, extract the taxonomy/provider, taxonomy version where stated, classification level, and timing date. Preserve unresolved wording rather than reducing it to a generic `industry` field. For every capitalization control or weight, distinguish total, A-share, circulating-A, and free-float capitalization and preserve any log, square-root, winsorization, or standardization operation separately.

For financial inputs, extract the exact statement field/definition, report-period convention, announcement timing, original/restated policy, and whether a flow is fiscal-year-to-date, standalone quarter, or TTM. For benchmark or risk-free inputs, extract the exact identifier, constituent timing, monthly/daily weight convention, return horizon/calendar, yield-curve tenor, rate unit, and conversion rule. Preserve unspecified details as ambiguity rather than choosing a convenient local default.

Every recipe references the project-level `china_a_share_ic_evaluation_v1` policy. Do not extract its ST/PT and next-trading-day suspension masks as if they were paper preprocessing. The runtime always calculates the factor on full valid history, aligns evaluation inputs, applies this global policy first, and only then executes the truth-source recipe. Preserve paper differences as deviations.

## Validate and normalize

Run extraction validation before normalization. Reject duplicate IDs, dangling references, missing formulas/semantic fields, mismatched covered-factor/result rows, mismatched truth metrics/results, unknown method IDs, non-contiguous preprocessing order, invalid factor truth selections, and runtime bindings. A source row block must be homogeneous; split heterogeneous blocks. Preserve unresolved contradictory evidence as an extraction gap and require review before selection.

Normalize as a preservation mapping into `FactorResearchSpec`:

- keep formulas, semantic IDs, parameters, frequency, provenance, the selected truth-source recipe, limitations, and ambiguity categories;
- set formula and field mapping validation targets;
- preserve the ordered recipe without flattening neutralization into a separate bucket;
- populate exactly one `selected_truth_sources` entry from Stage-1 `factor_truth_selection`;
- record Stage 3 as recipe/data-state resolution and Stage 6 as execution, not selection;
- never invent default transforms;
- preserve every explicit missing-value operation and its position, including zero-fill after cross-sectional standardization;
- never add paper factor-value truth targets.

Export and reload artifacts to verify serialization. Generated `specs.py` must import cleanly.

## Required outputs

- `runtime/factor_lab/paper_specs/<paper_id>_extracted.json`
- `runtime/factor_lab/specs/<family>_specs.json`
- `runtime/factor_lab/catalogs/<family>_catalog.json`
- `research_core/factor_lab/libraries/<family>/specs.py` when generated
- Stage 1-2 pipeline updates with diagnostics and limitations
- every pipeline-cited source manifest under `runtime/factor_lab/source_evidence/`; never cite an artifact that is not persisted
