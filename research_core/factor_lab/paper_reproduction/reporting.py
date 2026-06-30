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
    factors = []
    status_counts: dict[str, int] = {}
    truth_status_counts: dict[str, int] = {}
    for factor in extraction.target_factors:
        spec = spec_by_name.get(factor.factor_name)
        spec_metadata = dict(spec.metadata) if spec else {}
        factor_truth_results = truth_results.get(factor.factor_name, [])
        for item in factor_truth_results:
            status = str(item.get("status", "unknown"))
            truth_status_counts[status] = truth_status_counts.get(status, 0) + 1
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
                "preprocessing_rules": list(factor.preprocessing_rules),
                "neutralization_rules": list(factor.neutralization_rules),
                "evaluation_method": factor.evaluation_method,
                "portfolio_construction_rules": factor.portfolio_construction_rules,
                "truth_sources": [_as_plain_dict(source) for source in factor.truth_sources],
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
        lines.append(f"- Evaluation method: {factor.get('evaluation_method') or '-'}")
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
    if truth_status_counts.get("failed"):
        return "failed"
    if truth_status_counts.get("acceptable") or truth_status_counts.get("passed"):
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
    for stage in pipeline_payload.get("stages", []) if isinstance(pipeline_payload, dict) else []:
        if stage.get("status") in {"failed", "needs_human_review", "blocked_by_data"}:
            gaps.append(f"Stage {stage.get('name')} is {stage.get('status')}: {stage.get('summary') or '-'}")
    return gaps


def _as_plain_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return dict(value)


def _format_metrics(metrics: dict[str, Any]) -> str:
    if not metrics:
        return "-"
    return ", ".join(f"{key}={value}" for key, value in metrics.items())
