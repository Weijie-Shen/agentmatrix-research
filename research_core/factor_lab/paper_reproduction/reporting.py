from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from contracts.factor_research import FactorResearchSpec
from research_core.factor_lab.paper_reproduction.extraction import PaperExtraction
from research_core.factor_lab.paper_reproduction.paper_evaluation import PaperEvaluationPlan
from research_core.factor_lab.paper_reproduction.pipeline import PaperReproductionPipelineState
from research_core.factor_lab.runtime import FactorLabWorkspaceConfig, now_iso


def build_paper_reproduction_report(
    *,
    job_id: str,
    extraction: PaperExtraction,
    specs: list[FactorResearchSpec],
    pipeline_state: PaperReproductionPipelineState | None = None,
    evaluation_plan: PaperEvaluationPlan | None = None,
    evaluation_report: dict[str, Any] | None = None,
    truth_results: dict[str, list[dict[str, Any]]] | None = None,
    artifacts: dict[str, str] | None = None,
    tests_run: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    truth_results = truth_results or {}
    spec_by_name = {spec.factor_name: spec for spec in specs}
    evaluation_plan_by_name = {
        plan.factor_name: plan
        for plan in (evaluation_plan.factor_plans if evaluation_plan else [])
    }
    factors = []
    status_counts: dict[str, int] = {}
    truth_status_counts: dict[str, int] = {}
    for factor in extraction.target_factors:
        spec = spec_by_name.get(factor.factor_name)
        spec_metadata = dict(spec.metadata) if spec else {}
        factor_evaluation_plan = _as_plain_dict(evaluation_plan_by_name.get(factor.factor_name))
        factor_truth_results = truth_results.get(factor.factor_name, [])
        for item in factor_truth_results:
            status = str(item.get("status", "unknown"))
            truth_status_counts[status] = truth_status_counts.get(status, 0) + 1
        selected_cases = factor_evaluation_plan.get("selected_evaluation_cases", [])
        selected_truth = selected_cases[0] if selected_cases else {}
        factor_status = str(spec_metadata.get("status", "extracted_only"))
        status_counts[factor_status] = status_counts.get(factor_status, 0) + 1
        factors.append(
            {
                "factor_name": factor.factor_name,
                "formula": factor.formula,
                "required_fields": list(factor.required_fields),
                "frequency": factor.frequency,
                "sample_period": factor.sample_period,
                "universe": factor.universe,
                "truth_sources": [_as_plain_dict(source) for source in factor.truth_sources],
                "evaluation_cases": [_as_plain_dict(source) for source in factor.truth_sources],
                "assessed_evaluation_cases": factor_evaluation_plan.get("assessed_evaluation_cases", []),
                "selected_evaluation_cases": selected_cases,
                "skipped_evaluation_cases": factor_evaluation_plan.get("skipped_evaluation_cases", []),
                "unsupported_evaluation_cases": factor_evaluation_plan.get("unsupported_evaluation_cases", []),
                "deferred_evaluation_cases": factor_evaluation_plan.get("deferred_evaluation_cases", []),
                "selected_truth_id": selected_truth.get("source_truth_id") or selected_truth.get("truth_id", ""),
                "selected_truth_reason": selected_truth.get("selection_reason", ""),
                "comparability": selected_truth.get("comparability", ""),
                "deviations": selected_truth.get("deviations", []),
                "truth_match_eligible_metrics": selected_truth.get("truth_match_eligible_metrics", []),
                "diagnostic_only_metrics": selected_truth.get("diagnostic_only_metrics", []),
                "requires_paper_local_evaluator": factor_evaluation_plan.get("requires_paper_local_evaluator", False),
                "evaluator_implementation_targets": factor_evaluation_plan.get("evaluator_implementation_targets", []),
                "defaulted_transform_assumptions": _factor_defaulted_transform_assumptions(
                    spec_metadata,
                    factor_evaluation_plan,
                ),
                "truth_results": factor_truth_results,
                "spec_status": factor_status,
                "data_requirements": spec_metadata.get("data_requirements", {}),
                "known_limitations": spec_metadata.get("known_limitations", list(factor.known_limitations)),
                "spec_metadata": spec_metadata,
                "ambiguities": spec_metadata.get("factor_ambiguities_by_category", {}),
            }
        )

    pipeline_payload = _pipeline_payload(pipeline_state)
    overall_status = _resolve_overall_status(pipeline_payload, status_counts, truth_status_counts)
    truth_case_counts = _truth_case_counts(factors, truth_results)
    return {
        "job_id": job_id,
        "generated_at": now_iso(),
        "paper": {
            "paper_id": extraction.paper_id,
            "title": extraction.title,
            "authors": list(extraction.authors),
            "source": extraction.source,
            "year": extraction.year,
            "factor_family_name": extraction.factor_family_name,
            "extraction_scope": extraction.extraction_scope,
        },
        "summary": {
            "overall_status": overall_status,
            "factor_count": len(factors),
            "spec_status_counts": status_counts,
            "truth_status_counts": truth_status_counts,
            "truth_case_counts": truth_case_counts,
            "truth_match_pass_rate": _truth_match_pass_rate(truth_case_counts),
            "pipeline_overall_status": pipeline_payload.get("overall_status"),
            "next_stage": pipeline_payload.get("next_stage"),
            "proof_language_note": "Do not claim full reproduction, zero bias, or passed proof unless evaluation-result truth checks pass under the agreed policy.",
        },
        "pipeline": pipeline_payload,
        "evaluation_plan": _as_plain_dict(evaluation_plan) if evaluation_plan else {},
        "evaluation_report": evaluation_report or {},
        "factors": factors,
        "artifacts": artifacts or {},
        "tests_run": tests_run or [],
        "known_gaps": _collect_known_gaps(factors, pipeline_payload),
    }


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
        f"- Authors: {', '.join(paper['authors']) if paper['authors'] else '-'}",
        f"- Source: {paper.get('source') or '-'}",
        f"- Year: {paper.get('year') or '-'}",
        f"- Factor family: {paper['factor_family_name']}",
        f"- Overall status: {summary['overall_status']}",
        f"- Truth match pass rate: {summary.get('truth_match_pass_rate') or '-'}",
        f"- Next stage: {summary.get('next_stage') or '-'}",
        "",
        f"> {summary['proof_language_note']}",
        "",
        "## Factors",
        "",
        "| Factor | Spec Status | Frequency | Required Fields | Evaluation Truth |",
        "|---|---|---|---|---|",
    ]
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
        deviations = factor.get("deviations", [])
        for deviation in deviations:
            lines.append(
                f"- Deviation `{deviation.get('category', '-')}`: {deviation.get('paper_value', '-')} -> "
                f"{deviation.get('resolved_value', '-')} ({deviation.get('severity', '-')})"
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
        lines.extend(["| Stage | Status | Summary |", "|---|---|---|"])
        for stage in stages:
            lines.append(f"| {stage.get('name', '-')} | {stage.get('status', '-')} | {stage.get('summary', '') or '-'} |")
    else:
        lines.append("No pipeline state was supplied.")
    lines.extend(["", "## Known Gaps", ""])
    gaps = report.get("known_gaps", [])
    if gaps:
        lines.extend(f"- {gap}" for gap in gaps)
    else:
        lines.append("- None recorded.")
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


def _truth_case_counts(factors: list[dict[str, Any]], truth_results: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    selected = sum(len(factor.get("selected_evaluation_cases", [])) for factor in factors)
    assessed = sum(len(factor.get("assessed_evaluation_cases", [])) for factor in factors)
    extracted = sum(len(factor.get("truth_sources", [])) for factor in factors)
    deferred = sum(len(factor.get("deferred_evaluation_cases", [])) + len(factor.get("unsupported_evaluation_cases", [])) for factor in factors)
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
    }


def _truth_match_pass_rate(counts: dict[str, int]) -> str:
    denominator = counts.get("truth_cases_sufficiently_comparable", 0)
    if not denominator:
        return ""
    return f"{counts.get('truth_cases_matched', 0)}/{denominator}"


def _is_executed_selected_truth_result(result: dict[str, Any], selected_ids: set[str]) -> bool:
    truth_id = str(result.get("source_truth_id") or result.get("truth_id", ""))
    if selected_ids and truth_id not in selected_ids:
        return False
    if result.get("lifecycle_state") and result.get("lifecycle_state") != "executed":
        return False
    if result.get("status") in {"not_evaluated", "unsupported_evaluator", "deferred_by_budget", "insufficient_data"}:
        return False
    return bool(truth_id)


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


def _format_metrics(metrics: dict[str, Any]) -> str:
    if not metrics:
        return "-"
    return ", ".join(f"{key}={value}" for key, value in metrics.items())
