from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from research_core.factor_lab.runtime import FactorLabWorkspaceConfig, now_iso
from research_core.factor_lab.paper_reproduction.evaluation_recipe import (
    GLOBAL_EVALUATION_POLICY_ID,
    IC_RECIPE_SCHEMA_VERSION,
)


DEFAULT_SKILL_NAME = "paper-factor-reproduction"
DEFAULT_SKILL_ENV_VAR = "PAPER_FACTOR_REPRODUCTION_SKILL_PATH"
DEFAULT_STAGE_SKILL_NAMES = (
    "paper-evidence-extraction",
    "paper-factor-data-readiness",
    "paper-factor-implementation",
    "paper-factor-evaluation",
    "paper-reproduction-review",
    "rqdata-fetch-reference",
)


@dataclass(slots=True)
class PaperReproductionAgentHarnessRequest:
    """Inputs needed to prepare a fresh-agent reproduction test packet."""

    harness_id: str
    working_directory: str
    selected_factors: list[str]
    paper_path: str = ""
    paper_id: str = ""
    golden_json_path: str = ""
    skill_path: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PaperReproductionAgentHarnessBundle:
    harness_id: str
    created_at: str
    root_dir: str
    prompt_path: str
    metadata_path: str
    skill_copy_path: str
    skill_source_path: str
    skill_sha256: str
    skill_bundle_paths: list[str] = field(default_factory=list)
    skill_bundle_sha256: str = ""


def default_skill_path() -> Path:
    """Return the repository-scoped Codex skill used by fresh-agent tests."""

    configured = os.environ.get(DEFAULT_SKILL_ENV_VAR, "").strip()
    if configured:
        return Path(configured).expanduser()
    repository_root = Path(__file__).resolve().parents[3]
    return repository_root / ".agents" / "skills" / DEFAULT_SKILL_NAME / "SKILL.md"


def prepare_agent_harness_bundle(
    request: PaperReproductionAgentHarnessRequest,
    *,
    config: FactorLabWorkspaceConfig | None = None,
) -> PaperReproductionAgentHarnessBundle:
    """Create an auditable prompt packet that includes the reproduction skill."""

    workspace = config or FactorLabWorkspaceConfig()
    workspace.ensure_directories()

    source_skill_path = Path(request.skill_path).expanduser() if request.skill_path else default_skill_path()
    if not source_skill_path.exists():
        raise FileNotFoundError(
            f"paper-factor-reproduction skill not found at {source_skill_path}. "
            f"Pass skill_path or set {DEFAULT_SKILL_ENV_VAR}."
        )

    root_dir = workspace.runtime_root / "agent_harness" / request.harness_id
    bundle_root = root_dir / "skills"
    skill_copy_path, skill_bundle_paths = _copy_skill_bundle(
        source_skill_path=source_skill_path,
        bundle_root=bundle_root,
    )

    skill_text = skill_copy_path.read_text(encoding="utf-8")
    skill_sha256 = hashlib.sha256(skill_text.encode("utf-8")).hexdigest()
    skill_bundle_sha256 = _hash_skill_bundle(bundle_root)

    metadata = _metadata_payload(
        request=request,
        root_dir=root_dir,
        skill_copy_path=skill_copy_path,
        source_skill_path=source_skill_path,
        skill_sha256=skill_sha256,
        skill_bundle_paths=skill_bundle_paths,
        skill_bundle_sha256=skill_bundle_sha256,
    )
    metadata_path = root_dir / "harness_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    prompt_path = root_dir / "fresh_agent_prompt.md"
    prompt_path.write_text(_render_prompt(metadata), encoding="utf-8")

    return PaperReproductionAgentHarnessBundle(
        harness_id=request.harness_id,
        created_at=metadata["created_at"],
        root_dir=str(root_dir),
        prompt_path=str(prompt_path),
        metadata_path=str(metadata_path),
        skill_copy_path=str(skill_copy_path),
        skill_source_path=str(source_skill_path),
        skill_sha256=skill_sha256,
        skill_bundle_paths=skill_bundle_paths,
        skill_bundle_sha256=skill_bundle_sha256,
    )


def _metadata_payload(
    *,
    request: PaperReproductionAgentHarnessRequest,
    root_dir: Path,
    skill_copy_path: Path,
    source_skill_path: Path,
    skill_sha256: str,
    skill_bundle_paths: list[str],
    skill_bundle_sha256: str,
) -> dict[str, Any]:
    payload = asdict(request)
    gate_output_path = root_dir / "worker_pre_return_assessment.json"
    gate_arguments = " ".join(
        [
            "python -m research_core.factor_lab.paper_reproduction.agent_harness_review",
            shlex.quote(request.working_directory),
            *(f"--factor {shlex.quote(factor)}" for factor in request.selected_factors),
            f"--harness-id {shlex.quote(request.harness_id)}",
            f"--output {shlex.quote(str(gate_output_path))}",
        ]
    )
    payload.update(
        {
            "created_at": now_iso(),
            "harness_root": str(root_dir),
            "skill_name": DEFAULT_SKILL_NAME,
            "skill_copy_path": str(skill_copy_path),
            "skill_source_path": str(source_skill_path),
            "skill_sha256": skill_sha256,
            "skill_bundle_paths": skill_bundle_paths,
            "skill_bundle_sha256": skill_bundle_sha256,
            "agent_platform": "codex",
            "required_agent_instruction": "Load and follow the bundled paper-factor-reproduction skill before doing reproduction work.",
            "truth_policy": "Use paper-reported evaluation_results only; do not use factor-value truth matching.",
            "required_extraction_schema_version": IC_RECIPE_SCHEMA_VERSION,
            "required_global_evaluation_policy_id": GLOBAL_EVALUATION_POLICY_ID,
            "truth_selection_stage": 1,
            "recipe_resolution_stage": 3,
            "recipe_execution_stage": 6,
            "stage_policy": "Proceed through the gated paper reproduction workflow and stop at the correct gate when blocked.",
            "required_price_adjustment_views": ["qfq", "hfq"],
            "qfq_anchor_policy": "per-security cumulative factor at the paper testing-period end",
            "hfq_anchor_policy": "RQData initial cumulative-factor baseline",
            "deterministic_gate_command": gate_arguments,
            "deterministic_gate_output_path": str(gate_output_path),
            "deterministic_gate_max_repair_passes": 3,
        }
    )
    return payload


def _render_prompt(metadata: dict[str, Any]) -> str:
    selected_factors = metadata.get("selected_factors", [])
    factors_text = "\n".join(f"- {factor}" for factor in selected_factors) if selected_factors else "- <selected factors>"
    notes = metadata.get("notes", [])
    notes_text = "\n".join(f"- {note}" for note in notes) if notes else "- None"
    paper_line = metadata.get("paper_path") or "<attach or provide paper path>"
    golden_line = metadata.get("golden_json_path") or "<optional golden JSON path>"
    return f"""# Fresh Agent Paper Reproduction Harness

Use this packet to run a fresh AI-agent test for paper factor reproduction.

## Mandatory Skill

Load and follow the bundled skill before starting:

```text
{metadata["skill_copy_path"]}
```

Skill SHA-256:

```text
{metadata["skill_sha256"]}
```

Skill bundle SHA-256:

```text
{metadata["skill_bundle_sha256"]}
```

## Working Directory

```text
{metadata["working_directory"]}
```

## Paper

```text
{paper_line}
```

Paper ID:

```text
{metadata.get("paper_id") or "<paper id>"}
```

## Selected Factors

{factors_text}

## Golden JSON

```text
{golden_line}
```

## Instructions

- Use paper-reported `evaluation_results` only as truth. Create new Stage-1 artifacts as `{metadata["required_extraction_schema_version"]}`; v2 and legacy extraction are compatibility inputs only, not valid fresh-run output.
- Do not use paper factor-value truth matching.
- Build formula and semantic registries plus truth-source-owned declarative IC recipes. A homogeneous truth-source/table block may cover many factors. Split row blocks when their evaluation recipes differ.
- Select exactly one truth source for every selected factor during Stage 1 using the bundled extraction selection standard. The selected source must contain that factor's reported row. Never defer truth selection to data readiness or evaluation, and never select by reproduced metric closeness or local data convenience.
- Keep raw factor definitions separate from evaluation-case transforms, neutralization, return horizons, portfolio rules, and evaluation-required data. Treat Rank-IC mean, ICIR, IC standard deviation, and positive ratio as co-reported metrics of the single `ic_analysis` evaluator type.
- Use `load_recommended_daily_panel(..., price_view="qfq", adjustment_end_date=test_end)` and `price_view="hfq"` sequentially with `/Users/mac/recommended_data_v2` before Quant API v2 or declaring `blocked_by_data`. Run the testing-end-anchored QFQ and initial-baseline HFQ views independently. Complete, persist, and release one scenario before loading the next; do not hand-pick physical files or keep both full views resident by default.
- Read the recommended-data README before Stage 3. Resolve total/A-share/circulating-A/free-float capitalization from paper wording and request it with `market_cap_fields`. Resolve industry taxonomy source and level from paper evidence and pass `IndustryClassificationSelection`; interval history must use `start_date <= evaluation_or_formation_date < cancel_date`. Do not apply QFQ/HFQ multipliers to capitalization, treat industry codes as continuous, or silently choose a taxonomy.
- Use repository loaders for PIT financial statements, valuations/dividends, benchmark levels, historical index constituents/weights, the China exchange calendar, and the government yield curve. Apply `ann_date <= T` before filing-version selection; specify monthly versus daily index weights and yield tenor explicitly; use exchange-calendar `T+h` labels when the paper defines trading-day horizons. Use `$rqdata-fetch-reference` only when the canonical local reference bundle cannot satisfy the exact request.
- Use Quant API v2 only when the recommended local data folder cannot satisfy the paper's required fields/date window.
- Stage 2 must preserve the Stage-1 factor-to-truth selection and recipe without inventing transform defaults. Stage 3 assesses only the selected source, binds semantic concept plus data value state, and marks each transform `apply`, `reuse_materialized`, `blocked_unknown_state`, or `incompatible`. Stage 6 executes that resolved recipe without truth reselection.
- Resolve semantic data fields through declared relationships. Exact aliases, constructed equivalents, accepted proxies, and rejected substitutes must remain distinct; proxies downgrade comparability and stay report-visible, while unmaterialized derivations and unsupported substitutes must not become runtime fields.
- Certify the final factor module and callable as a `FactorImplementationArtifact` on a probe panel; an inline factor column or unimplemented scaffold is not implementation completion.
- Run selected cases through `execute_evaluation_plan(...)`. Keep the full calculation panel separate from evaluation inputs, align artifact factor output only by unique date/security keys, then apply `{metadata["required_global_evaluation_policy_id"]}` before the selected recipe.
- A Stage-6 runner must not end after `export_evaluation_bundle(...)`. After every scenario process has exited, reload all persisted scenario bundles, combine them with `merge_evaluation_bundles(...)`, call `compare_evaluation_bundle_to_paper_truth(...)`, and persist the result with `export_paper_truth_matches(...)`. Then mark Stages 6-7 from those exact artifacts, build the report with `build_paper_reproduction_report(...)`, and finish Stage 8 with `finalize_paper_reproduction_report(...)` so both JSON and Markdown reports contain paper-versus-calculated rows. Never hand-author comparison rows.
- Configure `EvaluationDataContext.resource_config` for full-period runs. Honor resource preflight, required-column projection, incremental hashing, and sequential cases; if projected execution still exceeds budget, require verified partitions instead of silently shortening dates, reducing the universe, or dropping controls.
- Extract factor-exposure missing policy, factor transforms, control transforms, neutralization, and standardization in one ordered recipe. Preserve sequential neutralizations as separate steps. Missing-exposure policy applies only to factor exposure; non-factor missing values use project defaults.
- Retain full otherwise-valid security history for rolling factor calculation. The global policy always excludes ST/PT at signal date and next-exchange-trading-day suspended securities after alignment and before recipe preprocessing. Missing status excludes the row. Record paper disagreement as a project-policy deviation.
- Record `physical_field`, semantic concept, unit, price basis, value space, transform chain, and temporal semantics for bound controls. Recommended capitalization is an unadjusted CNY level; do not apply log when `transform.natural_log` is already materialized.
- Stop only for unresolved factor-definition ambiguity, unavailable formula-required data with no supported construction, or unrecoverable implementation failure. For evaluation-data or evaluator limitations, continue through documented degradation and report deviations.
- Export extraction/spec/pipeline/report artifacts under the repo's Factor Lab runtime paths.
- Use the repository-scoped Codex stage skills routed by `$paper-factor-reproduction`; keep one coordinator responsible for pipeline state and final integration.
- After any interruption, reload and merge valid persisted evaluation bundles before declaring cases deferred. Never erase successful durable execution records because a later scenario, partition, or report step failed.
- Do not switch truth sources to obtain an executable case. Materialize constructible labels and accepted proxies for the Stage-1 selected source; otherwise persist its unsupported/deferred lifecycle. Resource deferral requires persisted preflight evidence or an actual caught resource-budget error, not an assumption from panel size.
- Resource evidence must come from the actual requested panel and a genuine runtime budget. Never pair a probe or reduced frame with full-period metadata, and never set an artificially tiny budget to manufacture a deferral.
- Do not retain full QFQ and HFQ frames together. Profile and release each view during data readiness; during evaluation reload, execute, persist, and release one view before loading the next.
- Wrap every worker-authored long evaluation runner in `scientific_process_lease(worktree, process_name=...)`. Run it in a persistent command session. When a command yields a session or cell identifier, poll that same process with the continuation tool until exit; a tool-call yield deadline is not process termination and must not trigger a restart or deferral. The durable receipt must reach `completed` or `failed` before the completion gate or harvest.
- Before reporting either completion or a hard/interrupted stop, verify that no Python, pytest, or scientific runner still has its current directory inside this worktree. The control plane blocks completed stops and harvesting while such a process exists or while scientific artifacts are changing.
- This automated test is successful only when every selected factor has a durable `executed` evaluation record and a paper-truth result; deferred records alone are not completion.
- Before returning, run the deterministic completion gate below. Persist its output, inspect `earliest_invalid_stage`, `defects`, and `repair_actions`, repair from the earliest invalid gate, and rerun dependent stages plus the deterministic check. You may make up to {metadata["deterministic_gate_max_repair_passes"]} correction passes inside this same attempt. Do not alter the paper protocol or formulas merely to silence a defect. If the gate still fails after the allowed passes or a genuine hard blocker prevents repair, return `incomplete` with the persisted gate output; never return a completion claim while `complete=false`.

```text
{metadata["deterministic_gate_command"]}
```

Required price views recorded by this harness: `{", ".join(metadata["required_price_adjustment_views"])}`.

## Notes

{notes_text}
"""


def _copy_skill_bundle(*, source_skill_path: Path, bundle_root: Path) -> tuple[Path, list[str]]:
    source_skill_dir = source_skill_path.parent
    source_skills_root = source_skill_dir.parent
    skill_names = (DEFAULT_SKILL_NAME, *DEFAULT_STAGE_SKILL_NAMES)
    copied_paths: list[str] = []

    for skill_name in skill_names:
        source_dir = source_skills_root / skill_name
        if skill_name == DEFAULT_SKILL_NAME:
            source_dir = source_skill_dir
        if not (source_dir / "SKILL.md").exists():
            continue
        target_dir = bundle_root / skill_name
        shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)
        copied_paths.append(str(target_dir / "SKILL.md"))

    skill_copy_path = bundle_root / DEFAULT_SKILL_NAME / "SKILL.md"
    return skill_copy_path, copied_paths


def _hash_skill_bundle(bundle_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(bundle_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(bundle_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
