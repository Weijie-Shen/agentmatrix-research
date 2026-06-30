# Paper Factor Reproduction Project

## Project Goal

Build an AI-driven pipeline inside `agentmatrix-research` that takes a research paper describing factors and produces an integrated, reproducible factor implementation under the existing Factor Lab framework.

The pipeline should follow the Alpha101 reproduction pattern already present in the repo:

- extract factor definitions and research assumptions from a paper
- normalize them into Factor Lab specs
- build the required input dataframe from the connected dataset
- implement factor calculation functions
- validate implementation quality
- evaluate predictive power
- optionally compare factor values against third-party truth data
- export reproducible artifacts and a final report

The first MVP should focus on daily price-volume factors. More complex factors, such as accounting, analyst, ownership, macro, or alternative-data factors, should be handled after the core workflow is stable.

## Guiding Principles

1. Use `research_core/factor_lab/` as the mainline integration point.
2. Reuse existing Factor Lab contracts, operators, validation, truth comparison, evaluation, and reporting where possible.
3. Do not create a parallel research framework.
4. Treat the workflow as gated: each stage produces artifacts and must pass checks before the next stage.
5. Never claim a factor is fully reproduced unless external truth comparison passes.
6. If paper details are ambiguous, the agent must record the ambiguity instead of inventing missing formulas, fields, or preprocessing rules.

## Intended AI Workflow

### 1. Paper Extraction

The agent reads the paper or a normalized paper text/Markdown file and extracts all information needed for reproduction.

Required extraction fields:

- paper title
- authors
- source or publication venue
- year
- factor family name
- target factors to reproduce
- factor formulas
- required raw data fields
- data frequency
- sample period
- universe
- preprocessing rules
- neutralization rules, if any
- evaluation method
- portfolio construction rules, if any
- sample factor values, if available
- third-party truth or reference source, if available
- ambiguous or missing information

Suggested artifact:

```text
runtime/factor_lab/paper_specs/<paper_id>_extracted.json
```

Gate checks:

- every target factor has a factor name
- every target factor has a formula
- every target factor has required fields
- frequency is specified or explicitly marked as missing
- ambiguous formula notation is listed in an ambiguity section
- missing paper details are recorded explicitly

### 2. Spec Normalization

The agent converts the extracted information into `FactorResearchSpec` records.

Relevant contract:

```text
contracts/factor_research.py
```

Expected generated files:

```text
research_core/factor_lab/libraries/<family>/
  __init__.py
  specs.py
```

Expected runtime artifacts:

```text
runtime/factor_lab/specs/<family>_specs.json
runtime/factor_lab/catalogs/<family>_catalog.json
```

Gate checks:

- `specs.py` imports cleanly
- generated specs are valid `FactorResearchSpec` objects
- catalog export succeeds
- source document and paper provenance are preserved
- validation thresholds exist
- missing or custom fields are explicitly marked

### 3. Input DataFrame Construction

The agent uses the connected dataset to build the normalized panel required by the factor family.

Expected normalized shape:

```text
date, code, open, high, low, close, volume, amount, ...
```

Additional columns may be required depending on the paper, such as:

- market capitalization
- industry classification
- sector classification
- returns
- adjusted prices
- financial statement fields

Suggested artifact:

```text
runtime/factor_lab/frames/<family>_<job_id>_input_panel.csv
```

Gate checks:

- required columns exist
- `date` is parseable
- `code` is present
- no duplicate `date` x `code` rows
- data is sorted by `code` and `date`
- frequency matches the spec
- preprocessing rules are applied or explicitly skipped
- enough history exists for rolling windows
- coverage is sufficient for the requested factors

Suggested future module:

```text
research_core/factor_lab/data_validation.py
```

### 4. Factor Implementation

The agent writes factor calculation functions under the Factor Lab library structure.

Expected files:

```text
research_core/factor_lab/libraries/<family>/
  __init__.py
  specs.py
  factors.py
  test_factors.py
```

Implementation rules:

- use `research_core.factor_lab.operators` where possible
- keep factor code deterministic
- keep data loading outside factor functions
- factor functions should receive an aligned panel
- factor output should include `date`, `code`, and one column per factor
- replace infinite values with nulls
- preserve paper formula details in specs and notes

Gate checks:

- implementation imports cleanly
- compute function returns expected columns
- output row count matches input panel row count
- factor columns are numeric
- no unexpected infinite values
- non-null coverage is above threshold
- deterministic demo tests pass
- paper-provided sample values match when available

### 5. Validation

The agent writes or reuses tests to validate each stage of the workflow.

Validation layers:

- extraction schema validation
- spec import/export validation
- input dataframe validation
- factor output shape validation
- non-null coverage validation
- sample point reconciliation
- optional truth comparison

Relevant existing modules:

```text
research_core/factor_lab/validation.py
research_core/factor_lab/truth.py
research_core/factor_lab/test_service.py
research_core/factor_lab/test_registry.py
```

Proof status rule:

- without external truth comparison, the maximum status should be `partial proof`
- with passing external truth comparison, status may become `passed`
- with failed checks, status should be `failed`
- with missing critical paper information, status should be `needs_human_review`
- with unavailable required data, status should be `blocked_by_data`

### 6. Evaluation

The agent evaluates predictive power using existing Factor Lab evaluation tools, and extends them only when the paper requires additional methods.

Baseline metrics:

- coverage
- rank IC
- Pearson IC
- rank IC IR
- long-short spread

Relevant existing module:

```text
research_core/factor_lab/evaluation.py
```

Expected artifacts:

```text
runtime/factor_lab/reports/<job_id>_evaluation.json
runtime/factor_lab/reports/<job_id>_evaluation.md
```

Gate checks:

- forward returns are computed without lookahead
- IC metrics exist for enough cross sections
- long-short metrics exist where applicable
- paper evaluation deviations are documented

### 7. Truth Validation

The agent should use third-party truth data when available.

Expected truth CSV format:

```text
date,code,<factor_1>,<factor_2>,...
```

Relevant existing module:

```text
research_core/factor_lab/truth.py
```

Expected artifacts:

```text
runtime/factor_lab/truth/<family>_<factor>_truth_compare.json
runtime/factor_lab/proofs/<family>_<factor>_proof.json
```

Gate checks:

- truth CSV has required columns
- dates are parseable
- no duplicate `date` x `code` keys
- comparison count is nonzero
- exact match ratio, max absolute error, or cross-sectional correlation meets thresholds

### 8. Report Generation

The agent generates a final reproduction report.

Relevant existing module:

```text
research_core/factor_lab/reporting.py
```

Expected artifacts:

```text
runtime/factor_lab/reports/<job_id>_proof_report.json
runtime/factor_lab/reports/<job_id>_proof_report.md
runtime/factor_lab/jobs/<job_id>.json
```

The report should include:

- paper metadata
- extracted factor definitions
- normalized specs
- data fields used
- preprocessing rules
- implementation notes
- tests run
- validation status
- evaluation results
- truth comparison status
- known gaps
- reproducibility commands

## Proposed Skill

Suggested skill name:

```text
paper-factor-reproduction
```

The skill should instruct the agent to:

1. read existing Factor Lab contracts and examples before editing
2. extract paper information into a structured artifact
3. normalize extracted factors into `FactorResearchSpec`
4. validate specs before implementing code
5. validate input data before calculating factors
6. implement factors under `research_core/factor_lab/libraries/<family>/`
7. use shared Factor Lab operators
8. add tests for extraction, specs, data framing, and factor outputs
9. run evaluation and proof export
10. use `truth.py` for third-party comparison when available
11. generate a final report
12. never claim full reproduction without passing external truth comparison

## Experiment Stages

### Stage 1: Paper Extraction Skill MVP

Goal:

Teach the agent to extract the correct information before touching code.

Input:

- one simple paper or Markdown excerpt with clear daily price-volume formulas

Output:

```text
runtime/factor_lab/paper_specs/<paper_id>_extracted.json
```

Checks:

- extraction JSON follows schema
- every factor has `factor_name`, `formula`, `required_fields`, and `frequency`
- ambiguities are explicit
- no invented formulas or fields

Exit criteria:

- the agent can extract 1-3 factors reliably

### Stage 2: Spec Normalization Experiment

Goal:

Convert extraction artifacts into Factor Lab specs.

Output:

```text
research_core/factor_lab/libraries/<family>/specs.py
runtime/factor_lab/specs/<family>_specs.json
runtime/factor_lab/catalogs/<family>_catalog.json
```

Checks:

- `specs.py` imports cleanly
- `FactorResearchSpec` objects are valid
- catalog export works
- paper provenance is preserved
- validation thresholds exist

Exit criteria:

- the agent can create valid specs without implementing factors

### Stage 3: DataFrame Contract Experiment

Goal:

Validate the input data layer independently from factor calculation.

Output:

- data requirement manifest
- input panel diagnostics report

Checks:

- required columns exist
- no duplicate `date` x `code`
- date sorting is correct
- frequency is consistent
- enough lookback history exists
- preprocessing is applied or explicitly skipped

Exit criteria:

- the agent can prove the input panel is suitable before factor calculation

### Stage 4: Factor Implementation Experiment

Goal:

Generate one small factor family implementation.

Output:

```text
research_core/factor_lab/libraries/<family>/
  __init__.py
  specs.py
  factors.py
  test_factors.py
```

Checks:

- factor functions import
- compute function returns `date`, `code`, and factor columns
- output row count matches input panel
- factor columns are numeric
- no infinite values
- non-null coverage passes threshold
- deterministic demo test passes

Exit criteria:

- one or two factors run end-to-end on demo data

### Stage 5: Evaluation Experiment

Goal:

Connect generated factors to existing Factor Lab evaluation.

Output:

```text
runtime/factor_lab/reports/<job_id>_evaluation.json
runtime/factor_lab/reports/<job_id>_evaluation.md
```

Checks:

- forward returns are aligned correctly
- rank IC exists
- long-short spread exists
- enough cross sections exist
- paper evaluation deviations are documented

Exit criteria:

- the factor family produces a reproducible evaluation report

### Stage 6: Truth Validation Experiment

Goal:

Validate factor values against third-party or reference output.

Input:

- truth CSV with `date`, `code`, and factor columns

Output:

```text
runtime/factor_lab/truth/<family>_<factor>_truth_compare.json
runtime/factor_lab/proofs/<family>_<factor>_proof.json
```

Checks:

- truth schema validation
- nonzero comparison count
- exact match ratio, max error, or rank correlation meets thresholds
- proof status logic works

Exit criteria:

- matching truth data can produce `passed`
- missing truth data remains `partial proof`

### Stage 7: Report Generation Experiment

Goal:

Produce the full reproduction bundle.

Output:

```text
runtime/factor_lab/reports/<job_id>_proof_report.json
runtime/factor_lab/reports/<job_id>_proof_report.md
runtime/factor_lab/jobs/<job_id>.json
```

Checks:

- report includes paper metadata
- report includes formulas and data assumptions
- report includes preprocessing and implementation notes
- report includes tests, evaluation, truth validation, and limitations

Exit criteria:

- a reviewer can reproduce the agent's work from the report

### Stage 8: Full Skill Integration

Goal:

Combine the prior experiments into one reusable skill.

Output:

```text
.hermes/skills/paper-factor-reproduction/SKILL.md
```

or another project-approved skill location.

Checks:

- skill enforces mandatory stage order
- skill lists stop conditions
- skill lists required artifacts
- skill lists test commands
- skill enforces proof language rules
- skill integrates with Factor Lab rather than creating a parallel framework

Exit criteria:

- a new agent can follow the skill and reproduce the demo workflow

### Stage 9: Harder Paper Experiments

Goal:

Test the skill on more realistic and ambiguous papers.

Cases:

- ambiguous formula notation
- missing sample values
- non-daily frequency
- accounting or fundamental fields
- evaluation rules not supported by current Factor Lab
- required data unavailable in the connected dataset

Exit criteria:

- the agent knows when to proceed
- the agent knows when to mark `needs_human_review`
- the agent knows when to mark `blocked_by_data`

## Five-Week Schedule

### Week 1: Extraction and Spec Foundation

Goal:

Make the AI reliably read paper content and produce valid structured specs.

Deliverables:

- draft `paper-factor-reproduction` skill, extraction-only version
- extracted paper JSON schema
- mapping from extracted fields to `FactorResearchSpec`
- first test paper fixture in Markdown or text
- extracted paper artifact
- generated `specs.py` for one small factor family

Tests:

- extraction JSON has required fields
- ambiguities are explicit
- generated specs import cleanly
- catalog/spec export works

Exit criteria:

- agent can extract and normalize 1-3 factors without writing factor code

### Week 2: DataFrame Contract and Validation Gates

Goal:

Make sure input data is validated before factor calculation.

Deliverables:

- data requirement manifest format
- `data_validation.py` or equivalent
- normalized panel contract
- checks for columns, duplicates, sortedness, coverage, frequency, and lookback sufficiency
- demo-data validation tests

Tests:

- valid demo panel passes
- missing required field fails
- duplicate `date` x `code` fails
- insufficient rolling history is flagged

Exit criteria:

- agent can prove the input panel is usable before implementing factors

### Week 3: Factor Implementation Scaffold

Goal:

Have the agent create a runnable factor family using the Factor Lab structure.

Deliverables:

- scaffold pattern under `research_core/factor_lab/libraries/<family>/`
- `specs.py`, `factors.py`, `test_factors.py`, and `__init__.py`
- generic or semi-generic service/CLI path for paper factor families
- implementation of 1-3 simple price-volume factors from the test spec

Tests:

- imports pass
- output shape matches input panel
- factor columns are numeric
- no infinite values
- non-null coverage passes
- deterministic sample anchors pass if available

Exit criteria:

- one small paper-derived factor family computes values on demo data

### Week 4: Evaluation, Truth, and Reports

Goal:

Connect the generated family to evaluation, proof, truth, and report artifacts.

Deliverables:

- evaluation JSON and Markdown export
- proof JSON export
- truth CSV schema and comparison
- final reproduction report Markdown and JSON
- job manifest with artifact paths
- status semantics

Tests:

- evaluation artifacts are created
- proof files are created
- truth comparison passes with matching generated truth
- proof remains partial without external truth
- report contains formulas, data assumptions, tests, evaluation, and limitations

Exit criteria:

- end-to-end run produces a full artifact bundle

### Week 5: Skill Hardening and End-to-End Demo

Goal:

Turn the experimental workflow into a reliable reusable skill.

Deliverables:

- final `paper-factor-reproduction` skill
- workflow docs
- reproducible command sequence
- one clean end-to-end demo from paper text to report
- CI-friendly tests that do not require private datasets
- documented unsupported cases and human-review triggers

Tests:

- full unit test suite for changed scope
- one scripted end-to-end smoke run
- generated report manually reviewed
- skill tested on one slightly different paper/spec excerpt

Exit criteria:

- a new agent can follow the skill and reproduce the demo workflow
- the repo has stable scaffolding for future paper-derived factor families

## Suggested Weekly Rhythm

- Monday-Tuesday: implement the week's core feature
- Wednesday: write tests and fixtures
- Thursday: run the agent experiment and record failures
- Friday: harden the skill instructions and update docs

## MVP Scope

The MVP should include:

- text or Markdown paper input
- 1-3 daily price-volume factors
- Factor Lab spec generation
- demo panel validation
- factor implementation under `research_core/factor_lab/libraries/<family>/`
- evaluation report
- proof report
- optional truth comparison
- reusable skill instructions

The MVP should not include:

- raw PDF parsing as a requirement
- accounting factors
- alternative data
- fully generic formula-to-code translation
- final proof claims without external truth data

## Future Extensions

- PDF/document normalization
- richer formula parser
- generic factor family scaffold command
- A-share dataset adapter integration
- paper-specific evaluator plugins
- no-lookahead audit module
- human review UI integration
- external truth-source collectors
