---
name: paper-reproduction-review
description: Audit AgentMatrix paper-factor reproduction artifacts and produce or validate the final report. Use for Stage 8, independent completeness review, pipeline-state reconciliation, artifact and test verification, truth-denominator checks, claim calibration, and deciding whether a fresh-agent reproduction run is complete.
---

# Paper Reproduction Review

Audit artifacts, not agent assertions. Build the final report only from persisted evidence.

## Reconcile the run

Load the extraction, normalized specs, data assessments, implementation manifest and artifact, tests, evaluation plan/results, truth matches, and pipeline state. Verify every path exists and every serialized artifact reloads.

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

- every candidate truth source has a lifecycle outcome;
- only selected resolved cases executed;
- paper protocol remains immutable;
- substitutions and deviations are explicit;
- factor outputs came from the certified implementation artifact;
- calculation data and evaluation filters remained separate;
- resource adaptations did not change methodology silently;
- QFQ/HFQ scenarios remained independent where required.

For truth matching verify:

- only evaluation-result truth was used;
- only eligible metrics entered matching;
- diagnostic, deferred, unsupported, and missing proxy metrics are excluded from failure denominators;
- `inconsistent` is used only under sufficient comparability;
- positive claims match the recorded comparability level.

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
