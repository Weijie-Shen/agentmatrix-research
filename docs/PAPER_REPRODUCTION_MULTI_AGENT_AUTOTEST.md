# Multi-Agent Paper Reproduction Autotest

This workflow tests the current paper-reproduction pipeline against a folder of unrelated papers while keeping every reproduction fresh, isolated, and auditable.

## Architecture

```text
orchestrator
  -> paper inventory + evidence-based factor selection
  -> unique repository-tracked branch/worktree per paper
  -> at most two reproduction workers
  -> durable artifact harvest outside disposable worktrees
  -> fresh independent reviewer per completed run
  -> deterministic + independent verdict reconciliation
  -> cross-paper batch report and owned cleanup
```

The paper folder is an explicit activation input; no machine-specific default is
part of the workflow.

## Why the concurrency cap is two

A reproduction may materialize a full-market, multi-million-row calculation panel. Agent-slot availability therefore overstates safe computational parallelism. Two writers is the hard default cap; reduce it to one when preflight predicts high memory use. QFQ and HFQ always execute sequentially inside each paper run. Reviewers are read-only and start after writers stop.

## Repository components

- `.agents/skills/paper-reproduction-autotest/SKILL.md`: orchestration policy and role boundaries.
- `research_core/factor_lab/paper_reproduction/paper_autotest.py`: deterministic discovery, selection validation, batch planning, unique worktree creation, harness creation, artifact harvesting, and ownership-checked cleanup.
- `research_core/factor_lab/paper_reproduction/agent_harness.py`: exact skill bundle and uncontaminated worker prompt.
- `research_core/factor_lab/paper_reproduction/agent_harness_review.py`: artifact-backed completion assessment.
- `.agents/skills/paper-reproduction-review/SKILL.md`: independent Sol audit contract.

## Activation

Invoke `$paper-reproduction-autotest` and provide the paper folder and committed framework base ref. The orchestrator performs these phases without sending paper truth or prior conclusions to workers:

1. Inventory PDFs and record SHA-256 hashes.
2. Review each paper and persist one `PaperSelectionArtifact` containing up to ten of that paper's strongest factors, prioritizing factors explicitly named in its conclusion or final recommendation.
3. Create a `PaperAutotestBatchManifest` and one `codex/paper-test-...` branch/worktree per selected paper.
4. Bundle the exact paper-reproduction skill revision into each worktree.
5. Dispatch at most two fresh reproduction workers and persist every worker start/stop outcome.
6. Harvest all changed reproduction artifacts, source patches, and hashes before cleanup.
7. Persist the deterministic assessment, then persist the verdict from a fresh independent reviewer.
8. Export JSON and Markdown batch summaries and remove only worktrees whose ownership records match.

The committed base ref must contain the repository-scoped reproduction and review skills. This prevents a test branch from silently omitting uncommitted pipeline changes.

## Factor-selection policy

“Good performing” is defined within each individual paper. Factors from different papers are never compared by raw IC, ICIR, return, or score.

The orchestrator first inspects the paper's conclusion, summary, recommendation, and final screening sections. If the authors name a final set of good factors, that set becomes the test scope when it has ten or fewer reproducible members. Thus, a Huatai paper that concludes with seven selected factors produces a seven-factor test. If the paper recommends more than ten, the orchestrator selects the strongest ten using only that paper's ordering, reported metrics, and emphasis. If the paper provides no final set, the orchestrator selects a few leading factors from its own comparison tables.

The orchestrator records the full recommended set and its source location, then scores formula clarity, local-data support, evaluator support, within-paper performance strength, and compute feasibility from zero through five. The latter dimensions document reproducibility and expected limitations; they do not justify silently replacing an author-recommended factor with an easier one.

Do not choose composite scores, optimized portfolios, chart-only rankings, or a factor whose reported performance cannot be assigned to a numeric truth case unless the paper's explicit final selection itself is the subject being tested and the limitation is recorded.

The selection artifact remains in the orchestrator control root. A worker receives only the paper, factor names, isolated worktree, and generated harness prompt.

## Completion and reports

A run is successful only when:

- all eight reproduction stages are evidenced;
- every selected factor has a certified implementation and passing tests;
- every selected factor has at least one durable executed evaluation record;
- paper-truth comparisons use eligible denominators;
- JSON and Markdown reports include direct paper-versus-calculated results and error metrics.

`complete_with_limitations` is permitted for completed execution with scientific comparability caveats. Missing execution, implementation, tests, or reports is `incomplete`.

The batch report records models, commits, branches, skill hashes, selected scope, stage outcomes, executed/deferred cases, IC comparison metrics, deterministic and independent verdicts, limitations, and generic corrective themes. Framework improvements must generalize across papers; no paper names, factor names, table numbers, or known answers enter pipeline logic.

## Retry safety

Every transition is appended to the run's state history and written to `run_state.json`. Cleanup refuses to run unless the harvest manifest, deterministic assessment, and independent review all exist.

Every retry uses a new run ID, attempt number, branch, and worktree. Harvest the failed attempt before retrying. The new worker sees the current generic workflow but never the previous answer or reviewer diagnosis. Default maximum is three attempts per paper; larger iteration campaigns require explicit user direction.
