from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from contracts.factor_research import FactorResearchSpec
from research_core.factor_lab.paper_reproduction.extraction import ICAnalysisPaperExtraction, PaperExtraction
from research_core.factor_lab.paper_reproduction.paper_evaluation import PaperEvaluationPlan
from research_core.factor_lab.paper_reproduction.pipeline import (
    PaperReproductionPipelineState,
    export_pipeline_state,
)
from research_core.factor_lab.runtime import FactorLabWorkspaceConfig, now_iso


def build_paper_reproduction_report(
    *,
    job_id: str,
    extraction: PaperExtraction | ICAnalysisPaperExtraction,
    specs: list[FactorResearchSpec],
    pipeline_state: PaperReproductionPipelineState | None = None,
    evaluation_plan: PaperEvaluationPlan | None = None,
    evaluation_bundle: object | None = None,
    evaluation_report: dict[str, Any] | None = None,
    data_profiles: dict[str, object] | None = None,
    truth_results: dict[str, list[dict[str, Any]]] | None = None,
    artifacts: dict[str, str] | None = None,
    tests_run: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _validate_stage3_support_consistency(pipeline_state, evaluation_plan)
    truth_results = truth_results or {}
    spec_by_name = {spec.factor_name: spec for spec in specs}
    evaluation_plan_by_name = {
        plan.factor_name: plan
        for plan in (evaluation_plan.factor_plans if evaluation_plan else [])
    }
    evaluation_bundle_payload = _as_plain_dict(evaluation_bundle)
    data_profile_payload = {
        str(profile_id): _as_plain_dict(profile)
        for profile_id, profile in (data_profiles or {}).items()
    }
    execution_records = [
        record
        for record in evaluation_bundle_payload.get("records", []) or []
        if isinstance(record, dict)
    ]
    factors = []
    status_counts: dict[str, int] = {}
    truth_status_counts: dict[str, int] = {}
    for factor in _extraction_factor_views(extraction, specs):
        factor_name = str(factor["factor_name"])
        spec = spec_by_name.get(factor_name)
        spec_metadata = dict(spec.metadata) if spec else {}
        factor_evaluation_plan = _as_plain_dict(evaluation_plan_by_name.get(factor_name))
        factor_truth_results = truth_results.get(factor_name, [])
        for item in factor_truth_results:
            status = str(item.get("status", "unknown"))
            truth_status_counts[status] = truth_status_counts.get(status, 0) + 1
        selected_cases = factor_evaluation_plan.get("selected_evaluation_cases", [])
        selected_truth = selected_cases[0] if selected_cases else {}
        selected_truth_id = str(
            selected_truth.get("source_truth_id")
            or selected_truth.get("truth_id")
            or (factor["selected_truth_source_ids"][0] if factor["selected_truth_source_ids"] else "")
        )
        selected_truth_reason = str(
            selected_truth.get("selection_reason") or factor["truth_selection_rule"] or ""
        )
        selected_truth_source = next(
            (
                source
                for source in factor["truth_sources"]
                if str(source.get("truth_source_id") or source.get("truth_id", "")) == selected_truth_id
            ),
            {},
        )
        data_requirement_assessments, data_replacements = _collect_data_assessments(factor_evaluation_plan)
        factor_status = str(spec_metadata.get("status", "extracted_only"))
        status_counts[factor_status] = status_counts.get(factor_status, 0) + 1
        factors.append(
            {
                "factor_name": factor_name,
                "formula": factor["formula"],
                "required_fields": list(factor["required_fields"]),
                "frequency": factor["frequency"],
                "sample_period": factor["sample_period"],
                "universe": factor["universe"],
                "truth_sources": list(factor["truth_sources"]),
                "evaluation_cases": list(factor["truth_sources"]),
                "assessed_evaluation_cases": factor_evaluation_plan.get("assessed_evaluation_cases", []),
                "selected_evaluation_cases": selected_cases,
                "skipped_evaluation_cases": factor_evaluation_plan.get("skipped_evaluation_cases", []),
                "unsupported_evaluation_cases": factor_evaluation_plan.get("unsupported_evaluation_cases", []),
                "deferred_evaluation_cases": factor_evaluation_plan.get("deferred_evaluation_cases", []),
                "selected_truth_id": selected_truth_id,
                "selected_truth_reason": selected_truth_reason,
                "selected_truth_source": selected_truth_source,
                "comparability": selected_truth.get("comparability", ""),
                "deviations": selected_truth.get("deviations", []),
                "truth_match_eligible_metrics": selected_truth.get("truth_match_eligible_metrics", []),
                "diagnostic_only_metrics": selected_truth.get("diagnostic_only_metrics", []),
                "case_executable": selected_truth.get("case_executable") if selected_truth else None,
                "data_requirement_assessments": data_requirement_assessments,
                "data_replacements": data_replacements,
                "requires_paper_local_evaluator": factor_evaluation_plan.get("requires_paper_local_evaluator", False),
                "evaluator_implementation_targets": factor_evaluation_plan.get("evaluator_implementation_targets", []),
                "defaulted_transform_assumptions": _factor_defaulted_transform_assumptions(
                    spec_metadata,
                    factor_evaluation_plan,
                ),
                "truth_results": factor_truth_results,
                "evaluation_executions": [
                    record for record in execution_records if record.get("factor_name") == factor_name
                ],
                "spec_status": factor_status,
                "data_requirements": spec_metadata.get("data_requirements", {}),
                "known_limitations": spec_metadata.get("known_limitations", list(factor["known_limitations"])),
                "spec_metadata": spec_metadata,
                "ambiguities": spec_metadata.get("factor_ambiguities_by_category", {}),
            }
        )

    pipeline_payload = _pipeline_payload(pipeline_state)
    selected_truth_sources = _selected_truth_source_summaries(factors)
    comparison_results = _build_metric_comparison_results(factors)
    comparison_summary = comparison_results.get("summary", {})
    overall_status = _resolve_overall_status(pipeline_payload, status_counts, truth_status_counts)
    truth_case_counts = _truth_case_counts(factors, truth_results)
    data_requirement_counts = _data_requirement_counts(factors)
    resource_preflight = evaluation_bundle_payload.get("resource_preflight", {}) or {}
    resource_telemetry = evaluation_bundle_payload.get("resource_telemetry", {}) or {}
    resource_adaptations = evaluation_bundle_payload.get("resource_adaptations", []) or []
    methodological_deviations = evaluation_bundle_payload.get("methodological_deviations", []) or []
    return {
        "job_id": job_id,
        "generated_at": now_iso(),
        "paper": _paper_report_metadata(extraction),
        "summary": {
            "overall_status": overall_status,
            "factor_count": len(factors),
            "spec_status_counts": status_counts,
            "truth_status_counts": truth_status_counts,
            "truth_case_counts": truth_case_counts,
            "data_requirement_counts": data_requirement_counts,
            "data_replacement_count": sum(len(factor.get("data_replacements", [])) for factor in factors),
            "evaluation_execution_counts": _execution_lifecycle_counts(execution_records),
            "evaluation_filter_rows_removed": sum(
                int((record.get("universe_diagnostics", {}) or {}).get("removed_rows", 0) or 0)
                for record in execution_records
            ),
            "evaluation_execution_mode": resource_preflight.get("execution_mode", ""),
            "measured_process_peak_rss_bytes": resource_telemetry.get("measured_process_peak_rss_bytes"),
            "resource_adaptation_count": len(resource_adaptations),
            "methodological_deviation_count": len(methodological_deviations),
            "raw_factor_before_evaluation_filters": evaluation_bundle_payload.get(
                "raw_factor_before_evaluation_filters"
            ),
            "truth_match_pass_rate": _truth_match_pass_rate(truth_case_counts),
            "selected_truth_source_count": len(selected_truth_sources),
            "metric_comparison_count": len(comparison_results.get("metric_rows", [])),
            "rank_ic_comparison_summary": comparison_summary.get("primary_metric", {}),
            "metric_comparison_summary": comparison_summary.get("all_metrics", {}),
            "pipeline_overall_status": pipeline_payload.get("overall_status"),
            "next_stage": pipeline_payload.get("next_stage"),
            "proof_language_note": "Do not claim full reproduction, zero bias, or passed proof unless evaluation-result truth checks pass under the agreed policy.",
        },
        "pipeline": pipeline_payload,
        "evaluation_plan": _as_plain_dict(evaluation_plan) if evaluation_plan else {},
        "evaluation_bundle": evaluation_bundle_payload,
        "resource_execution": {
            "preflight": resource_preflight,
            "telemetry": resource_telemetry,
            "resource_adaptations": resource_adaptations,
            "methodological_deviations": methodological_deviations,
            "requested_execution": evaluation_bundle_payload.get("requested_execution", {}) or {},
            "executed_execution": evaluation_bundle_payload.get("executed_execution", {}) or {},
            "raw_factor_before_evaluation_filters": evaluation_bundle_payload.get(
                "raw_factor_before_evaluation_filters"
            ),
        },
        "evaluation_report": evaluation_report or {},
        "data_profiles": data_profile_payload,
        "data_profile_summaries": _data_profile_summaries(data_profile_payload),
        "selected_truth_sources": selected_truth_sources,
        "comparison_results": comparison_results,
        "factors": factors,
        "artifacts": artifacts or {},
        "tests_run": tests_run or [],
        "known_gaps": _collect_known_gaps(factors, pipeline_payload),
    }


def _validate_stage3_support_consistency(
    pipeline_state: PaperReproductionPipelineState | None,
    evaluation_plan: PaperEvaluationPlan | None,
) -> None:
    if pipeline_state is None or evaluation_plan is None:
        return
    stage = next(
        (
            item
            for item in pipeline_state.stages
            if item.name == "input_dataframe_validation"
        ),
        None,
    )
    if stage is None:
        return
    expected = stage.diagnostics.get("support_assessment_ids")
    if not isinstance(expected, dict) or not expected:
        return
    actual: dict[str, dict[str, str]] = {}
    for factor_plan in evaluation_plan.factor_plans:
        factor_assessments: dict[str, str] = {}
        for case in factor_plan.assessed_evaluation_cases:
            assessment = dict(case.get("support_assessment", {}) or {})
            truth_id = str(case.get("truth_id") or case.get("truth_case_id") or "")
            assessment_id = str(assessment.get("assessment_id", "") or "")
            if truth_id and assessment_id:
                factor_assessments[truth_id] = assessment_id
        if factor_assessments:
            actual[factor_plan.factor_name] = factor_assessments
    if actual != expected:
        raise ValueError(
            "evaluation plan support assessments contradict durable Stage-3 state; "
            "reassess support and persist the new authoritative assessment before reporting"
        )


def _display_author(author: Any) -> str:
    if isinstance(author, dict):
        return str(author.get("name") or author.get("author") or author.get("display_name") or "-")
    return str(author)


def render_paper_reproduction_report_markdown(report: dict[str, Any]) -> str:
    paper = report["paper"]
    summary = report["summary"]
    lines = [
        "# Paper Factor Reproduction Report",
        "",
        f"- Job ID: {report['job_id']}",
        f"- Generated at: {report['generated_at']}",
        f"- Paper: {paper['title']}",
        f"- Paper ID: {paper['paper_id']}",
        f"- Authors: {', '.join(_display_author(author) for author in paper['authors']) if paper['authors'] else '-'}",
        f"- Source: {paper.get('source') or '-'}",
        f"- Year: {paper.get('year') or '-'}",
        f"- Factor family: {paper['factor_family_name']}",
        f"- Overall status: {summary['overall_status']}",
        f"- Truth match pass rate: {summary.get('truth_match_pass_rate') or '-'}",
        f"- Next stage: {summary.get('next_stage') or '-'}",
        "",
        f"> {summary['proof_language_note']}",
        "",
        "## Selected Truth Sources",
        "",
    ]
    selected_truth_sources = report.get("selected_truth_sources", []) or []
    if selected_truth_sources:
        lines.extend(
            [
                "| Factor | Selected Truth ID | Source Location | Evaluation Method | Sample Period | Paper Metrics |",
                "|---|---|---|---|---|---|",
            ]
        )
        for selection in selected_truth_sources:
            lines.append(
                f"| {_md_cell(selection.get('factor_name'))} | "
                f"{_md_cell(selection.get('truth_id'))} | "
                f"{_md_cell(selection.get('source_location'))} | "
                f"{_md_cell(selection.get('evaluation_method'))} | "
                f"{_md_cell(selection.get('sample_period'))} | "
                f"{_md_cell(_format_metrics(selection.get('paper_metrics', {})))} |"
            )
        lines.extend(["", "Selection rationale:", ""])
        for selection in selected_truth_sources:
            lines.append(
                f"- **{_md_cell(selection.get('factor_name'))}** chose "
                f"`{_md_cell(selection.get('truth_id'))}` because "
                f"{_md_cell(selection.get('selection_reason') or 'no reason was recorded')}. "
                f"Comparability: `{_md_cell(selection.get('comparability') or '-')}`."
            )
    else:
        lines.append("- No selected paper evaluation truth source was recorded.")

    lines.extend(["", "## Data Selections and Coverage", ""])
    data_profile_summaries = report.get("data_profile_summaries", []) or []
    if data_profile_summaries:
        lines.extend(
            [
                "| Profile | Coverage | Rows | Price View | Capitalization / Industry | PIT Financial / Valuation | Reference / Label Selection | Limitations |",
                "|---|---|---:|---|---|---|---|---|",
            ]
        )
        for profile in data_profile_summaries:
            lines.append(
                f"| {_md_cell(profile.get('source_id'))} | {_md_cell(profile.get('coverage'))} | "
                f"{profile.get('row_count', 0)} | {_md_cell(profile.get('price_adjustment') or '-')} | "
                f"{_md_cell(_capitalization_industry_label(profile))} | "
                f"{_md_cell(_pit_valuation_label(profile))} | "
                f"{_md_cell(_reference_label(profile))} | "
                f"{_md_cell('; '.join(profile.get('limitations', [])) or '-')} |"
            )
    else:
        lines.append("- No structured data profiles were supplied to the report.")

    lines.extend(["", "## Paper vs Calculated Results", ""])
    comparisons = report.get("comparison_results", {}) or {}
    comparison_summary = comparisons.get("summary", {}) or {}
    primary_metric = str(comparisons.get("primary_metric") or "")
    primary_summary = comparison_summary.get("primary_metric", {}) or {}
    primary_rows = comparisons.get("primary_metric_rows", []) or []
    if primary_rows:
        lines.append(f"### {_metric_label(primary_metric)} Summary")
        lines.append("")
        lines.append(f"- Comparisons: {primary_summary.get('comparison_count', 0)}")
        lines.append(
            "- Median absolute percentage error: "
            f"{_format_percentage(primary_summary.get('median_absolute_percentage_error'))}"
        )
        lines.append(
            "- Mean absolute percentage error: "
            f"{_format_percentage(primary_summary.get('mean_absolute_percentage_error'))}"
        )
        lines.append(f"- Mean absolute error: {_format_number(primary_summary.get('mean_absolute_error'))}")
        lines.append(f"- RMSE: {_format_number(primary_summary.get('root_mean_squared_error'))}")
        lines.append(
            f"- Sign agreement: {_format_percentage(primary_summary.get('sign_agreement_rate'))}"
        )
        lines.append(
            f"- Paper/calculated correlation: {_format_number(primary_summary.get('pearson_correlation'))}"
        )
        by_scenario = comparison_summary.get("primary_metric_by_scenario", {}) or {}
        if by_scenario:
            lines.extend(
                [
                    "",
                    "| Scenario | Comparisons | Median Absolute % Error | Mean Absolute % Error | MAE | RMSE | Sign Agreement | Pearson r |",
                    "|---|---:|---:|---:|---:|---:|---:|---:|",
                ]
            )
            for scenario, scenario_summary in by_scenario.items():
                lines.append(
                    f"| {_md_cell(scenario)} | {scenario_summary.get('comparison_count', 0)} | "
                    f"{_format_percentage(scenario_summary.get('median_absolute_percentage_error'))} | "
                    f"{_format_percentage(scenario_summary.get('mean_absolute_percentage_error'))} | "
                    f"{_format_number(scenario_summary.get('mean_absolute_error'))} | "
                    f"{_format_number(scenario_summary.get('root_mean_squared_error'))} | "
                    f"{_format_percentage(scenario_summary.get('sign_agreement_rate'))} | "
                    f"{_format_number(scenario_summary.get('pearson_correlation'))} |"
                )
        lines.extend(
            [
                "",
                f"### {_metric_label(primary_metric)} by Factor and Scenario",
                "",
                "| Factor | Scenario | Truth Source | Paper | Calculated | Signed Error | Absolute % Error | Truth Status | Comparability |",
                "|---|---|---|---:|---:|---:|---:|---|---|",
            ]
        )
        for row in primary_rows:
            lines.append(
                f"| {_md_cell(row.get('factor_name'))} | {_md_cell(row.get('scenario_id'))} | "
                f"{_md_cell(row.get('truth_id'))} ({_md_cell(row.get('source_location'))}) | "
                f"{_format_number(row.get('paper_value'))} | {_format_number(row.get('calculated_value'))} | "
                f"{_format_number(row.get('signed_error'))} | "
                f"{_format_percentage(row.get('absolute_percentage_error'))} | "
                f"{_md_cell(row.get('truth_status'))} | {_md_cell(row.get('comparability'))} |"
            )
    else:
        lines.append("- No executed paper-versus-calculated metric comparisons were available.")

    other_metric_rows = [
        row for row in comparisons.get("metric_rows", []) or [] if row.get("metric") != primary_metric
    ]
    if other_metric_rows:
        lines.extend(
            [
                "",
                "### Other Compared Paper Metrics",
                "",
                "| Factor | Scenario | Metric | Paper | Calculated | Signed Error | Absolute % Error | Truth Status | Metric Role |",
                "|---|---|---|---:|---:|---:|---:|---|---|",
            ]
        )
        for row in other_metric_rows:
            lines.append(
                f"| {_md_cell(row.get('factor_name'))} | {_md_cell(row.get('scenario_id'))} | "
                f"{_md_cell(_metric_label(str(row.get('metric') or '')))} | "
                f"{_format_number(row.get('paper_value'))} | {_format_number(row.get('calculated_value'))} | "
                f"{_format_number(row.get('signed_error'))} | "
                f"{_format_percentage(row.get('absolute_percentage_error'))} | "
                f"{_md_cell(row.get('truth_status'))} | {_md_cell(row.get('metric_role'))} |"
            )

    lines.extend(
        [
            "",
        "## Factors",
        "",
        "| Factor | Spec Status | Frequency | Required Fields | Evaluation Truth |",
        "|---|---|---|---|---|",
        ]
    )
    for factor in report["factors"]:
        truth_sources = factor.get("truth_sources", [])
        truth_labels = []
        for truth in truth_sources:
            truth_labels.append(f"{truth.get('truth_id', '-')}: {truth.get('source_location', '-')}")
        lines.append(
            f"| {factor['factor_name']} | {factor.get('spec_status', '-')} | {factor.get('frequency') or '-'} | "
            f"{', '.join(factor.get('required_fields', [])) or '-'} | {', '.join(truth_labels) or '-'} |"
        )
    lines.extend(["", "## Evaluation Truth", ""])
    for factor in report["factors"]:
        lines.append(f"### {factor['factor_name']}")
        lines.append("")
        lines.append(f"- Selected truth: {factor.get('selected_truth_id') or '-'}")
        lines.append(f"- Selection reason: {factor.get('selected_truth_reason') or '-'}")
        lines.append(f"- Comparability: {factor.get('comparability') or '-'}")
        lines.append(f"- Eligible metrics: {', '.join(factor.get('truth_match_eligible_metrics', [])) or '-'}")
        lines.append(f"- Diagnostic-only metrics: {', '.join(factor.get('diagnostic_only_metrics', [])) or '-'}")
        truth_sources = factor.get("truth_sources", [])
        if not truth_sources:
            lines.append("- Paper evaluation truth: missing")
        for truth in truth_sources:
            metrics = truth.get("metrics", {})
            lines.append(
                f"- Truth source `{truth.get('truth_id', '-')}` ({truth.get('source_location', '-')}): "
                f"{_format_metrics(metrics)}"
            )
        truth_results = factor.get("truth_results", [])
        if truth_results:
            for result in truth_results:
                lines.append(
                    f"- Match result `{result.get('truth_id', '-')}`: {result.get('status', '-')} "
                    f"({result.get('diagnostics', {}).get('quality', '-')})"
                )
        for execution in factor.get("evaluation_executions", []):
            universe = execution.get("universe_diagnostics", {}) or {}
            lines.append(
                f"- Evaluation execution `{execution.get('execution_id', '-')}`: "
                f"{execution.get('lifecycle_state', '-')} via "
                f"{(execution.get('evaluator_output', {}) or {}).get('execution_mode', '-')}"
            )
            for applied_filter in universe.get("applied_filters", []) or []:
                lines.append(
                    f"  - Filter `{applied_filter.get('filter_name', '-')}` at "
                    f"`{applied_filter.get('application_stage', '-')}` removed "
                    f"{applied_filter.get('removed_rows', 0)} rows."
                )
        deviations = factor.get("deviations", [])
        for deviation in deviations:
            lines.append(
                f"- Deviation `{deviation.get('category', '-')}`: {deviation.get('paper_value', '-')} -> "
                f"{deviation.get('resolved_value', '-')} ({deviation.get('severity', '-')})"
            )
        for replacement in factor.get("data_replacements", []):
            lines.append(
                f"- Data replacement `{replacement.get('paper_definition', '-')}` -> "
                f"`{replacement.get('replacement_field') or '-'}`: {replacement.get('status', '-')} "
                f"({replacement.get('relationship', '-')})"
            )
        lines.append("")
    lines.extend(["## Selected Evaluation Methods", ""])
    for factor in report["factors"]:
        lines.append(f"### {factor['factor_name']}")
        selected_cases = factor.get("selected_evaluation_cases", [])
        if selected_cases:
            for case in selected_cases:
                lines.append(
                    f"- Selected `{case.get('truth_id', '-')}`: {case.get('evaluation_family', '-')} "
                    f"({case.get('comparability', 'exact')})"
                )
        else:
            lines.append("- None selected for generic execution.")
        skipped_cases = factor.get("skipped_evaluation_cases", [])
        for case in skipped_cases:
            lines.append(
                f"- Skipped `{case.get('truth_id', '-')}`: {case.get('evaluation_family', '-')} "
                f"({case.get('skip_reason', '-')})"
            )
        targets = factor.get("evaluator_implementation_targets", [])
        for target in targets:
            lines.append(
                f"- Paper-local evaluator needed for `{target.get('evaluation_family', '-')}`: "
                f"`{target.get('suggested_function_name', '-')}`"
            )
        lines.append("")
    lines.extend(["## Truth Case Coverage", ""])
    counts = report.get("summary", {}).get("truth_case_counts", {})
    if counts:
        lines.extend(f"- {key}: {value}" for key, value in counts.items())
    else:
        lines.append("- No truth case counts recorded.")
    lines.append("")
    lines.extend(["## Resource Execution", ""])
    resource_execution = report.get("resource_execution", {}) or {}
    preflight = resource_execution.get("preflight", {}) or {}
    telemetry = resource_execution.get("telemetry", {}) or {}
    if preflight:
        lines.append(f"- Execution mode: {preflight.get('execution_mode', '-')}")
        lines.append(f"- Memory budget bytes: {preflight.get('memory_budget_bytes') or '-'}")
        lines.append(
            f"- Estimated projected peak bytes: {preflight.get('estimated_projected_peak_bytes') or '-'}"
        )
        lines.append(
            f"- Measured process peak RSS bytes: {telemetry.get('measured_process_peak_rss_bytes') or '-'}"
        )
        lines.append(
            "- Raw factors calculated before evaluation filters: "
            f"{resource_execution.get('raw_factor_before_evaluation_filters')}"
        )
        lines.append(f"- Requested execution: {_format_metrics(resource_execution.get('requested_execution', {}))}")
        lines.append(f"- Executed execution: {_format_metrics(resource_execution.get('executed_execution', {}))}")
        for adaptation in resource_execution.get("resource_adaptations", []) or []:
            lines.append(f"- Methodology-preserving resource adaptation: {adaptation}")
        deviations = resource_execution.get("methodological_deviations", []) or []
        if deviations:
            lines.extend(f"- Methodological deviation: {deviation}" for deviation in deviations)
        else:
            lines.append("- Methodological deviations: none")
    else:
        lines.append("- No resource preflight was supplied.")
    lines.append("")
    lines.extend(["## Defaulted Transform Assumptions", ""])
    defaulted_any = False
    for factor in report["factors"]:
        assumptions = factor.get("defaulted_transform_assumptions", [])
        if assumptions:
            defaulted_any = True
            lines.append(f"- {factor['factor_name']}: {', '.join(assumptions)}")
    if not defaulted_any:
        lines.append("- None recorded.")
    lines.append("")
    lines.extend(["## Pipeline", ""])
    pipeline = report.get("pipeline", {})
    stages = pipeline.get("stages", []) if isinstance(pipeline, dict) else []
    if stages:
        lines.extend(
            [
                "| Stage | Execution Status | Truth Status | Summary |",
                "|---|---|---|---|",
            ]
        )
        for stage in stages:
            lines.append(
                f"| {_md_cell(stage.get('name'))} | "
                f"{_md_cell(stage.get('execution_status') or stage.get('status'))} | "
                f"{_md_cell(stage.get('truth_validation_status') or '-')} | "
                f"{_md_cell(stage.get('summary') or '-')} |"
            )
    else:
        lines.append("No pipeline state was supplied.")
    lines.extend(["", "## Known Gaps", ""])
    gaps = report.get("known_gaps", [])
    if gaps:
        lines.extend(f"- {gap}" for gap in gaps)
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Tests Run", ""])
    tests_run = report.get("tests_run", []) or []
    if tests_run:
        lines.extend(["| Test or Command | Outcome |", "|---|---|"])
        for test in tests_run:
            if isinstance(test, dict):
                command = test.get("command") or test.get("name") or test.get("test") or "-"
                outcome = test.get("outcome") or test.get("status") or test.get("result") or "-"
            else:
                command = test
                outcome = "recorded"
            lines.append(f"| {_md_cell(command)} | {_md_cell(outcome)} |")
    else:
        lines.append("- No tests were recorded in the report payload.")
    lines.extend(["", "## Artifacts", ""])
    artifacts = report.get("artifacts", {})
    if artifacts:
        lines.extend(f"- `{key}`: `{value}`" for key, value in sorted(artifacts.items()))
    else:
        lines.append("- No artifacts recorded.")
    return "\n".join(lines) + "\n"


def export_paper_reproduction_report(
    report: dict[str, Any],
    *,
    config: FactorLabWorkspaceConfig | None = None,
) -> dict[str, Path]:
    workspace = config or FactorLabWorkspaceConfig()
    workspace.ensure_directories()
    name = f"{report['job_id']}_paper_reproduction_report"
    json_path = workspace.report_path(name, suffix=".json")
    md_path = workspace.report_path(name, suffix=".md")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_paper_reproduction_report_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def finalize_paper_reproduction_report(
    report: dict[str, Any],
    pipeline_state: PaperReproductionPipelineState,
    *,
    execution_status: str = "completed",
    truth_validation_status: str | None = None,
    summary: str = "Final JSON and Markdown reports exported from persisted evidence.",
    limitations: list[str] | None = None,
    config: FactorLabWorkspaceConfig | None = None,
) -> dict[str, Path]:
    """Finish Stage 8 and export a report whose embedded pipeline is self-consistent."""

    workspace = config or FactorLabWorkspaceConfig()
    workspace.ensure_directories()
    name = f"{report['job_id']}_paper_reproduction_report"
    expected_paths = {
        "json": workspace.report_path(name, suffix=".json"),
        "markdown": workspace.report_path(name, suffix=".md"),
    }
    legacy_status = "passed" if execution_status in {"completed", "completed_with_limitations"} else "failed"
    pipeline_state.mark_stage(
        "final_report",
        legacy_status,
        execution_status=execution_status,
        truth_validation_status=truth_validation_status,
        summary=summary,
        artifact_paths=[str(expected_paths["json"]), str(expected_paths["markdown"])],
        limitations=limitations or [],
    )
    pipeline_payload = _pipeline_payload(pipeline_state)
    report["pipeline"] = pipeline_payload
    report_summary = report.setdefault("summary", {})
    report_summary["overall_status"] = pipeline_state.overall_status
    report_summary["pipeline_overall_status"] = pipeline_state.overall_status
    report_summary["next_stage"] = pipeline_state.next_stage
    paths = export_paper_reproduction_report(report, config=workspace)
    export_pipeline_state(pipeline_state, config=workspace)
    return paths


def _pipeline_payload(pipeline_state: PaperReproductionPipelineState | None) -> dict[str, Any]:
    if pipeline_state is None:
        return {}
    payload = asdict(pipeline_state)
    payload["overall_status"] = pipeline_state.overall_status
    payload["next_stage"] = pipeline_state.next_stage
    return payload


def _resolve_overall_status(
    pipeline_payload: dict[str, Any],
    status_counts: dict[str, int],
    truth_status_counts: dict[str, int],
) -> str:
    if pipeline_payload.get("overall_status"):
        return str(pipeline_payload["overall_status"])
    if truth_status_counts.get("inconsistent") or truth_status_counts.get("failed"):
        return "failed"
    if any(truth_status_counts.get(status) for status in ("exact_match", "approximately_consistent", "directionally_consistent", "acceptable", "passed")):
        return "paper_truth_evaluated"
    if status_counts.get("needs_human_review"):
        return "needs_human_review"
    if status_counts.get("planned"):
        return "implemented"
    return "pending"


def _collect_known_gaps(factors: list[dict[str, Any]], pipeline_payload: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    for factor in factors:
        ambiguities = factor.get("ambiguities", {})
        if isinstance(ambiguities, dict):
            for category, items in ambiguities.items():
                if items:
                    gaps.append(f"{factor['factor_name']} has {category} ambiguities: {len(items)} item(s)")
        if not factor.get("truth_sources"):
            gaps.append(f"{factor['factor_name']} has no paper evaluation truth source")
        for case in factor.get("skipped_evaluation_cases", []):
            if case.get("skip_reason") in {"known_method_available", "method_budget_exceeded", "unsupported_generic_evaluator"}:
                gaps.append(
                    f"{factor['factor_name']} deferred {case.get('evaluation_family', 'unknown')} "
                    f"evaluation case {case.get('truth_id', '-')}: {case.get('skip_reason')}"
                )
        for deviation in factor.get("deviations", []):
            gaps.append(
                f"{factor['factor_name']} deviation {deviation.get('category', 'unknown')}: "
                f"{deviation.get('reason', '-')}"
            )
        if factor.get("defaulted_transform_assumptions"):
            gaps.append(
                f"{factor['factor_name']} uses defaulted transform assumptions that may explain metric drift: "
                f"{', '.join(factor['defaulted_transform_assumptions'])}"
            )
    for stage in pipeline_payload.get("stages", []) if isinstance(pipeline_payload, dict) else []:
        if stage.get("status") in {"failed", "needs_human_review", "blocked_by_data"}:
            gaps.append(f"Stage {stage.get('name')} is {stage.get('status')}: {stage.get('summary') or '-'}")
    return gaps


def _collect_data_assessments(
    factor_evaluation_plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requirements: list[dict[str, Any]] = []
    replacements: list[dict[str, Any]] = []
    seen_requirements: set[tuple[str, str, str]] = set()
    seen_replacements: set[tuple[str, str, str, str]] = set()
    cases = factor_evaluation_plan.get("assessed_evaluation_cases", []) or factor_evaluation_plan.get("selected_evaluation_cases", [])
    for case in cases:
        if not isinstance(case, dict):
            continue
        truth_id = str(case.get("source_truth_id") or case.get("truth_id", ""))
        assessment = case.get("support_assessment", {}) if isinstance(case.get("support_assessment", {}), dict) else {}
        for item in assessment.get("requirement_results", []) or []:
            if not isinstance(item, dict):
                continue
            payload = dict(item)
            payload["truth_id"] = truth_id
            key = (truth_id, str(payload.get("category", "")), str(payload.get("requirement", "")))
            if key not in seen_requirements:
                seen_requirements.add(key)
                requirements.append(payload)
        canonical_replacements = assessment.get("replacement_records", []) or case.get("replacement_records", []) or []
        for item in canonical_replacements:
            if not isinstance(item, dict):
                continue
            payload = dict(item)
            payload["truth_id"] = truth_id
            key = (
                truth_id,
                str(payload.get("required_semantic_role", "")),
                str(payload.get("paper_definition", "")),
                str(payload.get("replacement_field", "")),
            )
            if key not in seen_replacements:
                seen_replacements.add(key)
                replacements.append(payload)
    return requirements, replacements


def _data_requirement_counts(factors: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "exactly_available": 0,
        "constructible": 0,
        "available_with_missingness": 0,
        "replacement_available": 0,
        "missing": 0,
        "not_assessed": 0,
    }
    for factor in factors:
        for requirement in factor.get("data_requirement_assessments", []):
            status = str(requirement.get("semantic_availability", "not_assessed"))
            counts[status if status in counts else "not_assessed"] += 1
    return counts


def _truth_case_counts(factors: list[dict[str, Any]], truth_results: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    selected = sum(len(factor.get("selected_evaluation_cases", [])) for factor in factors)
    assessed = sum(len(factor.get("assessed_evaluation_cases", [])) for factor in factors)
    extracted = sum(len(factor.get("truth_sources", [])) for factor in factors)
    lifecycle_counts: dict[str, int] = {}
    for factor in factors:
        for collection in (
            "skipped_evaluation_cases",
            "unsupported_evaluation_cases",
            "deferred_evaluation_cases",
        ):
            for case in factor.get(collection, []):
                lifecycle = str(case.get("lifecycle_state", "unknown") or "unknown")
                lifecycle_counts[lifecycle] = lifecycle_counts.get(lifecycle, 0) + 1
    deferred = sum(
        lifecycle_counts.get(state, 0)
        for state in ("deferred_by_budget", "unsupported_evaluator", "insufficient_data")
    )
    selected_by_factor = {
        factor["factor_name"]: {
            str(case.get("source_truth_id") or case.get("truth_id", ""))
            for case in factor.get("selected_evaluation_cases", [])
            if isinstance(case, dict)
        }
        for factor in factors
    }
    executed_results = [
        result
        for factor_name, results in truth_results.items()
        for result in results
        if _is_executed_selected_truth_result(result, selected_by_factor.get(factor_name, set()))
    ]
    comparable_statuses = {"exact_match", "approximately_consistent", "directionally_consistent", "inconsistent"}
    matched_statuses = {"exact_match", "approximately_consistent", "directionally_consistent"}
    return {
        "truth_cases_extracted": extracted,
        "truth_cases_assessed": assessed,
        "truth_cases_selected": selected,
        "truth_cases_executed": len(executed_results),
        "truth_cases_sufficiently_comparable": sum(1 for result in executed_results if result.get("status") in comparable_statuses),
        "truth_cases_matched": sum(1 for result in executed_results if result.get("status") in matched_statuses),
        "truth_cases_inconsistent": sum(1 for result in executed_results if result.get("status") == "inconsistent"),
        "truth_cases_deferred": deferred,
        "truth_cases_conflicted": lifecycle_counts.get("paper_truth_conflict", 0),
        "truth_cases_superseded": lifecycle_counts.get("superseded_by_better_supported_truth", 0),
    }


def _truth_match_pass_rate(counts: dict[str, int]) -> str:
    denominator = counts.get("truth_cases_sufficiently_comparable", 0)
    if not denominator:
        return ""
    return f"{counts.get('truth_cases_matched', 0)}/{denominator}"


def _execution_lifecycle_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        lifecycle = str(record.get("lifecycle_state", "unknown") or "unknown")
        counts[lifecycle] = counts.get(lifecycle, 0) + 1
    return counts


def _is_executed_selected_truth_result(result: dict[str, Any], selected_ids: set[str]) -> bool:
    truth_id = str(result.get("source_truth_id") or result.get("truth_id", ""))
    if selected_ids and truth_id not in selected_ids:
        return False
    if result.get("lifecycle_state") and result.get("lifecycle_state") != "executed":
        return False
    if result.get("status") in {
        "not_evaluated",
        "unsupported_evaluator",
        "deferred_by_budget",
        "insufficient_data",
        "paper_truth_conflict",
        "superseded_by_better_supported_truth",
    }:
        return False
    return bool(truth_id)


def _extraction_factor_views(
    extraction: PaperExtraction | ICAnalysisPaperExtraction,
    specs: list[FactorResearchSpec],
) -> list[dict[str, Any]]:
    """Return a report-facing view without mutating or denormalizing Stage-1 evidence."""

    if isinstance(extraction, PaperExtraction):
        return [
            {
                "factor_name": factor.factor_name,
                "formula": factor.formula,
                "required_fields": list(factor.required_fields),
                "frequency": factor.frequency,
                "sample_period": factor.sample_period,
                "universe": factor.universe,
                "truth_sources": [asdict(source) for source in factor.truth_sources],
                "selected_truth_source_ids": list(factor.selected_truth_source_ids),
                "truth_selection_rule": factor.truth_selection_rule,
                "known_limitations": list(factor.known_limitations),
            }
            for factor in extraction.target_factors
        ]

    spec_by_name = {spec.factor_name: spec for spec in specs}
    views: list[dict[str, Any]] = []
    for factor in extraction.factor_definitions:
        spec = spec_by_name.get(factor.factor_id)
        metadata = dict(spec.metadata) if spec else {}
        truth_sources = list(metadata.get("truth_sources", []) or [])
        sample_periods = list(
            dict.fromkeys(str(source.get("sample_period", "")) for source in truth_sources if source.get("sample_period"))
        )
        universes = list(
            dict.fromkeys(str(source.get("universe", "")) for source in truth_sources if source.get("universe"))
        )
        views.append(
            {
                "factor_name": factor.factor_id,
                "formula": factor.formula,
                "required_fields": list(spec.required_fields) if spec else list(factor.required_semantic_fields),
                "frequency": factor.native_frequency,
                "sample_period": "; ".join(sample_periods),
                "universe": "; ".join(universes),
                "truth_sources": truth_sources,
                # Selection is deliberately absent from immutable Stage 1 and is
                # populated only from the Stage-6 evaluation plan above.
                "selected_truth_source_ids": [],
                "truth_selection_rule": str(extraction.truth_selection_policy.get("rule", "")),
                "known_limitations": list(metadata.get("known_limitations", []) or []),
            }
        )
    return views


def _paper_report_metadata(
    extraction: PaperExtraction | ICAnalysisPaperExtraction,
) -> dict[str, Any]:
    if isinstance(extraction, PaperExtraction):
        return {
            "paper_id": extraction.paper_id,
            "title": extraction.title,
            "authors": list(extraction.authors),
            "source": extraction.source,
            "year": extraction.year,
            "factor_family_name": extraction.factor_family_name,
            "extraction_scope": extraction.extraction_scope,
        }
    publication = extraction.paper.get("publication", {}) or {}
    return {
        "paper_id": extraction.paper.get("paper_id") or extraction.artifact_id,
        "title": extraction.paper.get("title", ""),
        "authors": list(extraction.paper.get("authors", []) or []),
        "source": extraction.paper.get("publisher") or extraction.paper.get("source", ""),
        "year": publication.get("year") or extraction.paper.get("year"),
        "factor_family_name": extraction.factor_family_name,
        "extraction_scope": extraction.scope,
        "extraction_schema_version": extraction.schema_version,
        "artifact_role": extraction.artifact_role,
    }


def _as_plain_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return dict(value)


def _factor_defaulted_transform_assumptions(
    spec_metadata: dict[str, Any],
    factor_evaluation_plan: dict[str, Any],
) -> list[str]:
    result: list[str] = []
    for step in spec_metadata.get("defaulted_transform_steps", []):
        if isinstance(step, str) and step not in result:
            result.append(step)
    for case_key in ("selected_evaluation_cases", "evaluation_cases"):
        for case in factor_evaluation_plan.get(case_key, []):
            if not isinstance(case, dict):
                continue
            transform_spec = case.get("transform_spec", {})
            if isinstance(transform_spec, dict):
                for step in transform_spec.get("defaulted_transform_steps", []):
                    if isinstance(step, str) and step not in result:
                        result.append(step)
            for step in case.get("defaulted_transform_steps", []):
                if isinstance(step, str) and step not in result:
                    result.append(step)
    return result


def _selected_truth_source_summaries(factors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selections: list[dict[str, Any]] = []
    for factor in factors:
        truth_id = str(factor.get("selected_truth_id", "") or "")
        source = factor.get("selected_truth_source", {}) or {}
        if not truth_id and not source:
            continue
        selections.append(
            {
                "factor_name": factor.get("factor_name", ""),
                "truth_id": truth_id or source.get("truth_id", ""),
                "truth_type": source.get("truth_type", ""),
                "description": source.get("description", ""),
                "source_location": source.get("source_location", ""),
                "sample_period": source.get("sample_period", ""),
                "universe": source.get("universe", ""),
                "frequency": source.get("frequency", ""),
                "evaluation_method": source.get("evaluation_method", ""),
                "evaluation_family": source.get("evaluation_family", ""),
                "evaluation_spec": source.get("evaluation_spec", {}) or {},
                "transform_spec": source.get("transform_spec", {}) or {},
                "neutralization_spec": source.get("neutralization_spec", {}) or {},
                "paper_metrics": source.get("metrics", {}) or {},
                "selection_reason": factor.get("selected_truth_reason", ""),
                "comparability": factor.get("comparability", ""),
                "case_executable": factor.get("case_executable"),
                "truth_match_eligible_metrics": factor.get("truth_match_eligible_metrics", []) or [],
                "diagnostic_only_metrics": factor.get("diagnostic_only_metrics", []) or [],
                "deviations": factor.get("deviations", []) or [],
            }
        )
    return selections


def _build_metric_comparison_results(factors: list[dict[str, Any]]) -> dict[str, Any]:
    metric_rows: list[dict[str, Any]] = []
    for factor in factors:
        truth_sources = {
            str(source.get("truth_id", "")): source
            for source in factor.get("truth_sources", []) or []
            if isinstance(source, dict)
        }
        results_by_truth: dict[str, list[dict[str, Any]]] = {}
        for result in factor.get("truth_results", []) or []:
            if not isinstance(result, dict):
                continue
            truth_id = str(result.get("source_truth_id") or result.get("truth_id", ""))
            results_by_truth.setdefault(truth_id, []).append(result)
        result_offsets: dict[str, int] = {}
        for execution in factor.get("evaluation_executions", []) or []:
            if not isinstance(execution, dict) or execution.get("lifecycle_state") != "executed":
                continue
            truth_id = str(execution.get("source_truth_id") or execution.get("truth_case_id", ""))
            truth_source = truth_sources.get(truth_id, {})
            if truth_source.get("truth_type") not in {None, "", "evaluation_results"}:
                continue
            paper_metrics = truth_source.get("metrics", {}) or {}
            calculated_metrics = _evaluator_metrics(execution.get("evaluator_output", {}) or {})
            truth_result_candidates = results_by_truth.get(truth_id, [])
            result_offset = result_offsets.get(truth_id, 0)
            truth_result = (
                truth_result_candidates[result_offset]
                if result_offset < len(truth_result_candidates)
                else {}
            )
            result_offsets[truth_id] = result_offset + 1
            eligible_metrics = list(execution.get("truth_match_eligible_metrics", []) or [])
            diagnostic_metrics = list(execution.get("diagnostic_only_metrics", []) or [])
            for metric, paper_value in paper_metrics.items():
                if metric not in calculated_metrics:
                    continue
                paper_number = _finite_number(paper_value)
                calculated_number = _finite_number(calculated_metrics.get(metric))
                if paper_number is None or calculated_number is None:
                    continue
                signed_error = calculated_number - paper_number
                absolute_error = abs(signed_error)
                signed_percentage_error = (
                    signed_error / abs(paper_number) if paper_number != 0 else None
                )
                absolute_percentage_error = (
                    absolute_error / abs(paper_number) if paper_number != 0 else None
                )
                metric_role = "reported_comparison"
                if metric in eligible_metrics:
                    metric_role = "truth_match_eligible"
                elif metric in diagnostic_metrics:
                    metric_role = "diagnostic_only"
                metric_rows.append(
                    {
                        "factor_name": factor.get("factor_name", ""),
                        "scenario_id": execution.get("scenario_id", ""),
                        "execution_id": execution.get("execution_id", ""),
                        "truth_id": truth_id,
                        "source_location": truth_source.get("source_location", ""),
                        "evaluation_method": truth_source.get("evaluation_method", ""),
                        "sample_period": truth_source.get("sample_period", ""),
                        "metric": str(metric),
                        "paper_value": paper_number,
                        "calculated_value": calculated_number,
                        "signed_error": signed_error,
                        "absolute_error": absolute_error,
                        "signed_percentage_error": signed_percentage_error,
                        "absolute_percentage_error": absolute_percentage_error,
                        "sign_match": _sign(paper_number) == _sign(calculated_number),
                        "truth_status": truth_result.get("status", ""),
                        "comparability": execution.get("comparability") or factor.get("comparability", ""),
                        "metric_role": metric_role,
                        "truth_match_eligible": metric in eligible_metrics,
                        "cross_section_count": calculated_metrics.get("cross_section_count"),
                    }
                )

    metric_names = {row["metric"] for row in metric_rows}
    primary_metric = next(
        (
            metric
            for metric in ("rank_ic_mean", "ic_mean", "mean_rank_ic", "mean_ic")
            if metric in metric_names
        ),
        "",
    )
    primary_rows = [row for row in metric_rows if row["metric"] == primary_metric]
    scenarios = list(dict.fromkeys(str(row.get("scenario_id", "")) for row in primary_rows))
    return {
        "primary_metric": primary_metric,
        "primary_metric_rows": primary_rows,
        "metric_rows": metric_rows,
        "summary": {
            "primary_metric": _comparison_statistics(primary_rows),
            "primary_metric_by_scenario": {
                scenario: _comparison_statistics(
                    [row for row in primary_rows if str(row.get("scenario_id", "")) == scenario]
                )
                for scenario in scenarios
            },
            "all_metrics": _comparison_statistics(metric_rows),
        },
    }


def _evaluator_metrics(evaluator_output: dict[str, Any]) -> dict[str, Any]:
    metrics = evaluator_output.get("metrics", {}) or {}
    if not isinstance(metrics, dict):
        return {}
    if isinstance(metrics.get("ic"), dict):
        return dict(metrics["ic"])
    return dict(metrics)


def _comparison_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "comparison_count": 0,
            "percentage_error_count": 0,
            "median_signed_percentage_error": None,
            "median_absolute_percentage_error": None,
            "mean_absolute_percentage_error": None,
            "mean_absolute_error": None,
            "root_mean_squared_error": None,
            "maximum_absolute_percentage_error": None,
            "sign_agreement_rate": None,
            "pearson_correlation": None,
        }
    signed_errors = [float(row["signed_error"]) for row in rows]
    absolute_errors = [float(row["absolute_error"]) for row in rows]
    signed_percentage_errors = [
        float(row["signed_percentage_error"])
        for row in rows
        if row.get("signed_percentage_error") is not None
    ]
    absolute_percentage_errors = [
        float(row["absolute_percentage_error"])
        for row in rows
        if row.get("absolute_percentage_error") is not None
    ]
    paper_values = [float(row["paper_value"]) for row in rows]
    calculated_values = [float(row["calculated_value"]) for row in rows]
    return {
        "comparison_count": len(rows),
        "percentage_error_count": len(absolute_percentage_errors),
        "mean_signed_error": statistics.fmean(signed_errors),
        "median_signed_percentage_error": (
            statistics.median(signed_percentage_errors) if signed_percentage_errors else None
        ),
        "median_absolute_percentage_error": (
            statistics.median(absolute_percentage_errors) if absolute_percentage_errors else None
        ),
        "mean_absolute_percentage_error": (
            statistics.fmean(absolute_percentage_errors) if absolute_percentage_errors else None
        ),
        "mean_absolute_error": statistics.fmean(absolute_errors),
        "root_mean_squared_error": math.sqrt(
            statistics.fmean(error * error for error in signed_errors)
        ),
        "maximum_absolute_percentage_error": (
            max(absolute_percentage_errors) if absolute_percentage_errors else None
        ),
        "sign_agreement_rate": statistics.fmean(
            1.0 if bool(row.get("sign_match")) else 0.0 for row in rows
        ),
        "pearson_correlation": _pearson_correlation(paper_values, calculated_values),
    }


def _pearson_correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    left_delta = [value - left_mean for value in left]
    right_delta = [value - right_mean for value in right]
    denominator = math.sqrt(
        sum(value * value for value in left_delta)
        * sum(value * value for value in right_delta)
    )
    if denominator == 0:
        return None
    return sum(a * b for a, b in zip(left_delta, right_delta, strict=True)) / denominator


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _data_profile_summaries(data_profiles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for profile_id, profile in data_profiles.items():
        conventions = profile.get("conventions", {}) or {}
        classification = conventions.get("industry_classification", {}) or {}
        if isinstance(classification, dict) and classification:
            industry_label = f"{classification.get('source', '-')} level {classification.get('level', '-')}"
            interval_rule = str(classification.get("interval_rule", ""))
        else:
            industry_label = ""
            interval_rule = ""
        source_id = str(profile.get("source_id") or profile_id)
        date_min = str(profile.get("date_min") or "")
        date_max = str(profile.get("date_max") or "")
        coverage = f"{date_min} to {date_max}" if date_min or date_max else ""
        market_cap_fields = conventions.get("market_cap_fields", []) or []
        if isinstance(market_cap_fields, str):
            market_cap_fields = [market_cap_fields]
        summaries.append(
            {
                "source_id": source_id,
                "coverage": coverage,
                "row_count": int(profile.get("row_count", 0) or 0),
                "price_adjustment": conventions.get("price_adjustment", ""),
                "market_cap_fields": [str(field) for field in market_cap_fields],
                "market_cap_lineage": conventions.get("market_cap_lineage", {}) or {},
                "industry_classification": industry_label,
                "industry_interval_rule": interval_rule,
                "financial_statement_selection": conventions.get("financial_statement_selection", {}) or {},
                "valuation_selection": conventions.get("valuation_selection", {}) or {},
                "dividend_history_selection": conventions.get("dividend_history_selection", {}) or {},
                "trading_calendar_selection": conventions.get("trading_calendar_selection", {}) or {},
                "index_reference_selection": conventions.get("index_reference_selection", {}) or {},
                "yield_curve_selection": conventions.get("yield_curve_selection", {}) or {},
                "forward_return_lineage": conventions.get("forward_return_lineage", {}) or {},
                "limitations": [str(item) for item in (profile.get("limitations", []) or [])],
            }
        )
    return summaries


def _capitalization_industry_label(profile: dict[str, Any]) -> str:
    parts: list[str] = []
    cap_fields = profile.get("market_cap_fields", []) or []
    if cap_fields:
        parts.append("cap=" + ",".join(str(value) for value in cap_fields))
    if profile.get("industry_classification"):
        industry = str(profile["industry_classification"])
        rule = str(profile.get("industry_interval_rule") or "")
        parts.append(f"industry={industry}" + (f" ({rule})" if rule else ""))
    return "; ".join(parts) or "-"


def _pit_valuation_label(profile: dict[str, Any]) -> str:
    parts: list[str] = []
    statement = profile.get("financial_statement_selection", {}) or {}
    if statement:
        parts.append(
            "statements="
            f"{','.join(str(value) for value in statement.get('fields', []) or [])} "
            f"as-of {statement.get('as_of_date', '-')} ({statement.get('version_policy', '-')})"
        )
    valuation = profile.get("valuation_selection", {}) or {}
    if valuation:
        parts.append("valuation=" + ",".join(str(value) for value in valuation.get("fields", []) or []))
    dividend = profile.get("dividend_history_selection", {}) or {}
    if dividend:
        parts.append(f"dividends={dividend.get('kind', '-')} as-of {dividend.get('as_of_date', '-')}")
    return "; ".join(parts) or "-"


def _reference_label(profile: dict[str, Any]) -> str:
    parts: list[str] = []
    index_reference = profile.get("index_reference_selection", {}) or {}
    if index_reference:
        label = str(index_reference.get("dataset") or "index_reference")
        index_id = index_reference.get("index_id") or index_reference.get("index_ids")
        frequency = index_reference.get("weight_frequency")
        parts.append(f"{label}={index_id}" + (f"/{frequency}" if frequency else ""))
    calendar = profile.get("trading_calendar_selection", {}) or {}
    if calendar:
        parts.append("calendar=CN exchange")
    curve = profile.get("yield_curve_selection", {}) or {}
    if curve:
        parts.append("yield=" + ",".join(str(value) for value in curve.get("tenors", []) or []))
    lineage = profile.get("forward_return_lineage", {}) or {}
    if lineage:
        parts.append(
            f"label={lineage.get('field', '-')} "
            f"({lineage.get('horizon', '-') } {lineage.get('horizon_unit', '-')})"
        )
    return "; ".join(parts) or "-"


def _format_number(value: Any) -> str:
    number = _finite_number(value)
    if number is None:
        return "-"
    return f"{number:.6f}".rstrip("0").rstrip(".")


def _format_percentage(value: Any) -> str:
    number = _finite_number(value)
    return f"{number:.2%}" if number is not None else "-"


def _md_cell(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value).replace("\n", " ").replace("|", "\\|")


def _metric_label(metric: str) -> str:
    return {
        "rank_ic_mean": "Mean Rank IC",
        "ic_mean": "Mean IC",
        "mean_rank_ic": "Mean Rank IC",
        "mean_ic": "Mean IC",
        "rank_ic_std": "Rank IC Standard Deviation",
        "ic_ir": "IC Information Ratio",
        "ic_positive_ratio": "Positive IC Ratio",
    }.get(metric, metric.replace("_", " ").title() or "Metric")


def _format_metrics(metrics: dict[str, Any]) -> str:
    if not metrics:
        return "-"
    return ", ".join(f"{key}={value}" for key, value in metrics.items())
