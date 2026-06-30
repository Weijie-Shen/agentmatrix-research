# Paper Factor Reproduction Overnight Log

This file records autonomous overnight design/implementation notes, blockers, and next decisions for review.

## Ground rules from user

- Continue without asking questions while user is absent.
- If blocked or uncertain, record issues here for morning discussion.
- Build on existing Factor Lab; do not create a parallel framework.
- Use paper-reported truth sources first: factor values if present, evaluation metrics if factor values are absent; if both are present, keep both unless explicit selection resolves alternatives.
- Missing truth source means `needs_human_review` for now.
- Preserve formula/field/evaluation ambiguities and report them at the end of the pipeline.
- Quant API key was provided in chat for live data access; do **not** write it into source files, skills, docs, runtime artifacts, or tests.

## Current architecture state before overnight work

Implemented so far:

- `research_core/factor_lab/paper_reproduction/extraction.py`
  - `PaperExtraction`
  - `ExtractedFactor`
  - `ExtractedTruthSource`
  - extraction validation with ambiguity diagnostics
  - paper extraction JSON export/load
- `research_core/factor_lab/paper_reproduction/normalization.py`
  - extraction to `FactorResearchSpec`
  - paper-truth-specific validation targets
  - selected truth source metadata
  - ambiguity metadata
  - generated `specs.py` writer
- `research_core/factor_lab/libraries/simplepv/specs.py`
  - generated SimplePV specs only; no factor code yet

## Overnight planned work sequence

1. Add input DataFrame validation module for Stage 3.
2. Add paper truth matching helpers for later stages.
3. Add lightweight staged pipeline/orchestration artifact writer.
4. Document Quant API integration without storing token.
5. Create reusable `paper-factor-reproduction` skill.
6. Run tests and record outcomes here.

## Open questions for morning review

- Whether extraction validation status should use `implemented` or a clearer status like `ready_for_normalization`.
- Exact numeric tolerance policy for paper-reported factor values.
- Whether evaluation metric matching should be exact, tolerance-based, or rounded based on paper precision.
- How to represent papers that report portfolio returns/Sharpe but not IC/IR.
- Whether Quant API should be wrapped directly in repo code or remain a skill/procedure for now.

## Work log

- Started overnight run.
- Added Stage 3 input dataframe validation:
  - `research_core/factor_lab/paper_reproduction/data_validation.py`
  - `research_core/factor_lab/paper_reproduction/test_data_validation.py`
  - Checks required columns, parseable dates, duplicate `date` x `code`, sortedness, and inferred lookback sufficiency.
- Added paper truth matching utilities:
  - `research_core/factor_lab/paper_reproduction/truth_matching.py`
  - `research_core/factor_lab/paper_reproduction/test_truth_matching.py`
  - Supports factor-value matching by `date, code, value` and evaluation metric matching by metric dictionary.
- Added staged pipeline state:
  - `research_core/factor_lab/paper_reproduction/pipeline.py`
  - `research_core/factor_lab/paper_reproduction/test_pipeline.py`
  - Exports runtime state under `runtime/factor_lab/paper_jobs/<job_id>.json`.
- Added Quant API integration helper and notes without storing token:
  - `research_core/factor_lab/paper_reproduction/quant_api.py`
  - `research_core/factor_lab/paper_reproduction/test_quant_api.py`
  - `docs/PAPER_FACTOR_REPRODUCTION_QUANT_API_INTEGRATION.md`
- Updated existing `paper-factor-reproduction` Hermes skill with Stage 3, Stage 7, pipeline state, and Quant API notes.
- Regenerated SimplePV spec artifact source at `research_core/factor_lab/libraries/simplepv/specs.py`.

## Verification results

- `python3 -m unittest discover -s research_core/factor_lab/paper_reproduction -q`
  - Result: `Ran 30 tests ... OK`
- `.venv/bin/python -m pytest research_core/factor_lab/paper_reproduction -q`
  - Result: `30 passed`
- `.venv/bin/python -m pytest research_core/factor_lab -q`
  - Result: `44 passed`
- After regenerating SimplePV artifacts:
  - `.venv/bin/python -m pytest research_core/factor_lab -q`
  - Result: `44 passed`

## Morning review notes

- The Quant API helper currently only normalizes common daily K-line column names and intentionally does not perform network calls or store tokens.
- The pipeline state is lightweight orchestration only; it does not yet execute all stages automatically.
- Factor implementation remains intentionally unimplemented for SimplePV until the user approves moving past data validation.
