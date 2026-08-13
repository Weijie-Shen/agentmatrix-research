# Autotest Artifact Contracts

## Control-plane layout

Keep these artifacts in the orchestrator checkout so disposable worktree cleanup cannot remove them:

```text
runtime/factor_lab/paper_autotest/<batch_id>/
  batch_manifest.json
  selections/<paper_id>.json
  <paper_id>/attempt-01/
    run_state.json
    worker_stop.json
    harvest_manifest.json
    git_status.txt
    worker_changes.patch
    artifacts/
    deterministic_assessment.json
    independent_review.json
  batch_summary.json
  batch_summary.md
```

## State transitions

```text
planned -> worktree_ready -> ready_for_worker -> running -> worker_stopped
        -> harvested -> deterministic_reviewed -> independently_reviewed
        -> complete | complete_with_limitations | incomplete -> cleaned
```

Never mark `complete` from agent prose. The deterministic utilities refresh `run_state.json` and its append-only `state_history` after worktree preparation, harness creation, worker start/stop, harvesting, each review record, the final verdict, and cleanup. A writer crash becomes `worker_stopped` and is harvested before retry decisions.

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

Workers do not receive `PaperSelectionArtifact`, golden files, cross-paper summaries, reviewer output, or prior-attempt artifacts.

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

## Review contract

The independent review must cite artifact paths and check:

1. selected scope and formula provenance;
2. all eight persisted stage outcomes;
3. semantic data selections and scenario isolation;
4. certified factor implementation plus tests;
5. durable executed cases for every selected factor;
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
