# Paper Reproduction Maintainer Handoff

**Status date:** 19 August 2026

**Primary branch:** `paper-reproduction-framework`

## What is ready

The repository contains an end-to-end, stage-gated workflow for reproducing
quantitative factors from papers. It can preserve paper evidence, normalize a
factor specification, validate data semantics, certify an implementation, run
paper-aware IC evaluation, compare eligible metrics with paper-reported truth,
and export an auditable report.

The current handoff validation command is:

```bash
python -m pytest \
  research_core/factor_lab/paper_reproduction \
  .agents/skills/rqdata-fetch-reference/scripts/test_rqdata_reference.py \
  research_core/factor_lab/libraries/huatai_momentum_20161220 \
  research_core/factor_lab/libraries/huatai_technical_2019 \
  -q
```

Use the command's current result as the source of truth; do not preserve a fixed
test count in project documentation. Known warnings are limited to the existing
UTC deprecation and a NumPy zero-variance correlation warning in a test fixture.

The framework is operational, but "completed" does not imply exact scientific
agreement. Each reproduction report must derive its claims from that job's
persisted artifacts; the repository deliberately does not keep an early example
as a project-wide progress proxy.

## System map

The coordinator moves one persistent pipeline state through eight ordered gates:

| Gate | Product | Main implementation |
|---|---|---|
| 1. Paper extraction | Immutable formulas, evidence, truth-source recipes | `extraction.py` |
| 2. Spec normalization | `FactorResearchSpec` records | `normalization.py` |
| 3. Data readiness | Semantic bindings, profiles, history and support decisions | `data_validation.py`, recommended-data loaders |
| 4. Implementation | Manifest, factor-family code, certified artifact | `implementation.py` |
| 5. Formula tests | Machine-readable semantic assertion evidence | factor-family tests |
| 6. Evaluation | Resolved plan and canonical `evaluation_bundle/v2` | `paper_evaluation.py`, `evaluation_execution.py` |
| 7. Truth matching | Eligible metric comparisons and calibrated status | `truth_matching.py` |
| 8. Final review | JSON and Markdown reports plus completeness audit | `reporting.py`, `agent_harness_review.py` |

`PaperReproductionPipelineState` is the authority for gate status. Agents must
load and merge it instead of reconstructing previous work from chat context.
Runtime artifacts belong under `runtime/factor_lab/` and are intentionally
ignored by Git.

## Skills and how they work

The skills are repository-local instructions under `.agents/skills/`. A skill
does not contain a model or a credential. It tells an agent which contracts to
use, what evidence to preserve, which validations are mandatory, and when a
stage may advance. The fresh-agent harness bundles the required skills and
records their hashes so a run is tied to the exact workflow revision.

| Skill | Responsibility |
|---|---|
| `paper-factor-reproduction` | Coordinates all eight stages and owns final integration. |
| `paper-evidence-extraction` | Stages 1-2: paper evidence, formulas, IC recipes, provenance, and normalized specs. |
| `paper-factor-data-readiness` | Stage 3: exact/constructed/proxy/missing data decisions, semantic bindings, point-in-time inputs, price views, calendars, and resource preflight. |
| `paper-factor-implementation` | Stages 4-5: implementation manifest, paper-family code, certified artifact, and formula-focused tests. |
| `paper-factor-evaluation` | Stages 6-7: selected-case planning, canonical execution, IC metrics, and paper-truth matching. |
| `paper-reproduction-review` | Stage 8: independent completeness, artifact reconciliation, denominator checks, and claim calibration. |
| `paper-reproduction-autotest` | Runs isolated multi-paper forward tests, harvests worker artifacts, and compares process quality without exposing precomputed answers to workers. |
| `rqdata-fetch-reference` | Streams missing benchmark/reference data from an authenticated RQData environment without creating a repository cache. |

Start an ordinary job with `paper-factor-reproduction`; it routes each gate to
the narrower stage skill. Use `paper-reproduction-autotest` only for controlled
fresh-agent testing across papers.

## Calculation contracts added in this revision

`factor_calculation_contract/v1` is now mandatory for temporal, weighted,
decay, or unit-sensitive formulas. It prevents several silent reproduction
errors by preserving:

- literal source parameters and units separately from runtime conversions;
- natural-month, exchange-session, and retained-observation window semantics;
- weighted-mean numerator and denominator rules;
- exchange-calendar distance behavior when a security row is missing;
- required pre-sample calculation history; and
- stable semantic assertion IDs that must appear in durable tests.

The contract is validated during extraction, preserved in normalized specs,
hashed into `FactorImplementationArtifact` v2, checked before evaluation, and
audited again by the fresh-agent review gate. Canonical evaluation refuses to
score a contracted factor if the calculation panel lacks certified history
before the first scoring date.

Key files are:

- `.agents/skills/paper-evidence-extraction/references/factor-calculation-contract.md`
- `research_core/factor_lab/paper_reproduction/calculation_contract.py`
- `research_core/factor_lab/paper_reproduction/test_calculation_contract.py`

## Essential repository products

1. **Framework package** — `research_core/factor_lab/paper_reproduction/`
   contains contracts, validators, execution, truth matching, reporting, and
   fresh-agent harness code.
2. **Repository skills** — `.agents/skills/` is the operating manual used by
   agents and reviewers.
3. **Project specification** —
   `docs/PAPER_FACTOR_REPRODUCTION_PROJECT.md` documents the durable scientific
   and architectural decisions.
4. **Autotest system** — `paper_autotest.py`, `agent_harness.py`, and
   `agent_harness_review.py` create isolated jobs, preserve evidence, and reject
   incomplete claims.
5. **Paper-family implementations** — factor code stays under
   `research_core/factor_lab/libraries/<paper_family>/`; this handoff includes
   Huatai technical and corrected Huatai momentum implementations with tests.
6. **On-demand reference data** — `rqdata-fetch-reference` supplies benchmark
   levels, components, weights, the China exchange calendar, and the government
   yield curve when the canonical local bundle does not cover the request.
7. **Reports and evidence** — pipeline JSON/Markdown reports and evaluation
   bundles are durable run products, but large panels, downloaded provider data,
   temporary worktrees, and generated spreadsheets are not source-control
   products.

## RQData reference access

No secret is committed. Each maintainer must arrange their own licensed RQData
environment and SSH authorization. For the currently tested remote pattern:

```bash
export RQDATA_SSH_TARGET=rqdata-host
export RQDATA_REMOTE_PYTHON=/path/to/licensed/python
export RQDATA_REMOTE_SHELL_INIT=1  # only if the remote shell initializes RQData
```

Example: inspect China Securities Index All Share (`000985.XSHG`) levels without
persisting them locally:

```bash
python .agents/skills/rqdata-fetch-reference/scripts/rqdata_reference.py \
  index-levels --index 000985.XSHG \
  --start 2005-04-29 --end 2016-12-30
```

The client opens one `ssh -T` subprocess, streams the validated worker script to
the remote Python process, returns an Arrow frame in memory, and closes the
connection. It does not save credentials or data. The SSH alias, key, remote
license configuration, and environment exports are machine-local prerequisites,
not part of the skill.

RQData fills reference/evaluation gaps; it does not automatically make every
factor formula executable. For example, an idiosyncratic-volatility regression
against China All Share, size, and BP returns still needs correctly constructed
daily stock returns and daily size/BP factor-return series in addition to the
index return.

## Starting or resuming a job

1. Work from the repository root and read
   `docs/PAPER_FACTOR_REPRODUCTION_PROJECT.md` plus
   `.agents/skills/paper-factor-reproduction/SKILL.md`.
2. Record the authorized paper files, selected factors, paper sample, data roots,
   and a stable job ID.
3. Create or load the job's `PaperReproductionPipelineState`.
4. Call `execution_decision(stage_name)` before every gate and use the matching
   stage skill.
5. Persist artifacts and limitations after every gate. Do not keep scientific
   decisions only in a prompt or notebook.
6. Execute selected cases only through `execute_evaluation_plan(...)`; never
   fabricate an execution record from summary values.
7. Run the deterministic harness pre-return check and repair from its
   `earliest_invalid_stage`.
8. Require both JSON and Markdown final reports and an independent Stage-8
   review before claiming completion.

## Data and repository hygiene

- Inspect the canonical recommended-data bundle first; fetch only missing or
  newer reference slices.
- Keep provider credentials, SSH keys, `.env` files, and private account data
  outside the repository.
- Do not commit downloaded market panels, RQData responses, temporary worktrees,
  nested repositories, Python caches, generated workbooks, or local attachments.
- Preserve paper evidence and hashes, but separate immutable source evidence
  from runtime substitutions and proxy decisions.
- Never silently change the benchmark, universe, period, return horizon,
  capitalization basis, industry taxonomy, price view, or weight frequency.

## Known limitations and next work

- Existing benchmark runs are directionally strong but not exact numerical
  reproductions; the main gap is data/protocol equivalence rather than pipeline
  completion.
- Point-in-time universe, industry, status, capitalization, and weighting inputs
  still need paper-specific verification.
- The RQData transport is tested for reference datasets, but each new data family
  requires an explicit query contract and entitlement check before use.
- Continue controlled QFQ/HFQ sensitivity studies, enforce full formula history,
  and build forward labels from the exchange calendar.
- Treat proxy-grade or protocol-gap comparisons as limitations; do not relabel
  them as automated reproduction success.

## Maintainer checklist

Before handing a new change to another maintainer:

```bash
git diff --check
python -m pytest research_core/factor_lab/paper_reproduction -q
```

Then confirm that source changes include tests and documentation, no runtime
dataset is staged, no credential or machine-specific private path is present,
and the final report's claims agree with the persisted artifacts.
