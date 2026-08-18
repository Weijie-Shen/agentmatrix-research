---
name: paper-reproduction-review
description: Audit AgentMatrix paper-factor reproduction artifacts and produce or validate the final report. Use for Stage 8, independent completeness review, pipeline-state reconciliation, artifact and test verification, truth-denominator checks, claim calibration, and deciding whether a fresh-agent reproduction run is complete.
---

# Paper Reproduction Review

Audit artifacts, not agent assertions. Build the final report only from persisted evidence.

## Reconcile the run

Load the extraction, normalized specs, data assessments, implementation manifest and artifact, tests, evaluation plan/results, truth matches, and pipeline state. Verify every path exists and every serialized artifact reloads. In an autotest, also verify every completed-stage runtime artifact appears in `harvest_manifest.json`; existence only inside the disposable worktree is not durable evidence.

For autotest reviews, also load `reviewer_assignment.json`, `harvest_manifest.json`, the hidden `PaperSelectionArtifact`, and the deterministic assessment before reviewing. Compare the worker's Stage 1 truth choice with the orchestrator's independently recorded principal/default truth block; a mismatch is a selection defect, not permission to rewrite the worker artifact. Treat the control-plane assignment as the authority for reviewer task identity and requested model. Do not self-attest identity or model provenance in the review body. If actual runtime-model evidence is unavailable, preserve `actual_model_status=unverified`. The control plane writes and hashes `reviewer_completion.json` after the review returns.

Before accepting a deferred/resource-limited conclusion, scan for completed scenario bundles and executed records. A recovery report that ignores durable successful records is incomplete and must be rebuilt from those records.

For all eight stages check:

- execution status is supported by artifacts;
- diagnostics and limitations are preserved;
- dependent gates were not bypassed;
- stage names and job ID are consistent;
- no earlier stage was reconstructed or silently overwritten.

## Completion audit

Reject completion when any selected factor lacks an extracted formula/spec, certified implementation, or implementation test. Reject a report that calls a scaffold, inline factor column, plan, or manifest an implementation.

For evaluation verify:

- new extractions use `paper_extraction.ic_recipe.v3`, all references resolve, Stage 1 contains no local physical-field bindings, and every factor has exactly one valid truth-source selection;
- Stage 2 projected the Stage-1-selected recipe without inventing defaults; Stage 3 resolved only that immutable recipe, including semantic fields and raw/already-transformed value states, without using calculated-versus-paper metric closeness;
- every Stage-1 selected truth source has a lifecycle outcome;
- Stage 3 and Stage 6 did not change the selected truth source, and all metrics co-reported by that block were retained;
- unresolved paper conflicts are explicit and ineligible rather than silently resolved;
- only selected resolved cases executed;
- paper protocol remains immutable;
- substitutions and deviations are explicit;
- factor outputs came from the certified implementation artifact;
- calculation data and evaluation filters remained separate, with the global ST/PT and next-trading-day suspension policy applied first in evaluation rather than encoded as a paper recipe step or silently truncating rolling factor history;
- Stage 6 preserved the exact ordered preprocessing trace, including exposure-missing operations, sequential neutralizations, and control transforms marked as applied or reused so already-logged capitalization was not logged twice;
- resource adaptations did not change methodology silently;
- QFQ/HFQ scenarios remained independent where required.

For truth matching verify:

- only evaluation-result truth was used;
- only eligible metrics entered matching;
- diagnostic, deferred, unsupported, and missing proxy metrics are excluded from failure denominators;
- `inconsistent` is used only under sufficient comparability;
- positive claims match the recorded comparability level.
- the executed Pearson-versus-Spearman method matches the immutable paper protocol;
- every explicit missing-value operation survives normalization and execution in the same order;
- signed and absolute metric conventions are reconciled before comparison;
- any companion formula source is authorized, hashed, and distinct from the selected evaluation-truth paper.
- every formula source locator matches the visible source table/figure title or number, and every paper-level formula gap is linked through `affects` and each affected factor's `formula_gap_ids`;
- every formula parameter retains its source symbol, literal value, unit, and algebraic role; derived observation counts or calendar conversions are separate, justified, and independently tested rather than substituted into the source equation;
- exchange-trading-day distances advance on an evidenced exchange calendar, not merely across retained/non-null security observations;
- ratio/percentage rows have been checked for an implied observation denominator and any conflict with the stated sample schedule is explicit;
- natural-month labels were not silently approximated by a fixed trading-day count;
- inferred/defaulted operations appear as structured deviations and downgrade comparability.

## Produce the report

Use `build_paper_reproduction_report(...)` with keyword arguments, including the persisted Stage 3 `data_profiles`, then `finalize_paper_reproduction_report(...)`. The finalizer marks Stage 8 before exporting and refreshes the embedded pipeline snapshot, preventing a final report that still claims `final_report = pending`. Export both JSON and Markdown.

The report must include:

- paper and selected factor scope;
- formula and data provenance;
- implementation modules/artifacts and tests;
- exact, constructed, proxy, rejected, missing, and unassessed data requirements;
- price-view scenarios and coverage;
- selected capitalization basis and lineage, plus industry taxonomy source, level, and effective-date rule;
- financial announcement cutoff/version policy and valuation/dividend units where applicable;
- benchmark/index identifiers, constituent effective-date policy, weight family, calendar-label rule, and yield tenor/unit where applicable;
- assessed, selected, executed, deferred, and unsupported evaluation cases;
- the Stage-1 truth source selected for each factor and any unsupported/deferred outcome;
- paper versus resolved protocols;
- deviations, affected metrics, and comparability;
- computed and paper metrics with truth statuses;
- correct match denominators;
- all eight stage outcomes;
- artifact paths and commands run;
- limitations, rerun conditions, and a no-overclaiming statement.

## Independent review result

Return one verdict:

- `complete`: full reports exist and every stage is properly evidenced;
- `complete_with_limitations`: all stages ran but documented limitations prevent exact reproduction claims;
- `incomplete`: missing implementation, skipped required gate, absent report, invalid artifact, or unsupported status claim.

List blocking deficiencies separately from non-blocking limitations. Give general corrective actions; do not tune guidance to one paper's known answer.

Treat a hand-shaped execution JSON as no execution. Load and inspect each standalone `evaluation_bundle/v2`: it must preserve canonical execution IDs, executor mode, certified implementation and specification hashes, SHA-256 snapshot identity, resource preflight/telemetry, requested/executed samples, alignment counts, universe-filter counts, resolved protocols, and cross-sectional IC values whose summaries can be recomputed. Reconcile every scenario/execution/truth/metric comparison row to those exact bundle records. If calculated values merely restate rounded paper truth without this lineage, classify the run as `incomplete`.
