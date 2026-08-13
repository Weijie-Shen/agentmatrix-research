---
name: paper-evidence-extraction
description: Extract selected quantitative factor definitions and paper-reported IC evidence into AgentMatrix shared-registry PaperExtraction artifacts, then normalize them into FactorResearchSpec records. Use for paper-reproduction Stages 1-2, extraction review, golden-benchmark comparison, or correction of formula, provenance, truth-source, transform, and evaluation-case schemas.
---

# Paper Evidence Extraction

Produce faithful `paper_extraction.ic_analysis.v2` evidence artifacts for selected factors. Do not implement factor code in this stage. The legacy factor-local schema may be loaded for old jobs, but new extraction must use the shared-registry IC-analysis schema.

## Read first

- `contracts/factor_research.py`
- `research_core/factor_lab/paper_reproduction/extraction.py`
- `research_core/factor_lab/paper_reproduction/normalization.py`
- the relevant golden JSON schema tests, without reading a paper-specific golden answer during a fresh forward test

## Build the shared evidence registries

Keep immutable paper evidence separate from runtime decisions. Populate paper-level registries for factor definitions, semantic requirements, universe protocols, sample periods, ordered operation pipelines, IC protocols, metric definitions, and truth sources. Use stable IDs and references rather than copying the same method block onto every factor.

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

If the selected paper reports a factor only as a comparison row and cites a companion paper for its formula, do not treat the row as formula evidence. Locate the cited source only within the user's authorized paper set, record its path and SHA-256 identity as formula provenance, and keep the selected paper as the evaluation-truth source. If the cited source is unavailable, leave formula fidelity unverified.

Semantic requirements describe paper meaning only. They may specify industry provider/version/level/effective-date rule, capitalization basis, status meaning, timing, or construction, but must never contain a selected local column, physical file, or resolved field. Stage 3 owns those bindings.

## Model IC analysis truth narrowly

The canonical evaluator type is only `ic_analysis`. Rank-IC mean, ICIR, IC standard deviation, and positive-ratio measures are metrics within that evaluator type, not separate evaluator cases. Define their general formulas and units once in `metric_definitions` and the generic rank/return/alignment contract once in `ic_analysis_contract`.

Split truth sources whenever the semantic protocol differs: sample, horizon, return alignment, universe, ordered preprocessing, neutralization controls, control timing, or other IC inputs. Do not split a table merely because it reports several IC metrics together. A table block under one protocol is one truth source and lists every reported metric ID; its `reported_results` map stores the values for all factors printed in that block.

Each source should contain:

- stable `truth_source_id` and one `protocol_id`;
- one narrow table/figure/row-block source location;
- all `reported_metric_ids` printed together for that block;
- factor-keyed `reported_results`, with normalized values and original labels/units retained as provenance;
- optional conflict group and notes;
- no runtime selection or local-data binding.

For reported count ratios or percentages, test whether multiple rows imply one unique integer observation denominator at the printed precision. Record that inferred denominator and compare it with the stated sample dates/schedule. If they disagree, preserve an explicit paper-evidence gap or conflict; do not silently let execution coverage choose the denominator.

Keep paper protocol immutable. Do not rewrite WLS as OLS, a paper sample as local coverage, or an unavailable field as a proxy during extraction.
Encode the paper's return interval semantically. “Following whole natural month” is a natural-month horizon, not a conventional 20/21-trading-day approximation.

Extract all relevant IC alternatives, including raw versus neutralized, different preprocessing for different factor groups, different horizons, and different samples. Do not extract only the most data-intensive variant when a raw IC case also carries valid numeric truth. Stage 3 assesses local semantic/data support and Stage 6 selects exactly one unconflicted truth source per factor without looking at metric closeness.

Normalize metric names and units to the framework's computational convention while retaining the original paper label/unit as provenance. For example, a percentage IC mean must be represented consistently with the evaluator's decimal output; do not compare `6.29` directly with `0.0629` or invent incompatible metric keys. Extract whether IC is ordinary Pearson correlation or Spearman/rank correlation; never infer rank IC merely from the label `IC`. Preserve signed-versus-absolute conventions for IR and other derived metrics in their definitions.

Missing daily factor values or curves are limitations, not blockers, when aggregate evaluation metrics and a meaningful method exist. Aggregate-only family evidence must not be fabricated into per-factor metrics.

## Extract transforms and controls

Define each reusable operation pipeline once and preserve ordered operations on:

- factor exposure;
- neutralization and regression controls;
- regression weights;
- return labels and evaluation inputs;
- output residuals or standardized exposures.

For each operation record method, parameters, scope, source (`explicit`, `inferred`, `default_assumed`, or `not_specified`), source location, and confidence. Distinguish explicit `none` from unknown. Apply a workflow default only where the project explicitly defines a safe default, and retain original provenance.

For every industry control, extract the taxonomy/provider, taxonomy version where stated, classification level, and timing date. Preserve unresolved wording rather than reducing it to a generic `industry` field. For every capitalization control or weight, distinguish total, A-share, circulating-A, and free-float capitalization and preserve any log, square-root, winsorization, or standardization operation separately.

For financial inputs, extract the exact statement field/definition, report-period convention, announcement timing, original/restated policy, and whether a flow is fiscal-year-to-date, standalone quarter, or TTM. For benchmark or risk-free inputs, extract the exact identifier, constituent timing, monthly/daily weight convention, return horizon/calendar, yield-curve tenor, rate unit, and conversion rule. Preserve unspecified details as ambiguity rather than choosing a convenient local default.

Universe protocols must contain distinct `calculation_universe` and `evaluation_universe` objects. A filter records its application stage and effective date. ST/PT and next-evaluation-day suspension exclusions are normally evaluation-eligibility filters: retain full valid security history for factor calculation, compute the factor first, then apply those masks to the factor/return cross-section. Only place a filter in calculation history when the paper explicitly defines it there.

For Chinese all-A-share language without a more specific pool, record the project default as an assumption rather than paper text: all A-shares excluding ST/PT and securities suspended on the next evaluation trading day. Preserve the exact status semantics and dates as semantic requirements; Stage 3 resolves local fields.

## Validate and normalize

Run extraction validation before normalization. Reject duplicate registry IDs, dangling references, missing formulas/semantic fields, non-IC evaluator types, mismatched truth metrics/results, runtime bindings, and filters that use future status during rolling factor calculation. Preserve unresolved contradictory paper result blocks as explicit conflict groups; conflicted cases remain in the denominator but cannot be exact-match truth until resolved.

Normalize as a preservation mapping into `FactorResearchSpec`:

- keep formulas, semantic IDs, parameters, frequency, provenance, shared evidence references, candidate truth sources, limitations, and ambiguity categories;
- set formula and field mapping validation targets;
- compile ordered operation pipelines into runtime transform/control structures without changing the immutable registries;
- leave `selected_truth_sources` empty, record Stage 3 as support assessment, and Stage 6 as the selection stage;
- never invent default transforms while compiling v2;
- preserve every explicit missing-value operation and its position, including zero-fill after cross-sectional standardization;
- never add paper factor-value truth targets.

Export and reload artifacts to verify serialization. Generated `specs.py` must import cleanly.

## Required outputs

- `runtime/factor_lab/paper_specs/<paper_id>_extracted.json`
- `runtime/factor_lab/specs/<family>_specs.json`
- `runtime/factor_lab/catalogs/<family>_catalog.json`
- `research_core/factor_lab/libraries/<family>/specs.py` when generated
- Stage 1-2 pipeline updates with diagnostics and limitations
