from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


EXPECTED_STAGES = (
    "paper_extraction",
    "spec_normalization",
    "input_dataframe_validation",
    "factor_implementation",
    "implementation_tests",
    "evaluation",
    "paper_truth_validation",
    "final_report",
)
COMPLETED_EXECUTION_STATUSES = {"completed", "completed_with_limitations"}
STANDARD_FORMULA_FIELDS = {"open", "high", "low", "close", "vwap", "volume", "amount", "returns"}


@dataclass(slots=True)
class AgentHarnessRunAssessment:
    complete: bool
    worktree: str
    expected_factors: list[str]
    report_json_path: str = ""
    report_markdown_path: str = ""
    implementation_artifact_path: str = ""
    harness_metadata_path: str = ""
    stage_statuses: dict[str, str] = field(default_factory=dict)
    defects: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def assess_agent_harness_run(
    worktree: str | Path,
    *,
    expected_factors: list[str],
    harness_id: str = "",
    report_json_path: str | Path | None = None,
) -> AgentHarnessRunAssessment:
    """Assess completion from persisted artifacts without trusting agent prose."""

    root = Path(worktree).expanduser().resolve()
    runtime_root = root / "runtime" / "factor_lab"
    defects: list[str] = []
    limitations: list[str] = []
    diagnostics: dict[str, Any] = {}

    harness_metadata_path, harness_metadata = _load_harness_metadata(runtime_root, harness_id, defects)
    if harness_metadata:
        recorded_factors = [str(value) for value in harness_metadata.get("selected_factors", []) or []]
        if recorded_factors != list(expected_factors):
            defects.append(
                f"harness selected factors do not match review scope: {recorded_factors} != {expected_factors}"
            )
        _verify_skill_provenance(harness_metadata, defects)

    if report_json_path is not None:
        candidate = Path(report_json_path).expanduser().resolve()
        reports_root = (runtime_root / "reports").resolve()
        if not candidate.is_relative_to(reports_root):
            raise ValueError("explicit report path must be inside the worktree runtime reports directory")
        report_paths = [candidate] if candidate.is_file() else []
    else:
        report_paths = sorted(
            runtime_root.glob("reports/*_paper_reproduction_report.json"),
            key=lambda path: path.stat().st_mtime,
        )
        if harness_metadata_path:
            harness_mtime = harness_metadata_path.stat().st_mtime
            report_paths = [path for path in report_paths if path.stat().st_mtime >= harness_mtime]
    if not report_paths:
        return AgentHarnessRunAssessment(
            complete=False,
            worktree=str(root),
            expected_factors=list(expected_factors),
            harness_metadata_path=str(harness_metadata_path) if harness_metadata_path else "",
            defects=[*defects, "no JSON paper reproduction report was produced"],
        )

    report_path = report_paths[-1]
    markdown_path = report_path.with_suffix(".md")
    if not markdown_path.is_file():
        defects.append("matching Markdown paper reproduction report is missing")

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return AgentHarnessRunAssessment(
            complete=False,
            worktree=str(root),
            expected_factors=list(expected_factors),
            report_json_path=str(report_path),
            report_markdown_path=str(markdown_path) if markdown_path.is_file() else "",
            harness_metadata_path=str(harness_metadata_path) if harness_metadata_path else "",
            defects=[*defects, f"JSON report could not be loaded: {exc}"],
        )

    pipeline = report.get("pipeline", {}) or {}
    stage_statuses: dict[str, str] = {}
    for stage in pipeline.get("stages", []) or []:
        name = str(stage.get("name", ""))
        execution_status = str(stage.get("execution_status") or stage.get("status", ""))
        if name:
            stage_statuses[name] = execution_status
        limitations.extend(str(item) for item in stage.get("limitations", []) or [])

    missing_stages = [name for name in EXPECTED_STAGES if name not in stage_statuses]
    incomplete_stages = [
        name for name in EXPECTED_STAGES if stage_statuses.get(name) not in COMPLETED_EXECUTION_STATUSES
    ]
    if missing_stages:
        defects.append(f"pipeline report is missing stages: {missing_stages}")
    if incomplete_stages:
        defects.append(f"pipeline stages are not completed: {incomplete_stages}")
    if str((report.get("summary", {}) or {}).get("next_stage", "")) != "complete":
        defects.append("report summary does not identify the pipeline as complete")

    factor_records = report.get("factors", []) or []
    actual_factors = [str(record.get("factor_name", "")) for record in factor_records]
    missing_factors = [factor for factor in expected_factors if factor not in actual_factors]
    unexpected_factors = [factor for factor in actual_factors if factor not in expected_factors]
    if missing_factors:
        defects.append(f"report is missing selected factors: {missing_factors}")
    if unexpected_factors:
        defects.append(f"report contains unexpected factors: {unexpected_factors}")
    formula_requirement_defects = _formula_requirement_defects(factor_records)
    defects.extend(formula_requirement_defects)

    factors_without_execution = [
        str(record.get("factor_name", ""))
        for record in factor_records
        if not any(
            str(execution.get("lifecycle_state", "")) == "executed"
            for execution in record.get("evaluation_executions", []) or []
            if isinstance(execution, dict)
        )
    ]
    factors_without_truth_result = [
        str(record.get("factor_name", ""))
        for record in factor_records
        if not (record.get("truth_results", []) or [])
    ]
    if factors_without_execution:
        defects.append(f"selected factors lack executed evaluation records: {factors_without_execution}")
    if factors_without_truth_result:
        defects.append(f"selected factors lack paper-truth results: {factors_without_truth_result}")
    comparison_results = report.get("comparison_results", {}) or {}
    comparison_rows = [
        *(comparison_results.get("primary_metric_rows", []) or []),
        *(comparison_results.get("all_metric_rows", []) or []),
    ]
    if not comparison_rows:
        defects.append("report has no direct paper-versus-calculated metric comparison rows")

    tests_run = report.get("tests_run", []) or []
    if not tests_run:
        defects.append("report does not record tests run")

    implementation_path, implementation_payload = _find_implementation_artifact(runtime_root)
    if not implementation_path:
        defects.append("no FactorImplementationArtifact JSON was found")
    else:
        implemented = set(implementation_payload.get("output_factor_columns", []) or [])
        if not implemented:
            implemented = set((implementation_payload.get("factor_columns_by_id", {}) or {}).values())
        if not implemented:
            implemented = set(implementation_payload.get("implemented_factor_ids", []) or [])
        missing_implemented = [factor for factor in expected_factors if factor not in implemented]
        if missing_implemented:
            defects.append(f"implementation artifact omits selected factors: {missing_implemented}")
        if implementation_payload.get("validation_status") not in COMPLETED_EXECUTION_STATUSES:
            defects.append("implementation artifact is not validated as completed")

    diagnostics.update(
        {
            "report_overall_status": (report.get("summary", {}) or {}).get("overall_status"),
            "pipeline_overall_status": (report.get("summary", {}) or {}).get("pipeline_overall_status"),
            "actual_factors": actual_factors,
            "tests_recorded": len(tests_run),
            "evaluation_execution_counts": (report.get("summary", {}) or {}).get(
                "evaluation_execution_counts", {}
            ),
            "truth_status_counts": (report.get("summary", {}) or {}).get("truth_status_counts", {}),
        }
    )
    return AgentHarnessRunAssessment(
        complete=not defects,
        worktree=str(root),
        expected_factors=list(expected_factors),
        report_json_path=str(report_path),
        report_markdown_path=str(markdown_path) if markdown_path.is_file() else "",
        implementation_artifact_path=str(implementation_path) if implementation_path else "",
        harness_metadata_path=str(harness_metadata_path) if harness_metadata_path else "",
        stage_statuses=stage_statuses,
        defects=defects,
        limitations=_unique(limitations),
        diagnostics=diagnostics,
    )


def _load_harness_metadata(
    runtime_root: Path,
    harness_id: str,
    defects: list[str],
) -> tuple[Path | None, dict[str, Any]]:
    if not harness_id:
        return None, {}
    path = runtime_root / "agent_harness" / harness_id / "harness_metadata.json"
    if not path.is_file():
        defects.append(f"harness metadata is missing for run {harness_id}")
        return None, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        defects.append(f"harness metadata could not be loaded: {exc}")
        return path, {}
    if payload.get("harness_id") != harness_id:
        defects.append("harness metadata id does not match the requested run")
    return path, payload


def _verify_skill_provenance(metadata: dict[str, Any], defects: list[str]) -> None:
    skill_path = Path(str(metadata.get("skill_copy_path", "")))
    expected = str(metadata.get("skill_sha256", ""))
    if not skill_path.is_file():
        defects.append("bundled paper-reproduction skill is missing")
        return
    import hashlib

    actual = hashlib.sha256(skill_path.read_bytes()).hexdigest()
    if not expected or actual != expected:
        defects.append("bundled paper-reproduction skill hash does not match harness metadata")


def _find_implementation_artifact(runtime_root: Path) -> tuple[Path | None, dict[str, Any]]:
    candidates: list[tuple[Path, dict[str, Any]]] = []
    for path in runtime_root.rglob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("schema_version") == "factor_implementation_artifact/v1":
            candidates.append((path, payload))
    if not candidates:
        return None, {}
    return max(candidates, key=lambda item: item[0].stat().st_mtime)


def _formula_requirement_defects(factor_records: list[dict[str, Any]]) -> list[str]:
    defects: list[str] = []
    for record in factor_records:
        formula_tokens = {
            token.lower() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", str(record.get("formula", "")))
        }
        extras = sorted(
            str(field)
            for field in record.get("required_fields", []) or []
            if str(field).lower() in STANDARD_FORMULA_FIELDS and str(field).lower() not in formula_tokens
        )
        if extras:
            defects.append(
                f"factor {record.get('factor_name', '')} has formula-unrelated standard required fields: {extras}"
            )
    return defects


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def main() -> int:
    parser = argparse.ArgumentParser(description="Assess a fresh-agent paper reproduction run.")
    parser.add_argument("worktree")
    parser.add_argument("--factor", action="append", dest="factors", required=True)
    parser.add_argument("--harness-id", default="")
    parser.add_argument("--report-json")
    args = parser.parse_args()
    assessment = assess_agent_harness_run(
        args.worktree,
        expected_factors=args.factors,
        harness_id=args.harness_id,
        report_json_path=args.report_json,
    )
    print(json.dumps(asdict(assessment), ensure_ascii=False, indent=2))
    return 0 if assessment.complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
