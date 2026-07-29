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


def default_skill_path() -> Path:
    """Return the configured Hermes skill path used by local fresh-agent tests."""

    configured = os.environ.get(DEFAULT_SKILL_ENV_VAR, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".hermes" / "skills" / "research" / DEFAULT_SKILL_NAME / "SKILL.md"


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
    skill_dir = root_dir / "skills" / DEFAULT_SKILL_NAME
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_copy_path = skill_dir / "SKILL.md"
    shutil.copyfile(source_skill_path, skill_copy_path)

    skill_text = skill_copy_path.read_text(encoding="utf-8")
    skill_sha256 = hashlib.sha256(skill_text.encode("utf-8")).hexdigest()

    metadata = _metadata_payload(
        request=request,
        root_dir=root_dir,
        skill_copy_path=skill_copy_path,
        source_skill_path=source_skill_path,
        skill_sha256=skill_sha256,
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
    )


def _metadata_payload(
    *,
    request: PaperReproductionAgentHarnessRequest,
    root_dir: Path,
    skill_copy_path: Path,
    source_skill_path: Path,
    skill_sha256: str,
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
            "required_agent_instruction": "Load and follow the bundled paper-factor-reproduction skill before doing reproduction work.",
            "truth_policy": "Use paper-reported evaluation_results only; do not use factor-value truth matching.",
            "stage_policy": "Proceed through the gated paper reproduction workflow and stop at the correct gate when blocked.",
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
- Always use `load_recommended_daily_panel()` with `/Users/mac/recommended_data_v2` before Quant API v2 or declaring `blocked_by_data`; do not hand-pick dated or supplemental files.
- Use Quant API v2 only when the recommended local data folder cannot satisfy the paper's required fields/date window.
- Preserve all extracted truth sources, profile available data, select the best-supported paper truth before computing metrics, and execute only selected resolved cases.
- Stop only for unresolved factor-definition ambiguity, unavailable formula-required data with no supported construction, or unrecoverable implementation failure. For evaluation-data or evaluator limitations, continue through documented degradation and report deviations.
- Export extraction/spec/pipeline/report artifacts under the repo's Factor Lab runtime paths.

## Notes

{notes_text}
"""
