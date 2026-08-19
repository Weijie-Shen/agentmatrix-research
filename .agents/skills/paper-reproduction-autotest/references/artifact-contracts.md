# Autotest Artifact Contracts

## Control-plane layout

Keep these artifacts in the orchestrator checkout so disposable worktree cleanup cannot remove them:

```text
runtime/factor_lab/paper_autotest/<batch_id>/
  batch_manifest.json
  selections/<paper_id>.json
  <paper_id>/attempt-01/
    run_state.json
    worker_completion_gate.json
    worker_gate_assessments/
    worker_stop.json
    harvest_manifest.json
    worktree_ownership.json
    git_status.txt
    worker_changes.patch
    artifacts/
    deterministic_assessment.json
    reviewer_assignment.json
    independent_review.json
    reviewer_completion.json
  batch_summary.json
  batch_summary.md
```

## State transitions

```text
planned -> worktree_ready -> ready_for_worker -> running -> worker_stopped
        -> harvested -> deterministic_reviewed -> reviewer_running -> independently_reviewed
        -> complete | complete_with_limitations | incomplete -> cleaned
```

Never mark `complete` from agent prose. The deterministic utilities refresh `run_state.json`, the matching run in `batch_manifest.json`, and append-only `state_history` after worktree preparation, harness creation, worker gate passes, worker start/stop, harvesting, reviewer assignment, each review record, the final verdict, and cleanup. A writer crash becomes `worker_stopped` and is harvested before retry decisions.

Fresh v3 control artifacts use `paper_autotest_batch/v2`, `paper_autotest_selection/v2`, `paper_autotest_harvest/v3`, and `paper_autotest_reviewer_assignment/v2`. These versions carry the required extraction schema, global-policy ID, Stage 1 truth-selection ownership, and hidden selection recipe summary.

## Worker completion gate

The fresh-agent harness gives the worker an exact `agent_harness_review` command and a durable output path. Before returning, the worker gets up to three correction passes in the same task/worktree. Each pass starts at `earliest_invalid_stage`; dependent artifacts and executions must then be rebuilt rather than relabeled.

The control plane independently reruns the same assessment when `record_worker_stopped(..., outcome="completed")` is requested. Failed assessments are saved under `worker_gate_assessments/`, the plan remains `running`, and the same worker receives the defect list plus `repair_actions`. Only `complete=true` permits a completed stop. Hard blockers use a failed/interrupted stop and are still harvested and reviewed.

The deterministic gate validates persisted artifact families, extraction/spec scope, Stage 3 profiles and sample bounds, certified source hashes, per-factor test coverage and durable test results, Stage-1-selected → Stage-3-resolved → Stage-6-executed lineage, QFQ/HFQ scenario evidence, global-policy execution, ordered preprocessing, skipped transforms/controls/filters, truth eligibility denominators, pipeline/report consistency, and—after harvest—durability. Standalone executions must be canonical `evaluation_bundle/v2` exports with stable execution IDs, certified source/specification identity, canonical executor mode, SHA-256 snapshot identity, resource preflight/telemetry, requested/executed samples, alignment and universe row counts, internally consistent IC summaries derived from persisted cross-sectional values, and scenario/execution/truth/metric report reconciliation. Hand-shaped execution JSON and calculated values copied from paper truth are incomplete.

The gate inventories standalone stage families even when the final JSON report is absent or unreadable, so `earliest_invalid_stage` identifies the first missing upstream artifact rather than defaulting to Stage 8. It also samples scientific artifact hashes around the assessment, validates durable `scientific_process_lease(...)` receipts for worker-authored runners/bundles, and supplements those receipts with OS process inspection when the sandbox permits it. Active receipts/processes, missing terminal receipts, or changing artifacts keep the run in `running`.

Fresh autotest runs require `paper_extraction.ic_recipe.v3`: exactly one principal/default truth block per factor is selected in Stage 1, its recipe is resolved without reselection in Stage 3, and Stage 6 executes that resolved recipe unchanged after `china_a_share_ic_evaluation_v1`. Every return label has a typed interval, and every selected case has a certified `stage3_executable_evaluation_contract/v1` containing the authoritative semantic bindings and required physical fields. The gate rejects unresolved data value states, binding/recipe disagreement, absent physical fields, double-applied transforms, missing reuse/apply lineage, reordered preprocessing, and collapsed sequential neutralizations. Legacy `paper_extraction.ic_analysis.v2` is accepted only when the harness metadata explicitly declares that older schema; a fresh v3 harness must not silently downgrade.

Temporal, weighted, decay, and unit-sensitive factor formulas also require `factor_calculation_contract/v1`. The gate rejects missing contracts, observation counts substituted for literal month/year parameters, weighted means without sum-of-weights normalization, fixed-observation substitutes for natural-month windows, insufficient pre-sample calculation history, stale implementation contract hashes, and durable tests that omit the contract's required semantic assertion IDs.

## Harvest contract

`harvest_manifest.json` must inventory required scientific families, not merely files under a short allowlist. Required families are pipeline state, extraction, normalized specs, Stage 3 profiles, implementation certification, formula-test source and durable test output, evaluation plan and bundles, truth match, and both report formats. Worker runners under `scripts/` and factor tests under the implemented library or top-level `tests/` are retained. Bundled harness/skill self-tests do not satisfy the factor implementation-test family. Python bytecode and cache directories are excluded.

Harvesting requires a quiescent worktree for completed, failed, and interrupted outcomes. Do not copy artifacts while a scientific-process receipt is active, while a worker-authored runner/bundle lacks a terminal receipt, or while an observable Python/pytest/scientific process still has its current directory inside the worktree.

The manifest records copied-file hash verification separately from scientific review readiness. `omitted_files`, `missing_required_artifact_families`, and `review_ready` must make gaps explicit. An empty `omitted_files` list does not imply that the run is review-ready.

## Worker assignment

Each reproducer receives one writable worktree. Required assignment fields:

- batch and run IDs;
- paper path and SHA-256;
- selected factor names;
- worktree, branch, and base commit;
- harness prompt and skill bundle hashes;
- model `gpt-5.6-terra`;
- no-contamination restrictions;
- required output and return contracts.

Workers do not receive `PaperSelectionArtifact`, answer-key artifacts, cross-paper summaries, reviewer output, or prior-attempt artifacts.

## Selection rubric

Apply the rubric within one paper only. Never use it to rank factors from different papers against one another.

Start with the paper's conclusion, summary, recommendation, or final screening section. Persist its named final factor set and exact source location. Select all members when the set has ten or fewer reproducible factors. When it has more than ten, select the strongest ten from that set using the paper's own ordering, metrics, and author emphasis. If no final set exists, use the paper's own comparison tables to identify its leading few factors.

Use integer scores from zero through five:

| Dimension | 5 | 3 | 0 |
|---|---|---|---|
| Formula clarity | exact formula, parameters, timing | resolvable minor ambiguity | material unresolved definition |
| Local-data support | exact canonical fields and coverage | supported construction/proxy | formula input unavailable |
| Evaluator support | exact existing evaluator | bounded paper-local extension | no numeric executable protocol |
| Within-paper performance strength | in the paper's final recommended set or highest reported tier | useful relative to peers in that paper | no attributable numeric evidence |
| Compute feasibility | narrow inputs and ordinary horizon | heavier controls/history | infeasible without changing method |

A selected factor needs formula clarity and within-paper performance strength of at least three. The paper's explicit final recommendation takes priority over cross-factor diversity or compute convenience. Use total score only to order candidates inside the same paper when the paper recommends more than ten or provides no final list.

`PaperSelectionArtifact` uses `paper_autotest_selection/v2`. Each selected factor must record the principal truth block's narrow location, role, selection reason, and a `paper_recipe_summary` with `ic_method`, `return_label`, and `preprocessing_order`. This hidden evidence audits selection consistency; it is not sent to the reproduction worker.

## Review contract

Persist `reviewer_assignment.json` before reviewer dispatch using the orchestrator-observed task ID. The reviewer task must differ from the writer and every task already used by another run in the batch. Requested model, actual-runtime-model evidence, and model-verification status are separate fields; never treat reviewer-authored JSON as identity or model proof. Persist `reviewer_completion.json` with hashes of the assignment and final review.

The independent review must cite artifact paths and check:

1. selected scope, formula provenance, and whether the worker's Stage 1 truth choice agrees with the hidden selection evidence;
2. all eight persisted stage outcomes;
3. semantic data selections, explicit raw/already-transformed value states, and scenario isolation;
4. certified factor implementation plus tests;
5. durable execution of every selected factor's Stage-1-selected and Stage-3-resolved recipe, including global-policy and ordered-preprocessing traces;
6. paper-truth eligibility, denominators, and comparison metrics;
7. JSON and Markdown report completeness;
8. limitation/claim calibration;
9. skill hash, base commit, and run identity consistency.

Use `complete_with_limitations` only when execution completed and limitations constrain exact scientific claims. Missing executed cases, implementation artifacts, tests, or final reports are `incomplete`.

## Device budget

- Maximum concurrent Terra reproducers: two.
- Maximum concurrent full-data calculation per worktree: one.
- Load QFQ and HFQ sequentially within a run.
- Do not parallelize multiple factor workers inside the same paper worktree.
- A Sol reviewer is read-only and starts only after its Terra writer stops.
- When memory preflight is close to the device limit, reduce active writers to one; do not shorten the scientific sample to preserve concurrency.
