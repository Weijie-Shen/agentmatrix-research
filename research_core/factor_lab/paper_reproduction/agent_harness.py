from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from research_core.factor_lab.runtime import FactorLabWorkspaceConfig, now_iso


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
            "stage_policy": "Proceed through the gated paper reproduction workflow and stop at the correct gate when blocked.",
            "required_price_adjustment_views": ["qfq", "hfq"],
            "qfq_anchor_policy": "per-security cumulative factor at the paper testing-period end",
            "hfq_anchor_policy": "RQData initial cumulative-factor baseline",
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

- Use paper-reported `evaluation_results` only as truth.
- Do not use paper factor-value truth matching.
- Keep raw factor definitions separate from evaluation-case transforms, neutralization, return horizons, portfolio rules, and evaluation-required data.
- Use `load_recommended_daily_panel(..., price_view="qfq", adjustment_end_date=test_end)` and `price_view="hfq"` sequentially with `/Users/mac/recommended_data_v2` before Quant API v2 or declaring `blocked_by_data`. Run the testing-end-anchored QFQ and initial-baseline HFQ views independently. Complete, persist, and release one scenario before loading the next; do not hand-pick physical files or keep both full views resident by default.
- Read the recommended-data README before Stage 3. Resolve total/A-share/circulating-A/free-float capitalization from paper wording and request it with `market_cap_fields`. Resolve industry taxonomy source and level from paper evidence and pass `IndustryClassificationSelection`; interval history must use `start_date <= evaluation_or_formation_date < cancel_date`. Do not apply QFQ/HFQ multipliers to capitalization, treat industry codes as continuous, or silently choose a taxonomy.
- Use repository loaders for PIT financial statements, valuations/dividends, benchmark levels, historical index constituents/weights, the China exchange calendar, and the government yield curve. Apply `ann_date <= T` before filing-version selection; specify monthly versus daily index weights and yield tenor explicitly; use exchange-calendar `T+h` labels when the paper defines trading-day horizons. Use `$rqdata-fetch-reference` only when the canonical local reference bundle cannot satisfy the exact request.
- Use Quant API v2 only when the recommended local data folder cannot satisfy the paper's required fields/date window.
- Preserve all extracted truth sources, profile available data, select the best-supported paper truth before computing metrics, and execute only selected resolved cases.
- Resolve semantic data fields through declared relationships. Exact aliases, constructed equivalents, accepted proxies, and rejected substitutes must remain distinct; proxies downgrade comparability and stay report-visible, while unmaterialized derivations and unsupported substitutes must not become runtime fields.
- Certify the final factor module and callable as a `FactorImplementationArtifact` on a probe panel; an inline factor column or unimplemented scaffold is not implementation completion.
- Run selected cases through `execute_evaluation_plan(...)`. Keep the full calculation panel separate from possibly filtered evaluation inputs, and align artifact factor output only by unique date/security keys.
- Configure `EvaluationDataContext.resource_config` for full-period runs. Honor resource preflight, required-column projection, incremental hashing, and sequential cases; if projected execution still exceeds budget, require verified partitions instead of silently shortening dates, reducing the universe, or dropping controls.
- Extract factor, control, weight, and output transformations in their stated order. Use structured neutralization specs so control transforms such as log, winsorization, and cross-sectional standardization are capability-checked and executed rather than flattened into raw column names.
- Represent calculation and evaluation universes separately. Apply ST/PT, suspension, and future-tradability masks only at their declared evaluation stage unless the paper explicitly requires them during factor calculation.
- Stop only for unresolved factor-definition ambiguity, unavailable formula-required data with no supported construction, or unrecoverable implementation failure. For evaluation-data or evaluator limitations, continue through documented degradation and report deviations.
- Export extraction/spec/pipeline/report artifacts under the repo's Factor Lab runtime paths.
- Use the repository-scoped Codex stage skills routed by `$paper-factor-reproduction`; keep one coordinator responsible for pipeline state and final integration.
- After any interruption, reload and merge valid persisted evaluation bundles before declaring cases deferred. Never erase successful durable execution records because a later scenario, partition, or report step failed.
- Do not finish with zero selected/executed cases while constructible labels, alternative truth, or accepted proxies can make a case executable. Resource deferral requires persisted preflight evidence or an actual caught resource-budget error, not an assumption from panel size.
- Resource evidence must come from the actual requested panel and a genuine runtime budget. Never pair a probe or reduced frame with full-period metadata, and never set an artificially tiny budget to manufacture a deferral.
- Do not retain full QFQ and HFQ frames together. Profile and release each view during data readiness; during evaluation reload, execute, persist, and release one view before loading the next.
- Run long full-panel evaluations in a persistent command session. When a command yields a session or cell identifier, poll that same process with the continuation tool until exit; a tool-call yield deadline is not process termination and must not trigger a restart or deferral.
- This automated test is successful only when every selected factor has a durable `executed` evaluation record and a paper-truth result; deferred records alone are not completion.

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
