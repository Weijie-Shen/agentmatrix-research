from __future__ import annotations

import argparse
import hashlib
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
    earliest_invalid_stage: str = ""
    repair_actions: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def assess_agent_harness_run(
    worktree: str | Path,
    *,
    expected_factors: list[str],
    harness_id: str = "",
    report_json_path: str | Path | None = None,
    harvest_manifest_path: str | Path | None = None,
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
                f"[scope] harness selected factors do not match review scope: {recorded_factors} != {expected_factors}"
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
        early_defects = [*defects, "[report] no JSON paper reproduction report was produced"]
        earliest, actions = _repair_guidance(early_defects)
        return AgentHarnessRunAssessment(
            complete=False,
            worktree=str(root),
            expected_factors=list(expected_factors),
            harness_metadata_path=str(harness_metadata_path) if harness_metadata_path else "",
            defects=early_defects,
            earliest_invalid_stage=earliest,
            repair_actions=actions,
        )

    report_path = report_paths[-1]
    markdown_path = report_path.with_suffix(".md")
    if not markdown_path.is_file():
        defects.append("[report] matching Markdown paper reproduction report is missing")

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        early_defects = [*defects, f"[report] JSON report could not be loaded: {exc}"]
        earliest, actions = _repair_guidance(early_defects)
        return AgentHarnessRunAssessment(
            complete=False,
            worktree=str(root),
            expected_factors=list(expected_factors),
            report_json_path=str(report_path),
            report_markdown_path=str(markdown_path) if markdown_path.is_file() else "",
            harness_metadata_path=str(harness_metadata_path) if harness_metadata_path else "",
            defects=early_defects,
            earliest_invalid_stage=earliest,
            repair_actions=actions,
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
        defects.append(f"[pipeline] pipeline report is missing stages: {missing_stages}")
    if incomplete_stages:
        defects.append(f"[pipeline] pipeline stages are not completed: {incomplete_stages}")
    if str((report.get("summary", {}) or {}).get("next_stage", "")) != "complete":
        defects.append("[report] report summary does not identify the pipeline as complete")

    defects.extend(_pipeline_artifact_defects(root, report, expected_factors))

    factor_records = report.get("factors", []) or []
    actual_factors = [str(record.get("factor_name", "")) for record in factor_records]
    missing_factors = [factor for factor in expected_factors if factor not in actual_factors]
    unexpected_factors = [factor for factor in actual_factors if factor not in expected_factors]
    if missing_factors:
        defects.append(f"[scope] report is missing selected factors: {missing_factors}")
    if unexpected_factors:
        defects.append(f"[scope] report contains unexpected factors: {unexpected_factors}")
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
        defects.append(f"[evaluation] selected factors lack executed evaluation records: {factors_without_execution}")
    if factors_without_truth_result:
        defects.append(f"[truth] selected factors lack paper-truth results: {factors_without_truth_result}")
    comparison_results = report.get("comparison_results", {}) or {}
    comparison_rows = [
        *(comparison_results.get("primary_metric_rows", []) or []),
        *(comparison_results.get("all_metric_rows", []) or []),
    ]
    if not comparison_rows:
        defects.append("[truth] report has no direct paper-versus-calculated metric comparison rows")

    tests_run = report.get("tests_run", []) or []
    if not tests_run:
        defects.append("[tests] report does not record tests run")

    implementation_path, implementation_payload = _find_implementation_artifact(runtime_root)
    if not implementation_path:
        defects.append("[implementation] no FactorImplementationArtifact JSON was found")
    else:
        implemented = set(implementation_payload.get("output_factor_columns", []) or [])
        if not implemented:
            implemented = set((implementation_payload.get("factor_columns_by_id", {}) or {}).values())
        if not implemented:
            implemented = set(implementation_payload.get("implemented_factor_ids", []) or [])
        missing_implemented = [factor for factor in expected_factors if factor not in implemented]
        if missing_implemented:
            defects.append(f"[implementation] implementation artifact omits selected factors: {missing_implemented}")
        if implementation_payload.get("validation_status") not in COMPLETED_EXECUTION_STATUSES:
            defects.append("[implementation] implementation artifact is not validated as completed")

    defects.extend(
        _deep_completion_defects(
            root=root,
            runtime_root=runtime_root,
            report=report,
            expected_factors=expected_factors,
            harness_metadata=harness_metadata,
            implementation_path=implementation_path,
            implementation_payload=implementation_payload,
            tests_run=tests_run,
            harvest_manifest_path=harvest_manifest_path,
        )
    )
    defects = _unique(defects)
    earliest_invalid_stage, repair_actions = _repair_guidance(defects)

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
            "deterministic_gate_version": "v2",
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
        earliest_invalid_stage=earliest_invalid_stage,
        repair_actions=repair_actions,
        diagnostics=diagnostics,
    )


def _deep_completion_defects(
    *,
    root: Path,
    runtime_root: Path,
    report: dict[str, Any],
    expected_factors: list[str],
    harness_metadata: dict[str, Any],
    implementation_path: Path | None,
    implementation_payload: dict[str, Any],
    tests_run: list[Any],
    harvest_manifest_path: str | Path | None,
) -> list[str]:
    defects: list[str] = []
    extracted_truth_ids_by_factor: dict[str, set[str]] = {}
    extraction_path, extraction = _latest_json_with_any_key(
        runtime_root / "paper_specs", ("factor_definitions", "target_factors")
    )
    specs_path, specs_payload = _latest_json_with_key(runtime_root / "specs", "items")
    pipeline_path, pipeline_payload = _latest_json_with_key(runtime_root / "paper_jobs", "stages")
    evaluation_plan_path, evaluation_plan_payload = _latest_json_with_key(
        runtime_root / "evaluation_plans", "factor_plans"
    )
    truth_path = _latest_json_path(runtime_root / "truth_matches") or _latest_json_path(runtime_root / "truth")
    test_result_paths = sorted((runtime_root / "test_results").glob("**/*")) if (runtime_root / "test_results").exists() else []
    test_result_paths = [path for path in test_result_paths if path.is_file()]

    if not extraction_path:
        defects.append("[extraction] no standalone paper-extraction JSON was found")
    else:
        is_v2 = extraction.get("schema_version") == "paper_extraction.ic_analysis.v2"
        factor_key = "factor_id" if is_v2 else "factor_name"
        factor_collection = "factor_definitions" if is_v2 else "target_factors"
        extraction_factors = {
            str(item.get(factor_key, "")): item
            for item in extraction.get(factor_collection, []) or []
            if isinstance(item, dict)
        }
        if is_v2:
            defects.extend(_v2_extraction_contract_defects(extraction))
        missing = [factor for factor in expected_factors if factor not in extraction_factors]
        if missing:
            defects.append(f"[extraction] extraction omits selected factors: {missing}")
        for factor in expected_factors:
            item = extraction_factors.get(factor, {})
            if not str(item.get("formula", "")).strip():
                defects.append(f"[extraction] {factor} has no extracted formula")
            if is_v2:
                truth_sources = [
                    source
                    for source in extraction.get("truth_sources", []) or []
                    if isinstance(source, dict)
                    and factor in (source.get("reported_results", {}) or {})
                ]
                if not truth_sources:
                    defects.append(f"[extraction] {factor} has no IC-analysis truth source")
                extracted_truth_ids_by_factor[factor] = {
                    str(source.get("truth_source_id", "")) for source in truth_sources
                }
                for source in truth_sources:
                    source_ref = source.get("source", {}) or {}
                    if not source_ref:
                        defects.append(f"[extraction] {factor} truth lacks a narrow source location")
                    results = (source.get("reported_results", {}) or {}).get(factor, {}) or {}
                    if set(results) != set(source.get("reported_metric_ids", []) or []):
                        defects.append(f"[extraction] {factor} truth metrics do not match reported_metric_ids")
            else:
                selected_truth_ids = set(item.get("selected_truth_source_ids", []) or [])
                truth_sources = [source for source in item.get("truth_sources", []) or [] if isinstance(source, dict)]
                selected_sources = [
                    source for source in truth_sources
                    if not selected_truth_ids or str(source.get("truth_id", "")) in selected_truth_ids
                ]
                if not selected_sources:
                    defects.append(f"[extraction] {factor} has no selected evaluation-result truth source")
                extracted_truth_ids_by_factor[factor] = {
                    str(source.get("truth_id", "")) for source in truth_sources
                }
                for source in selected_sources:
                    if source.get("truth_type") != "evaluation_results":
                        defects.append(f"[extraction] {factor} selected non-evaluation truth")
                    if not str(source.get("source_location", "")).strip():
                        defects.append(f"[extraction] {factor} truth lacks a narrow source location")
                    if not isinstance(source.get("metrics"), dict) or not source.get("metrics"):
                        defects.append(f"[extraction] {factor} truth lacks numeric paper metrics")
            if item.get("ambiguous_or_missing_information") or item.get("formula_gap_ids"):
                defects.append(f"[extraction] {factor} retains unresolved extraction ambiguities")

    extraction_stage = _stage_by_name(report, "paper_extraction")
    extraction_diagnostics = extraction_stage.get("diagnostics", {}) or {}
    extraction_validation = extraction_diagnostics.get("status")
    ambiguity_groups = (extraction_diagnostics.get("diagnostics", {}) or {}).get("ambiguities_by_category", {}) or {}
    has_extraction_errors = bool(extraction_diagnostics.get("errors"))
    has_unresolved_ambiguities = any(bool(items) for items in ambiguity_groups.values())
    if extraction_validation == "needs_human_review" and (has_extraction_errors or has_unresolved_ambiguities):
        defects.append("[extraction] extraction validation still requires human review")

    if not specs_path:
        defects.append("[specs] no standalone normalized-spec JSON was found")
    else:
        spec_items = specs_payload.get("items", []) or []
        spec_names = {str(item.get("factor_name", "")) for item in spec_items if isinstance(item, dict)}
        missing = [factor for factor in expected_factors if factor not in spec_names]
        if missing:
            defects.append(f"[specs] normalized specs omit selected factors: {missing}")
        needs_review = [
            str(item.get("factor_name", ""))
            for item in spec_items
            if isinstance(item, dict) and str((item.get("metadata", {}) or {}).get("status", "")) == "needs_human_review"
        ]
        if needs_review:
            defects.append(f"[specs] normalized specs still require human review: {needs_review}")

    if not pipeline_path:
        defects.append("[pipeline] no standalone pipeline state was found")
    else:
        report_job_id = str(report.get("job_id", ""))
        if report_job_id and str(pipeline_payload.get("job_id", "")) != report_job_id:
            defects.append("[pipeline] report and standalone pipeline job IDs do not match")

    profile_paths = sorted((runtime_root / "data_profiles").glob("*.json")) if (runtime_root / "data_profiles").exists() else []
    required_views = [str(view) for view in harness_metadata.get("required_price_adjustment_views", []) or []]
    view_profiles: dict[str, dict[str, Any]] = {}
    for path in profile_paths:
        payload = _load_json(path)
        view = _scenario_from_path_or_payload(path, payload, required_views)
        if view:
            view_profiles[view] = payload
        defects.extend(_data_profile_defects(path, payload, expected_factors))
    if not profile_paths:
        defects.append("[stage3] no standalone Stage 3 data profiles were found")
    missing_views = [view for view in required_views if view not in view_profiles]
    if missing_views:
        defects.append(f"[stage3] required price-view profiles are missing: {missing_views}")
    report_profiles = report.get("data_profile_summaries", []) or []
    if not report_profiles:
        defects.append("[report] final report has no structured data-profile summaries")
    elif any(int(profile.get("row_count", 0) or 0) <= 0 for profile in report_profiles if isinstance(profile, dict)):
        defects.append("[report] final report contains empty or zero-row data-profile summaries")

    embedded_plan = report.get("evaluation_plan", {}) or {}
    if not evaluation_plan_path:
        defects.append("[evaluation-plan] no standalone evaluation plan was found")
        evaluation_plan_payload = embedded_plan if isinstance(embedded_plan, dict) else {}
    if not evaluation_plan_payload:
        defects.append("[evaluation-plan] no usable evaluation plan was found")
    factor_plans = {
        str(item.get("factor_name", "")): item
        for item in evaluation_plan_payload.get("factor_plans", []) or []
        if isinstance(item, dict)
    }
    if not factor_plans and isinstance(embedded_plan, dict):
        factor_plans = {
            str(item.get("factor_name", "")): item
            for item in embedded_plan.get("factor_plans", []) or []
            if isinstance(item, dict)
        }
    selected_ids: dict[str, set[str]] = {}
    for factor in expected_factors:
        factor_plan = factor_plans.get(factor)
        if not factor_plan:
            defects.append(f"[evaluation-lineage] no evaluation plan exists for {factor}")
            selected_ids[factor] = set()
            continue
        assessed = [case for case in factor_plan.get("assessed_evaluation_cases", []) or [] if isinstance(case, dict)]
        selected = [case for case in factor_plan.get("selected_evaluation_cases", []) or [] if isinstance(case, dict)]
        if not assessed:
            defects.append(f"[evaluation-lineage] {factor} has zero assessed evaluation cases")
        if not selected:
            defects.append(f"[evaluation-lineage] {factor} has zero selected evaluation cases")
        extraction_schema = str(extraction.get("schema_version", ""))
        if extraction_schema == "paper_extraction.ic_analysis.v2" and len(selected) > 1:
            defects.append(f"[evaluation-lineage] {factor} selected more than one IC truth source")
        selected_ids[factor] = {
            str(case.get("source_truth_id") or case.get("truth_id") or case.get("truth_case_id") or "")
            for case in selected
        }
        unknown_selected = selected_ids[factor] - extracted_truth_ids_by_factor.get(factor, set())
        if unknown_selected:
            defects.append(
                f"[evaluation-lineage] {factor} selected truth not present in extraction: {sorted(unknown_selected)}"
            )

    if implementation_path:
        module_path = _resolve_artifact_path(root, str(implementation_payload.get("module_path", "")))
        if not module_path or not module_path.is_file():
            defects.append("[implementation] implementation artifact module path is missing")
        elif str(implementation_payload.get("source_hash", "")) != _sha256_file(module_path):
            defects.append("[implementation] implementation artifact source hash does not match its module")
        if not str(implementation_payload.get("callable_import_path", "")).strip():
            defects.append("[implementation] implementation artifact has no callable import path")

    if not test_result_paths:
        defects.append("[tests] no durable implementation-test result artifact was found")
    covered_factors: set[str] = set()
    for test in tests_run:
        if not isinstance(test, dict):
            defects.append("[tests] test records must be structured objects")
            continue
        outcome = str(test.get("outcome", ""))
        command = str(test.get("command", ""))
        if "pytest" in command and (not re.search(r"\bpassed\b", outcome) or re.search(r"\bfailed\b", outcome)):
            defects.append(f"[tests] implementation test did not record a passing outcome: {outcome or '-'}")
        covered_factors.update(str(value) for value in test.get("covered_factors", []) or [])
    missing_test_coverage = [factor for factor in expected_factors if factor not in covered_factors]
    if missing_test_coverage:
        defects.append(f"[tests] no formula-focused test coverage is recorded for: {missing_test_coverage}")

    execution_by_factor: dict[str, list[dict[str, Any]]] = {
        factor: [] for factor in expected_factors
    }
    for factor_record in report.get("factors", []) or []:
        if not isinstance(factor_record, dict):
            continue
        factor = str(factor_record.get("factor_name", ""))
        for execution in factor_record.get("evaluation_executions", []) or []:
            if isinstance(execution, dict) and execution.get("lifecycle_state") == "executed":
                execution_by_factor.setdefault(factor, []).append(execution)
    implementation_hash = str(implementation_payload.get("source_hash", ""))
    scenario_snapshots: dict[str, set[str]] = {}
    for factor in expected_factors:
        executions = execution_by_factor.get(factor, [])
        views = {str(item.get("scenario_id", "")) for item in executions}
        missing = [view for view in required_views if view not in views]
        if missing:
            defects.append(f"[evaluation] {factor} lacks executed required scenarios: {missing}")
        for execution in executions:
            truth_id = str(execution.get("source_truth_id") or execution.get("truth_case_id") or "")
            if selected_ids.get(factor) and truth_id not in selected_ids[factor]:
                defects.append(f"[evaluation-lineage] {factor} executed unselected truth case {truth_id or '-'}")
            if implementation_hash and execution.get("implementation_source_hash") != implementation_hash:
                defects.append(f"[evaluation] {factor} execution did not use the certified implementation hash")
            scenario = str(execution.get("scenario_id", ""))
            scenario_snapshots.setdefault(scenario, set()).add(str(execution.get("data_snapshot_hash", "")))
            defects.extend(_execution_protocol_defects(factor, execution, factor_plans.get(factor, {})))
    if len(required_views) > 1:
        view_hashes = {
            view: next(iter(scenario_snapshots.get(view, set())), "") for view in required_views
        }
        if any(not value for value in view_hashes.values()):
            defects.append("[evaluation] required price views lack durable data snapshot hashes")
        elif len(set(view_hashes.values())) != len(view_hashes):
            defects.append("[evaluation] required price views do not have independent data snapshot hashes")

    defects.extend(_sample_boundary_defects(view_profiles, factor_plans))
    defects.extend(_truth_denominator_defects(report))
    if not truth_path:
        defects.append("[truth] no standalone truth-match artifact was found")
    defects.extend(_markdown_consistency_defects(report, report.get("data_profile_summaries", []) or []))
    if harvest_manifest_path is not None:
        defects.extend(_harvest_durability_defects(harvest_manifest_path))
    return defects


def _pipeline_artifact_defects(root: Path, report: dict[str, Any], expected_factors: list[str]) -> list[str]:
    del expected_factors
    defects: list[str] = []
    for stage in (report.get("pipeline", {}) or {}).get("stages", []) or []:
        if not isinstance(stage, dict):
            continue
        execution_status = str(stage.get("execution_status") or stage.get("status", ""))
        if execution_status not in COMPLETED_EXECUTION_STATUSES:
            continue
        for raw_path in stage.get("artifact_paths", []) or []:
            text = str(raw_path)
            if not text or text.isdigit() or "://" in text:
                continue
            path = _resolve_artifact_path(root, text)
            if path is None or not path.exists():
                defects.append(
                    f"[pipeline] stage {stage.get('name', '-')} cites missing artifact: {text}"
                )
    return defects


def _execution_protocol_defects(
    factor: str,
    execution: dict[str, Any],
    factor_plan: dict[str, Any],
) -> list[str]:
    defects: list[str] = []
    output = execution.get("evaluator_output", {}) or {}
    if execution.get("error") or str(output.get("status", "")) not in {"passed", "completed"}:
        defects.append(f"[evaluation] {factor} has an executed record with an evaluator error")
    skipped_filters = (execution.get("universe_diagnostics", {}) or {}).get("skipped_filters", []) or []
    if skipped_filters:
        names = [str(item.get("filter_name", "")) for item in skipped_filters if isinstance(item, dict)]
        defects.append(f"[protocol] {factor} executed with required universe filters skipped: {names}")
    neutralization = output.get("neutralization_diagnostics", {}) or {}
    skipped_controls = neutralization.get("skipped_controls", []) or []
    if skipped_controls:
        names = [str(item.get("paper_field", "")) for item in skipped_controls if isinstance(item, dict)]
        defects.append(f"[protocol] {factor} executed with neutralization controls skipped: {names}")
    selected_cases = [case for case in factor_plan.get("selected_evaluation_cases", []) or [] if isinstance(case, dict)]
    truth_id = str(execution.get("source_truth_id") or execution.get("truth_case_id") or "")
    selected = next(
        (
            case for case in selected_cases
            if str(case.get("source_truth_id") or case.get("truth_id") or case.get("truth_case_id") or "") == truth_id
        ),
        {},
    )
    selected_protocol = selected.get("resolved_protocol", {}) or selected
    selected_neutralization = selected_protocol.get("neutralization_spec", {}) or {}
    required_controls = selected_neutralization.get("controls", []) or []
    used_controls = neutralization.get("used_controls", []) or []
    if required_controls and len(used_controls) < len(required_controls):
        defects.append(
            f"[protocol] {factor} executed without all selected neutralization controls "
            f"({len(used_controls)}/{len(required_controls)})"
        )
    transform_steps = (selected_protocol.get("transform_spec", {}) or {}).get("steps", []) or []
    if transform_steps and output.get("transform_applied") is not True:
        defects.append(f"[protocol] {factor} executed without its selected transform pipeline")
    return defects


def _truth_denominator_defects(report: dict[str, Any]) -> list[str]:
    defects: list[str] = []
    comparison_results = report.get("comparison_results", {}) or {}
    rows = comparison_results.get("metric_rows", []) or comparison_results.get("all_metric_rows", []) or []
    correct_eligible = sum(
        1
        for row in rows
        if isinstance(row, dict)
        and (row.get("truth_match_eligible") is True or row.get("metric_role") == "truth_match_eligible")
    )
    truth_stage = _stage_by_name(report, "paper_truth_validation")
    diagnostics = truth_stage.get("diagnostics", {}) or {}
    reported = diagnostics.get("eligible_denominator")
    if reported is not None and int(reported or 0) != correct_eligible:
        defects.append(
            f"[truth] reported eligible denominator {reported} does not equal comparison-row denominator {correct_eligible}"
        )
    for factor in report.get("factors", []) or []:
        if not isinstance(factor, dict):
            continue
        diagnostic_metrics = set(factor.get("diagnostic_only_metrics", []) or [])
        for result in factor.get("truth_results", []) or []:
            if not isinstance(result, dict):
                continue
            result_eligible = set((result.get("diagnostics", {}) or {}).get("eligible_metrics", []) or [])
            overlap = sorted(result_eligible & diagnostic_metrics)
            if overlap:
                defects.append(
                    f"[truth] {factor.get('factor_name', '-')} counts diagnostic-only metrics as eligible: {overlap}"
                )
    summary_counts = (report.get("summary", {}) or {}).get("truth_case_counts", {}) or {}
    factor_records = [item for item in report.get("factors", []) or [] if isinstance(item, dict)]
    computed_assessed = sum(len(item.get("assessed_evaluation_cases", []) or []) for item in factor_records)
    computed_selected = sum(len(item.get("selected_evaluation_cases", []) or []) for item in factor_records)
    computed_executed = sum(
        1
        for item in factor_records
        for execution in item.get("evaluation_executions", []) or []
        if isinstance(execution, dict) and execution.get("lifecycle_state") == "executed"
    )
    for key, computed in (
        ("truth_cases_assessed", computed_assessed),
        ("truth_cases_selected", computed_selected),
        ("truth_cases_executed", computed_executed),
    ):
        if key in summary_counts and int(summary_counts.get(key, 0) or 0) != computed:
            defects.append(
                f"[truth] summary {key}={summary_counts.get(key)} does not match persisted factor evidence {computed}"
            )
    return defects


def _data_profile_defects(path: Path, payload: dict[str, Any], expected_factors: list[str]) -> list[str]:
    defects: list[str] = []
    profiles = payload.get("profiles", {}) if isinstance(payload, dict) else {}
    validations = payload.get("validations", {}) if isinstance(payload, dict) else {}
    if profiles:
        missing = [factor for factor in expected_factors if factor not in profiles]
        if missing:
            defects.append(f"[stage3] {path.name} omits factor profiles: {missing}")
        for factor in expected_factors:
            profile = profiles.get(factor, {}) or {}
            if int(profile.get("row_count", 0) or 0) <= 0:
                defects.append(f"[stage3] {path.name} has no full-panel rows for {factor}")
            validation = validations.get(factor, {}) if isinstance(validations, dict) else {}
            if validation and validation.get("valid") is not True:
                defects.append(f"[stage3] {path.name} validation failed for {factor}")
    elif int(payload.get("row_count", 0) or 0) <= 0:
        defects.append(f"[stage3] {path.name} contains no usable profile rows")
    return defects


def _sample_boundary_defects(
    view_profiles: dict[str, dict[str, Any]],
    factor_plans: dict[str, dict[str, Any]],
) -> list[str]:
    defects: list[str] = []
    expected_ranges: set[tuple[str, str]] = set()
    for factor_plan in factor_plans.values():
        for case in factor_plan.get("selected_evaluation_cases", []) or []:
            if not isinstance(case, dict):
                continue
            dates = re.findall(r"\d{4}-\d{2}-\d{2}", str(case.get("sample_period", "")))
            if len(dates) >= 2:
                expected_ranges.add((dates[0], dates[1]))
    if len(expected_ranges) != 1:
        return defects
    expected_start, expected_end = next(iter(expected_ranges))
    for view, payload in view_profiles.items():
        profiles = payload.get("profiles", {}) or {}
        ranges = {
            (str(profile.get("date_min", "")), str(profile.get("date_max", "")))
            for profile in profiles.values()
            if isinstance(profile, dict)
        }
        for actual_start, actual_end in ranges:
            if actual_start and actual_start > expected_start:
                defects.append(
                    f"[stage3] {view} sample starts {actual_start} and does not cover expected start {expected_start}"
                )
            if actual_end and actual_end < expected_end:
                defects.append(
                    f"[stage3] {view} sample ends {actual_end} and does not cover expected end {expected_end}"
                )
    return defects


def _markdown_consistency_defects(
    report: dict[str, Any], data_profile_summaries: list[dict[str, Any]]
) -> list[str]:
    del report
    if data_profile_summaries and all(int(item.get("row_count", 0) or 0) <= 0 for item in data_profile_summaries):
        return ["[report] Markdown data lineage would render only zero-row profiles"]
    return []


def _harvest_durability_defects(path: str | Path) -> list[str]:
    payload = _load_json(Path(path).expanduser().resolve())
    defects: list[str] = []
    if payload.get("review_ready") is not True:
        defects.append("[harvest] harvest manifest is not review-ready")
    missing = payload.get("missing_required_artifact_families", []) or []
    if missing:
        defects.append(f"[harvest] required artifact families were not harvested: {missing}")
    if payload.get("omitted_files"):
        defects.append("[harvest] one or more eligible artifacts were omitted")
    return defects


def _repair_guidance(defects: list[str]) -> tuple[str, list[str]]:
    stage_order = (
        ("paper_extraction", {"extraction", "scope"}),
        ("spec_normalization", {"specs"}),
        ("input_dataframe_validation", {"stage3"}),
        ("factor_implementation", {"implementation"}),
        ("implementation_tests", {"tests"}),
        ("evaluation", {"evaluation-plan", "evaluation-lineage", "evaluation", "protocol"}),
        ("paper_truth_validation", {"truth"}),
        ("final_report", {"pipeline", "report", "harvest", "provenance"}),
    )
    categories = {
        match.group(1)
        for defect in defects
        if (match := re.match(r"\[([^]]+)\]", defect))
    }
    earliest = next((stage for stage, names in stage_order if categories & names), "")
    action_by_category = {
        "extraction": "Correct extraction provenance/ambiguities, renormalize specs, and rerun every dependent gate.",
        "scope": "Reconcile selected-factor names across harness, extraction, specs, implementation, and reports.",
        "specs": "Regenerate normalized specs from the persisted extraction before continuing.",
        "stage3": "Persist full requested-scenario Stage 3 profiles with semantic validations and exact sample boundaries.",
        "implementation": "Rebuild and recertify the importable implementation artifact; verify its source hash.",
        "tests": "Add formula-focused expected-value tests for every selected factor and persist machine-readable test output.",
        "evaluation-plan": "Persist a resolved evaluation plan with assessed and selected lifecycle cases for every factor.",
        "evaluation-lineage": "Rebuild assessed→selected→executed lineage and execute only selected cases.",
        "evaluation": "Rerun every required scenario through the certified implementation and persist successful records.",
        "protocol": "Resolve and apply every required transform, neutralization control, and universe filter before re-execution.",
        "truth": "Rebuild truth matching from executed selected cases and exclude diagnostic-only metrics from denominators.",
        "pipeline": "Reconcile pipeline stage claims and artifact paths with files that actually exist.",
        "report": "Regenerate both final reports from reconciled persisted artifacts after upstream repairs.",
        "harvest": "Produce the missing artifact families before stopping; do not rely on unharvested live files.",
        "provenance": "Regenerate the harness from the committed base and use the exact bundled skill revision.",
    }
    actions = [action_by_category[name] for _, names in stage_order for name in sorted(categories & names)]
    return earliest, _unique(actions)


def _stage_by_name(report: dict[str, Any], name: str) -> dict[str, Any]:
    return next(
        (
            stage for stage in (report.get("pipeline", {}) or {}).get("stages", []) or []
            if isinstance(stage, dict) and stage.get("name") == name
        ),
        {},
    )


def _latest_json_with_key(directory: Path, key: str) -> tuple[Path | None, dict[str, Any]]:
    if not directory.exists():
        return None, {}
    candidates: list[tuple[Path, dict[str, Any]]] = []
    for path in directory.glob("*.json"):
        payload = _load_json(path)
        if key in payload:
            candidates.append((path, payload))
    return max(candidates, key=lambda item: item[0].stat().st_mtime) if candidates else (None, {})


def _latest_json_with_any_key(
    directory: Path,
    keys: tuple[str, ...],
) -> tuple[Path | None, dict[str, Any]]:
    if not directory.exists():
        return None, {}
    candidates: list[tuple[Path, dict[str, Any]]] = []
    for path in directory.glob("*.json"):
        payload = _load_json(path)
        if any(key in payload for key in keys):
            candidates.append((path, payload))
    return max(candidates, key=lambda item: item[0].stat().st_mtime) if candidates else (None, {})


def _find_forbidden_extraction_keys(payload: Any) -> list[str]:
    forbidden = {"local_column", "physical_field", "resolved_field", "selected_truth_source_ids"}
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            found.update(forbidden.intersection(str(key) for key in value))
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return sorted(found)


def _v2_extraction_contract_defects(extraction: dict[str, Any]) -> list[str]:
    defects: list[str] = []
    forbidden = _find_forbidden_extraction_keys(extraction)
    if forbidden:
        defects.append(f"[extraction] v2 immutable evidence contains runtime bindings: {forbidden}")
    registries = {
        "factor": {str(item.get("factor_id", "")) for item in extraction.get("factor_definitions", []) or []},
        "semantic": {
            str(item.get("semantic_field_id", "")) for item in extraction.get("semantic_requirements", []) or []
        },
        "universe": {
            str(item.get("universe_protocol_id", "")) for item in extraction.get("universe_protocols", []) or []
        },
        "sample": {str(item.get("sample_period_id", "")) for item in extraction.get("sample_periods", []) or []},
        "pipeline": {
            str(item.get("operation_pipeline_id", "")) for item in extraction.get("operation_pipelines", []) or []
        },
        "metric": {str(item.get("metric_id", "")) for item in extraction.get("metric_definitions", []) or []},
        "protocol": {str(item.get("protocol_id", "")) for item in extraction.get("ic_protocols", []) or []},
    }
    for factor in extraction.get("factor_definitions", []) or []:
        missing = set(factor.get("required_semantic_fields", []) or []) - registries["semantic"]
        if missing:
            defects.append(f"[extraction] {factor.get('factor_id', '-')} references unknown semantics: {sorted(missing)}")
    for protocol in extraction.get("ic_protocols", []) or []:
        refs = {
            "sample": protocol.get("sample_period_id"),
            "pipeline": protocol.get("operation_pipeline_id"),
            "universe": protocol.get("universe_protocol_id")
            or (extraction.get("ic_analysis_contract", {}) or {}).get("universe_protocol_id"),
        }
        for registry, ref in refs.items():
            if str(ref or "") not in registries[registry]:
                defects.append(
                    f"[extraction] protocol {protocol.get('protocol_id', '-')} references unknown {registry}: {ref}"
                )
    for source in extraction.get("truth_sources", []) or []:
        if str(source.get("protocol_id", "")) not in registries["protocol"]:
            defects.append(
                f"[extraction] truth {source.get('truth_source_id', '-')} references unknown IC protocol"
            )
        missing_metrics = set(source.get("reported_metric_ids", []) or []) - registries["metric"]
        missing_factors = set((source.get("reported_results", {}) or {})) - registries["factor"]
        if missing_metrics:
            defects.append(
                f"[extraction] truth {source.get('truth_source_id', '-')} references unknown metrics: {sorted(missing_metrics)}"
            )
        if missing_factors:
            defects.append(
                f"[extraction] truth {source.get('truth_source_id', '-')} references unknown factors: {sorted(missing_factors)}"
            )
    return defects


def _latest_json_path(directory: Path) -> Path | None:
    paths = [path for path in directory.glob("*.json") if path.is_file()] if directory.exists() else []
    return max(paths, key=lambda path: path.stat().st_mtime) if paths else None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_artifact_path(root: Path, value: str) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _scenario_from_path_or_payload(path: Path, payload: dict[str, Any], required_views: list[str]) -> str:
    candidates = [path.stem.lower(), str(payload.get("scenario_id", "")).lower()]
    for view in required_views:
        if any(re.search(rf"(?:^|[_-]){re.escape(view.lower())}(?:$|[_-])", value) for value in candidates):
            return view
    return ""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_harness_metadata(
    runtime_root: Path,
    harness_id: str,
    defects: list[str],
) -> tuple[Path | None, dict[str, Any]]:
    if not harness_id:
        return None, {}
    path = runtime_root / "agent_harness" / harness_id / "harness_metadata.json"
    if not path.is_file():
        defects.append(f"[provenance] harness metadata is missing for run {harness_id}")
        return None, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        defects.append(f"[provenance] harness metadata could not be loaded: {exc}")
        return path, {}
    if payload.get("harness_id") != harness_id:
        defects.append("[provenance] harness metadata id does not match the requested run")
    return path, payload


def _verify_skill_provenance(metadata: dict[str, Any], defects: list[str]) -> None:
    skill_path = Path(str(metadata.get("skill_copy_path", "")))
    expected = str(metadata.get("skill_sha256", ""))
    if not skill_path.is_file():
        defects.append("[provenance] bundled paper-reproduction skill is missing")
        return
    import hashlib

    actual = hashlib.sha256(skill_path.read_bytes()).hexdigest()
    if not expected or actual != expected:
        defects.append("[provenance] bundled paper-reproduction skill hash does not match harness metadata")


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
                f"[extraction] factor {record.get('factor_name', '')} has formula-unrelated standard required fields: {extras}"
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
    parser.add_argument("--harvest-manifest")
    parser.add_argument("--output")
    args = parser.parse_args()
    assessment = assess_agent_harness_run(
        args.worktree,
        expected_factors=args.factors,
        harness_id=args.harness_id,
        report_json_path=args.report_json,
        harvest_manifest_path=args.harvest_manifest,
    )
    serialized = json.dumps(asdict(assessment), ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    print(serialized)
    return 0 if assessment.complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
