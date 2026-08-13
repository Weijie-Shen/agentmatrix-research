---
name: paper-evidence-extraction
description: Extract selected quantitative factor definitions and paper-reported evaluation evidence into AgentMatrix PaperExtraction artifacts, then normalize them into FactorResearchSpec records. Use for paper-reproduction Stages 1-2, extraction review, golden-benchmark comparison, or correction of formula, provenance, truth-source, transform, and evaluation-case schemas.
---

# Paper Evidence Extraction

Produce faithful evidence artifacts for selected factors. Do not implement factor code in this stage.

## Read first

- `contracts/factor_research.py`
- `research_core/factor_lab/paper_reproduction/extraction.py`
- `research_core/factor_lab/paper_reproduction/normalization.py`
- the relevant golden JSON schema tests, without reading a paper-specific golden answer during a fresh forward test

## Extract paper metadata

Keep paper-level metadata lean: ID, title, authors, source, year, family, selected factors, extraction scope, and notes. Put factor-varying method details on factors or their evaluation cases.

For every selected factor capture:

- canonical name and aliases only when supported;
- exact formula and narrow source location;
- formula-required raw fields and derived-field construction;
- parameters and windows;
- intrinsic frequency, universe, and sample period;
- formula, field-mapping, evaluation, and other ambiguities;
- all relevant paper-reported evaluation cases.

Formula-required fields must be factor-specific. Do not copy a family-wide OHLCVW superset onto every factor.

Do not invent missing formula semantics. Classify material ambiguity and retain source text or location.

## Model evaluation truth narrowly

Every truth source must use `truth_type = evaluation_results`. Split sources when table, figure, metric family, horizon, sample, transform, neutralization, controls, weights, portfolio construction, fee, execution price, or benchmark differs.

Each source should contain:

- stable `truth_id`;
- `evaluation_family` and method text;
- structured `evaluation_spec`;
- ordered `transform_spec`;
- semantic `required_data` grouped by formula, evaluation, controls, weights, filters, and labels where useful;
- reported metrics with units and sign conventions;
- one narrow `source_location`;
- sample/universe details when case-specific.

Keep paper protocol immutable. Do not rewrite WLS as OLS, a paper sample as local coverage, or an unavailable field as a proxy during extraction.

Extract alternative reported protocols when they carry numeric truth, including unneutralized versus neutralized, different horizons, and distinct IC/regression/portfolio tables. Do not extract only the most data-intensive variant when the paper reports a less-dependent case that can provide valid primary evidence. Selection happens after data support is assessed.

Normalize metric names and units to the framework's computational convention while retaining the original paper label/unit as provenance. For example, a percentage IC mean must be represented consistently with the evaluator's decimal output; do not compare `6.29` directly with `0.0629` or invent incompatible metric keys.

Missing daily factor values or curves are limitations, not blockers, when aggregate evaluation metrics and a meaningful method exist. Aggregate-only family evidence must not be fabricated into per-factor metrics.

## Extract transforms and controls

Preserve ordered operations on:

- factor exposure;
- neutralization and regression controls;
- regression weights;
- return labels and evaluation inputs;
- output residuals or standardized exposures.

For each operation record method, parameters, scope, source (`explicit`, `inferred`, `default_assumed`, or `not_specified`), source location, and confidence. Distinguish explicit `none` from unknown. Apply a workflow default only where the project explicitly defines a safe default, and retain original provenance.

For every industry control, extract the taxonomy/provider, taxonomy version where stated, classification level, and timing date. Preserve unresolved wording rather than reducing it to a generic `industry` field. For every capitalization control or weight, distinguish total, A-share, circulating-A, and free-float capitalization and preserve any log, square-root, winsorization, or standardization operation separately.

For financial inputs, extract the exact statement field/definition, report-period convention, announcement timing, original/restated policy, and whether a flow is fiscal-year-to-date, standalone quarter, or TTM. For benchmark or risk-free inputs, extract the exact identifier, constituent timing, monthly/daily weight convention, return horizon/calendar, yield-curve tenor, rate unit, and conversion rule. Preserve unspecified details as ambiguity rather than choosing a convenient local default.

For Chinese all-A-share language without a more specific pool, record the project default as an assumption rather than paper text: all A-shares excluding ST/PT and securities suspended on the next evaluation trading day.

## Validate and normalize

Run extraction validation before normalization. Reject duplicate truth IDs, missing formulas/fields, invalid selected truth IDs, and non-evaluation truth. Require human review for material formula ambiguity, absent evaluation truth, or unresolved selection among comparable sources.

Normalize as a preservation mapping into `FactorResearchSpec`:

- keep formulas, fields, parameters, frequency, provenance, truth sources, selected IDs, limitations, and ambiguity categories;
- set formula and field mapping validation targets;
- add paper evaluation metric matching only when selected evaluation truth exists;
- never add paper factor-value truth targets.

Export and reload artifacts to verify serialization. Generated `specs.py` must import cleanly.

## Required outputs

- `runtime/factor_lab/paper_specs/<paper_id>_extracted.json`
- `runtime/factor_lab/specs/<family>_specs.json`
- `runtime/factor_lab/catalogs/<family>_catalog.json`
- `research_core/factor_lab/libraries/<family>/specs.py` when generated
- Stage 1-2 pipeline updates with diagnostics and limitations
