# Paper Factor Reproduction Auto-Test Workflow

This document describes the intended iterative workflow for testing whether a fresh AI agent can reproduce a paper's factor methodology using this repo and the `paper-factor-reproduction` skill.

## Goal

We are not initially testing whether final computed IC/returns numerically match the paper. Those results can differ because of data source, sample coverage, vendor definitions, benchmark, neutralization data, or execution assumptions.

The first goal is to test whether the agent correctly extracts and operationalizes the paper's **reproduction method**:

- formulas,
- data requirements,
- preprocessing,
- neutralization,
- evaluation method,
- paper-reported evaluation truth metrics,
- source locations,
- known limitations and blockers.

## Iterative workflow

### 1. Prepare or choose a paper-specific golden JSON

For each test paper and selected factor scope, create a manually curated golden JSON under:

```text
research_core/factor_lab/paper_reproduction/golden/<paper_id>_<factor_scope>.json
```

If no golden JSON exists yet, build it in a separate review session using:

```text
docs/PAPER_FACTOR_REPRODUCTION_GOLDEN_JSON_CONTEXT.md
```

The golden JSON should be reviewed by the user before it is treated as stable.

### 2. Run the fresh-agent test in a disposable worktree

Create a clean worktree from the framework branch, not from old main:

```bash
cd /Users/mac/agentmatrix-research
git worktree remove /tmp/agentmatrix-paper-test --force 2>/dev/null || true
git branch -D paper-test-run 2>/dev/null || true
git worktree add -b paper-test-run /tmp/agentmatrix-paper-test paper-reproduction-framework
```

Verify framework files exist:

```bash
cd /tmp/agentmatrix-paper-test
test -d research_core/factor_lab/paper_reproduction && echo paper_reproduction present
```

In a new Hermes chat, use `/tmp/agentmatrix-paper-test` as the working directory and provide the paper and selected factors.

Before starting the chat, create a harness packet that bundles the exact
`paper-factor-reproduction` skill with the fresh-agent prompt:

```python
from research_core.factor_lab.paper_reproduction.agent_harness import (
    PaperReproductionAgentHarnessRequest,
    prepare_agent_harness_bundle,
)

bundle = prepare_agent_harness_bundle(
    PaperReproductionAgentHarnessRequest(
        harness_id="<paper_id>_<factor_scope>",
        working_directory="/tmp/agentmatrix-paper-test",
        paper_path="<paper path or attachment note>",
        paper_id="<paper_id>",
        golden_json_path="research_core/factor_lab/paper_reproduction/golden/<paper_id>_<factor_scope>.json",
        selected_factors=["<factor_1>", "<factor_2>"],
        skill_path="/Users/mac/.hermes/skills/research/paper-factor-reproduction/SKILL.md",
    )
)
print(bundle.prompt_path)
```

The harness writes:

```text
runtime/factor_lab/agent_harness/<harness_id>/
  fresh_agent_prompt.md
  harness_metadata.json
  skills/paper-factor-reproduction/SKILL.md
```

Use `fresh_agent_prompt.md` as the starting prompt. The metadata records the
source skill path and SHA-256 hash so each AI test is auditable.

Recommended prompt:

```text
Use /tmp/agentmatrix-paper-test as the working directory.

Load and follow the bundled paper-factor-reproduction skill from the harness packet.

I am attaching a paper. Run the paper reproduction workflow for selected factors only:
- <factor list>

Use paper-reported evaluation results only as truth.
Do not use factor-value truth matching.
Always try Quant API v2 before declaring blocked_by_data.
If formulas, preprocessing, neutralization, evaluation method, or data are ambiguous, record the blocker in a markdown issue log and stop at the correct gate.
```

### 3. Analyze the fresh-agent result against the golden JSON

Compare the agent-generated extraction/spec/report artifacts with the golden JSON.

Main generated artifacts may include:

```text
runtime/factor_lab/paper_specs/<paper_id>_extracted.json
runtime/factor_lab/specs/<family>_specs.json
runtime/factor_lab/catalogs/<family>_catalog.json
runtime/factor_lab/implementation_plans/<family>_implementation_manifest.json
runtime/factor_lab/reports/<job_id>_paper_reproduction_report.json
research_core/factor_lab/libraries/<family>/specs.py
research_core/factor_lab/libraries/<family>/factors.py
research_core/factor_lab/libraries/<family>/test_factors.py
```

Comparison priorities:

1. Selected factor scope.
2. Formula accuracy.
3. Formula-required fields.
4. Stage-specific data requirements.
5. Preprocessing rules.
6. Neutralization rules.
7. Evaluation method and return horizon.
8. Truth source granularity and source locations.
9. Paper metric values.
10. Known limitations vs blocking ambiguities.

### 4. Improve structure or skill

If the agent's output is wrong, decide whether the fix belongs to:

- the skill instructions,
- extraction schema,
- validation logic,
- normalization metadata,
- implementation manifest,
- report generation,
- Quant API/data acquisition instructions.

Examples:

- If the agent marks missing daily factor values as a blocker despite aggregate metrics existing, improve skill/validation around `known_limitations`.
- If it mixes multiple tables into one truth source, improve truth-source granularity instructions and/or validation warnings.
- If it treats VWAP as a formula field when only portfolio evaluation needs it, improve stage-specific data requirement extraction.

### 5. Retest

Repeat the test with the same paper to check whether the correction works.

Then test with a different paper to check whether the fix generalized.

## Overfitting caution

Do not tune the workflow only to pass one paper. Each improvement should be phrased as a general extraction principle.

Examples of good general principles:

- split truth sources by table/evaluation setting;
- distinguish formula fields from evaluation fields;
- record aggregate-only paper metrics as known limitations rather than blockers;
- keep paper-specific helper functions local until repeated need justifies promotion.

Examples of overfitting:

- hardcoding Huatai table numbers into extraction logic;
- assuming all technical-factor papers use T=20;
- assuming all papers use industry+market-cap neutralization;
- assuming VWAP is always the execution price.

We will revisit overfitting after building several golden JSON artifacts.

## Cleanup

After a test, remove the worktree:

```bash
cd /Users/mac/agentmatrix-research
git worktree remove /tmp/agentmatrix-paper-test --force
git branch -D paper-test-run
```
