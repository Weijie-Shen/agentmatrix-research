---
name: paper-reproduction-autotest
description: Orchestrate auditable multi-paper forward tests of the AgentMatrix paper-reproduction pipeline. Use when Codex must inventory a paper test-case folder, select strong and reproducible factors from each paper, prepare isolated repository-tracked test branches/worktrees, dispatch fresh low-cost reproduction agents, harvest their artifacts, assign independent reviewers, and summarize cross-paper defects without contaminating workers with golden answers or prior attempts.
---

# Paper Reproduction Autotest

Coordinate the control plane. Reproduction workers follow `$paper-factor-reproduction`; reviewers follow `$paper-reproduction-review`.

Read `references/artifact-contracts.md` before creating a batch. Use the deterministic APIs in `research_core/factor_lab/paper_reproduction/paper_autotest.py` for discovery, planning, worktree preparation, harness generation, harvesting, and owned cleanup.

## Roles and models

- Orchestrator: use `gpt-5.6-sol`. Own selection, scheduling, manifests, task boundaries, artifact collection, adjudication, and the batch summary.
- Reproducer: use `gpt-5.6-terra` with medium reasoning by default. Give it exactly one paper, one isolated worktree, selected factor names, and the generated harness prompt.
- Reviewer: use a fresh `gpt-5.6-sol` agent. Give it harvested artifacts, selected factor names, and `$paper-reproduction-review`; do not let it repair the writer's output.

Run at most two reproducer agents concurrently. Full-market QFQ/HFQ evaluations are memory-heavy, so never increase this cap merely because more agent slots exist. Run no more than one full-data process in each worktree. Reviewers are read-only and may start after their corresponding writer has stopped.

## 1. Inventory and select

Discover PDFs under the requested test-case root with `discover_test_papers(...)`. Persist the path, byte size, and SHA-256. Do not assume filenames are reliable paper IDs without recording the hash.

Review each paper independently before dispatch. Select the strongest factors within that paper, never by comparing its IC, return, or rank with factors from other papers. Select at most ten factors from one paper.

Inspect the conclusion, summary, recommendation, and final factor-screening sections first. When the authors explicitly identify a final set of good-performing factors, use that set as the primary selection:

- if the final set contains ten or fewer reproducible factors, select all of them;
- if it contains more than ten, select the strongest ten using only that paper's ranking, reported metrics, and author emphasis;
- do not replace an author-recommended factor with an easier factor merely because the easier one is cheaper to reproduce;
- record the complete author-recommended set and the conclusion/recommendation source location in `PaperSelectionArtifact`.

The Huatai-style pattern of naming seven final factors therefore produces a seven-factor test scope, not an arbitrary smaller sample.

If the paper has no explicit final recommendation, select a few leading factors from its own factor comparison tables. A selected factor must have:

- an unambiguous formula and parameters with a narrow source location;
- inputs that are exact or constructible from supported data;
- a numeric paper-reported evaluation result with a narrow truth location;
- a supported or realistically implementable evaluator;
- paper-reported performance strong enough to make it a useful reproduction target;
- manageable expected compute cost.

Score formula clarity, local-data support, evaluator support, within-paper performance strength, and compute feasibility from zero through five. Performance strength is relative only to factors evaluated in the same paper. Author inclusion in the paper's final recommended set is the strongest selection signal. Use the other dimensions to assess reproducibility and anticipated limitations, not to override the paper's final factor selection. Do not select composites, optimized portfolios, chart-only rankings, or factors whose attractive performance has no attributable numeric truth. Persist `PaperSelectionArtifact`; do not expose its truth values, scores, or reasoning to reproduction workers.

For every selected factor, also choose its single principal/default IC result block using the Stage 1 truth-source standard. Persist the narrow truth location, `truth_source_role`, `truth_selection_reason`, and a `paper_recipe_summary` containing at least `ic_method`, `return_label`, and `preprocessing_order`. One block may cover several factors. Keep this selection evidence hidden from the worker; the independent reviewer uses it to audit the worker's Stage 1 choice without supplying a golden answer.

## 2. Plan isolated runs

Use `create_batch_manifest(...)` with an explicit committed base ref. The base commit must already contain the repository-tracked reproduction, extraction, autotest, and review skills; the `paper_extraction.ic_recipe.v3` runtime; and every extraction reference (schema, selection standard, semantic data states, method catalogs, examples, and global policy). Never test an uncommitted framework snapshot.

Prepare one unique `codex/paper-test-<run-id>` branch and one `/private/tmp/agentmatrix-paper-tests/...` worktree per paper with `prepare_test_worktree(...)`. Never share a worktree between paper writers. Never reuse a path or branch from an earlier attempt. The ownership record is mandatory.

Call `prepare_run_harness(...)` inside each worktree. Treat its bundled skill hash and base commit as run provenance. Keep selection artifacts and previous reviewer output in the main checkout's control root, outside every worker's discovery surface.

## 3. Dispatch fresh reproducers

Spawn up to two Terra workers. Use a bounded assignment containing:

- exact worktree and paper paths;
- selected factor names only;
- generated harness prompt path;
- `$paper-factor-reproduction` and bundled stage skills;
- required `paper_extraction.ic_recipe.v3` contract: select one principal truth block in Stage 1, resolve its recipe and data value states in Stage 3, then execute it unchanged in Stage 6 after the global evaluation policy;
- required outputs: pipeline state, extraction/specs, data profiles, implementation artifact and tests, evaluation bundles, paper-truth comparisons, and JSON/Markdown reports;
- return contract: artifact paths, commands/tests, lifecycle outcomes, and limitations.

Do not give workers selection scores, extracted metric values, golden JSON, another worker's results, suspected pipeline defects, or retry conclusions. A worker must not edit the orchestrator checkout or another worktree. Wait for persistent evaluation processes to exit; a yielded tool call is not completion.

The control plane must verify worktree quiescence before accepting a completed stop and again before harvesting any outcome. Every worker-authored evaluation runner must use `scientific_process_lease(...)`; a running or unreadable receipt blocks stop/harvest, while an abrupt process death deliberately leaves a blocking receipt. OS process inspection is supplementary because some sandboxes cannot enumerate processes. Treat an observed active process, a missing terminal receipt for a runner/bundle, or artifacts changing during the completion gate as a process-lifecycle defect. Keep polling or terminate the owned failed process explicitly; never harvest a live worktree.

Immediately persist each dispatched task with `record_worker_started(...)`. When it finishes, fails, or is interrupted, call `record_worker_stopped(...)` with the lifecycle outcome before inspecting or harvesting its files.

The generated harness contains a deterministic pre-return command. Require the worker to run it, repair from `earliest_invalid_stage`, and rerun dependent stages while the same task and worktree remain active. When the worker announces completion, `record_worker_stopped(..., outcome="completed")` independently reruns this gate. If it raises because `complete=false`, do not stop, harvest, or create a retry attempt: send the persisted defects and repair actions back to that same active worker. For fresh v3 runs, the gate rejects v2 extraction, Stage 3 or Stage 6 truth-source reselection, unresolved value states, a missing global-policy trace, reordered preprocessing, collapsed sequential neutralizations, and transformed controls that lack reuse/apply lineage. A genuine hard blocker may instead be recorded as `failed`; scientific metric drift must not be repaired by tuning formulas to paper answers.

The gate must also reject untyped return labels, schedule/return-interval contradictions, missing or blocked Stage-3 executable contracts, and any disagreement between a recipe control's `resolved_field` and the contract's authoritative semantic binding. Attribute these to extraction or Stage 3 before accepting Stage-6 execution artifacts.

For risky factor formulas, the gate must additionally reject a missing or invalid `factor_calculation_contract/v1`, a stale/missing implementation contract hash, a calculation panel without certified pre-sample history, and durable formula-test evidence that omits any required semantic assertion ID. Treat these as extraction, Stage 3, implementation, or test defects according to the earliest failed gate.

## 4. Harvest and review

After a worker stops, call `harvest_run_artifacts(...)` before cleanup. It copies changed reproduction artifacts to the batch control root, records hashes and omissions, and preserves Git status and a source patch.

Treat `review_ready=false` or any `missing_required_artifact_families` as an explicit evidence gap. The harvest must include Stage 3 profiles, evaluation plans, implementation certification, formula-test source and durable test output, evaluation bundles, truth matches, both reports, and worker-authored runners. Cache files and bytecode are not scientific artifacts.

When no final report exists, the deterministic gate must still inventory every standalone stage family and return the earliest missing upstream stage. Do not collapse missing Stage 3, evaluation, or truth artifacts into a report-only defect.

Run `assess_agent_harness_run(...)` against the isolated worktree and pass the harvested manifest path so durability is checked; persist it with `record_deterministic_assessment(...)`. Then spawn a fresh Sol reviewer with only:

- the paper path;
- selected factor names;
- harvested manifest/artifact root;
- assessment output;
- bundled skill hashes and base commit;
- `$paper-reproduction-review`.

Before dispatch, call `record_reviewer_started(...)` with the fresh reviewer task ID and requested model. This writes control-plane-owned assignment provenance and rejects reuse of the writer or another batch task. Requested-model provenance must remain distinct from actual-runtime-model evidence; when the platform cannot attest the latter, record it as unverified rather than copying a reviewer self-claim.

Require the reviewer to inspect persisted artifacts, compare each worker-selected Stage 1 truth source with the hidden selection evidence, and return `complete`, `complete_with_limitations`, or `incomplete`, with blocking defects separated from limitations and cited artifact paths. Persist it with `record_independent_review(...)`; that API validates the assignment and writes a hashed completion record. The orchestrator reconciles that verdict with the deterministic assessment. Neither reviewer nor orchestrator may call a run successful unless all eight stages are evidenced, every selected factor has a certified implementation and passing test, every selected factor has a durable execution of its selected v3 recipe, and both report formats contain paper-versus-calculated comparisons.

## 5. Summarize and clean up

Write one batch summary showing per paper:

- selected scope and selection-artifact path;
- branch, base commit, worker/reviewer models, and skill bundle hash;
- stage status, executed/deferred cases, truth status, IC error metrics, and report paths;
- deterministic assessment and independent-review verdict;
- blocking defects, non-blocking limitations, and generic corrective themes.

Aggregate defects only after preserving paper-local evidence. Classify proposed fixes by skill, extraction/schema, data readiness, implementation, evaluator, reporting, harness, or resource execution. Never tune framework logic to a paper name, factor name, table number, or known answer.

Call `cleanup_test_worktree(...)` only after successful harvest and both review records are persisted. It validates exact ownership and the three control-plane artifacts before removing the worktree and branch. Retain incomplete run artifacts for audit even after cleanup.

## Retry policy

Retries use a new attempt number, run ID, branch, and worktree. A retry receives only the paper, selected factors, current bundled skill, and generic corrected workflow; it must not see the previous answer. Do not auto-retry scientific mismatches by changing formulas to chase paper metrics. Retry infrastructure/interruption failures only after recording the first attempt, and stop a paper after three attempts unless the user explicitly requests a broader iteration campaign.
