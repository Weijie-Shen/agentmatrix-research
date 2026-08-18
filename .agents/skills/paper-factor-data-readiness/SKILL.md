---
name: paper-factor-data-readiness
description: Profile, resolve, construct, and validate data for AgentMatrix paper-factor reproduction. Use for Stage 3 input validation, semantic field resolution, local recommended-data loading, point-in-time financials, valuations, industry and capitalization selection, benchmark/universe/weight/calendar/yield inputs, price-adjustment scenarios, resource preflight, proxy assessment, and evaluation-case data-support scoring.
---

# Paper Factor Data Readiness

Validate formula computation separately from evaluation support. A missing evaluation-only field must not block a valid factor implementation.

## Source priority

1. Use an explicit user-provided artifact when suitable.
2. Use `/Users/mac/recommended_data_v2` through repository loaders.
3. For reference/evaluation data outside local coverage, use `.agents/skills/rqdata-fetch-reference/SKILL.md` without persistence.
4. Use Quant API v2 only when local canonical data and the applicable reference path cannot satisfy the requirement.
5. Mark a hard data blocker only after applicable sources and supported constructions fail.

Never expose or persist data tokens.

Read `/Users/mac/recommended_data_v2/README.md` and its linked dataset note before using a refreshed local bundle. Treat the documented loader and point-in-time join semantics as authoritative; do not keep using deleted legacy filenames because an older project document mentions them.

Read [recommended-data-contracts.md](references/recommended-data-contracts.md) when the paper uses financial statements, valuations, dividends, benchmarks, index membership/weights, trading-calendar horizons, or risk-free rates.

For daily price panels use repository loading APIs, not hand-selected physical-file joins. Load one price view at a time, persist its outputs, release it, then load the next:

- QFQ anchored at the paper test end;
- HFQ anchored at the source's initial cumulative-factor baseline.

Apply the same view multiplier to price-like fields including OHLC and VWAP. Leave volume and amount unadjusted. Require real price observations for price calculations and do not forward-fill status-only rows.

Capitalization fields use the unadjusted price basis and must not receive QFQ/HFQ multipliers. Resolve the paper wording before loading:

- generic market capitalization or `市值`: `market_cap` backed by `market_cap_3`, with ambiguity disclosed when the paper is vague;
- A-share capitalization: `a_share_market_cap`;
- circulating-A capitalization or `流通市值`: `circulating_market_cap`;
- free-float capitalization or `自由流通市值`: `free_float_market_cap`.

These are distinct semantics, not aliases. Request only needed fields with `market_cap_fields=(...)`. Preserve the free-float derivation and provider quality caveats in the data profile; apply log, square root, winsorization, and standardization later as explicit evaluation transforms.

For industry controls, resolve both taxonomy source and level from paper evidence before loading. Use `IndustryClassificationSelection(source, level)` with supported sources `sws`, `citics`, `citics_2019`, or `gildata`. Do not infer a taxonomy from the generic word “industry”, relabel `sws` as SWS 2021, or substitute a present-day snapshot. Resolve membership at the evaluation or formation date with `start_date <= date < cancel_date`; keep missing memberships missing and treat industry codes as categorical values. Use taxonomy snapshots when historically accurate names or parent relationships matter.

## Build semantic requirements

Consume the Stage-1 `semantic_requirements` registry and the Stage-2 factor/truth-source projections. Resolve each semantic ID to local data once per data scenario, then reuse that relationship across every candidate protocol that references it. Never write a resolved column or selected truth ID back into the immutable extraction.

Persist one authoritative `semantic_bindings` registry per data profile. Each selected entry records `semantic_input`, `physical_field`, relationship class, selection mode, and source. `field_relationships` are candidates and lineage, not competing selected bindings. Generate the support assessment, resolved recipe, preflight projection, and evaluator inputs from the authoritative registry. If any two persisted selected-binding locations disagree, block Stage 3; do not let a later component choose among them.

Translate paper fields into semantic roles before choosing physical columns. Record:

- paper name and definition;
- stage and affected evaluation cases/metrics;
- temporal and point-in-time requirements;
- construction formula if derived;
- exactness requirement;
- acceptable and rejected relationships.

For capitalization record the selected basis, physical source field, unit, unadjusted price basis, any construction, and transform timing. For industry record paper wording, resolved source, level, effective-date rule, membership file, taxonomy file, and whether the selection is exact, inferred, proxy, or unsupported.

Treat industry source/version/level and capitalization basis as typed semantics. For example, SWS and CITIC/CITICS are different relationships, as are total-company, A-share, circulating-A, and free-float capitalization. The fact that a generic `industry` or `market_cap` column exists does not satisfy a differently specified requirement.

Classify each relationship as `exact_alias`, `derived_equivalent`, `proxy_substitute`, or `unsupported_substitute`. Never materialize a proxy as an exact alias.

Assess each requirement as `exactly_available`, `constructible`, `available_with_missingness`, `replacement_available`, `missing`, or `not_assessed`. Include coverage, missingness, selected field, construction or replacement, methodological effect, comparability impact, and blocking decision.

## Validate formula inputs

Build `DataFrameValidationRequest.from_factor(factor)` and run `validate_input_frame(...)` on the normalized calculation panel.

Check:

- parseable `date` and stable security key;
- formula-required fields;
- unique date/security rows;
- explicit sorting by security/date;
- sufficient per-security history for windows;
- numeric compatibility and observation flags;
- derived fields materialized before certification.

Stop implementation only for unavailable formula-required inputs, invalid panel keys/history that cannot be repaired safely, or unresolved field semantics that change the formula.

## Profile evaluation support

Use `build_data_profile(...)`, `assess_evaluation_case_support(...)`, and `resolve_recipe_value_states(...)` for the Stage-1 selected truth source. Stage 3 determines executability, comparability, semantic bindings, and transform execution modes; it never changes `factor_truth_selection`.

Persist one authoritative assessment and resolved recipe for every selected factor/source pair. If the selected source is unsupported, report that limitation or blocker rather than switching to another result block.

Certify a `stage3_executable_evaluation_contract/v1` before marking a selected case executable. Require every resolved physical field to exist in the profiled panel, every accepted replacement to appear identically in the resolved recipe, all value-state modes to be executable, and the typed return interval to be internally consistent with the signal schedule. Persist the contract, required physical fields, binding registry, assessment ID, and blocking errors. A missing or blocked contract makes Stage 3 incomplete.

For every bound evaluation input record `physical_field`, `semantic_concept`, unit, price basis, `value_space`, `transform_chain`, temporal semantics, and lineage. Mark every recipe transform `apply`, `reuse_materialized`, `blocked_unknown_state`, or `incompatible`. Keep the requested paper operation even when a materialized value is reused. Never log a field whose state already contains `transform.natural_log`.

Before building the profile used for evaluation planning, materialize runtime labels required by the candidate cases. For ordinary trading-observation horizons use `materialize_forward_return(...)`, then record the derived field and lineage in the profile. Prose such as “20-day forward return” or a raw `close` field is not an executable `return_col`.

When the paper defines `T+h` in market trading days, load the exchange calendar with `load_recommended_trading_calendar(...)` including the required look-ahead and use `materialize_calendar_forward_return(...)`. Do not approximate an exchange-calendar horizon with each security's next surviving observations.

When the paper defines the following whole natural month, use `materialize_natural_month_forward_return(...)` with the exchange calendar so the target is that month's last trading day. Do not replace a natural-month interval with 20 or 21 trading observations. Persist the target-date rule and any missing target prices in label lineage.

Dispatch label materialization from the extracted typed interval. Do not reinterpret `next_evaluation_period` as a trading day merely because its horizon value is one. If its schedule-to-target rule remains ambiguous, stop at Stage 3 and return the ambiguity to extraction review.

Evaluation-only gaps include forward-return labels, controls, weights, industry, market cap, benchmark, historical index membership, index-weight convention, risk-free rate/tenor, execution price, ST/PT, suspension, and future-tradability masks. Record them as selected-case limitations, replacements, or unsupported requirements.

For point-in-time financial fields, enforce the paper evaluation date as the announcement cutoff before choosing a filing version. Record fields, cutoff, version policy, flow/stock semantics, and any standalone-quarter derivation. For valuations and dividends, preserve provider-versus-paper definitions and units.

Resolve exact benchmark/index identifiers. Keep monthly weights, reconstructed daily weights, and constituents distinct. Join by effective date, not provider ingestion time; never use the latest membership retrospectively. Select yield-curve tenor explicitly and preserve the annual decimal unit until a documented conversion is applied.

Compute rolling factor values before joining capitalization or interval-resolving industry unless the paper explicitly makes them part of factor calculation or the calculation universe. Join capitalization on security/date and industry at the declared evaluation or formation date. A physically present `industry` or `market_cap` column is not semantic proof: attach explicit `FieldRelationship` records when the paper taxonomy or capitalization basis is matched or differs.

Keep the full calculation panel separate from filtered evaluation inputs. Materialize rolling factors on retained valid security history, then join the factor by unique date/security keys to the evaluation panel. The mandatory global policy excludes ST/PT at signal date and next-exchange-day suspended securities after alignment and before recipe preprocessing. Do not filter factor history with these masks.

## Resource integrity

For full-period execution:

- project required columns only;
- estimate memory and runtime before loading;
- hash inputs incrementally;
- run scenarios and evaluation cases sequentially;
- use verified partitions when supported;
- never silently shorten dates, reduce universe, drop controls, or change encodings to fit resources.

Resource limitations may defer a case, but they cannot mutate paper protocol.

## Required outputs

- formula input validation reports;
- reusable data profiles;
- semantic requirement and relationship assessments;
- capitalization-basis and point-in-time industry-selection lineage;
- financial cutoff/version lineage and valuation/dividend units where applicable;
- benchmark identifiers, constituent/weight family, calendar-horizon, and yield-tenor lineage where applicable;
- QFQ/HFQ scenario metadata where applicable;
- evaluation-case support assessments;
- one explicit local relationship per referenced semantic requirement, including status-mask timing;
- Stage 3 pipeline update with blockers, deviations, and limitations.
