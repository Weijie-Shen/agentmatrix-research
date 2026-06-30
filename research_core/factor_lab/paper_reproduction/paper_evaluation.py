from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from contracts.factor_research import FactorResearchSpec


@dataclass(slots=True)
class PaperFactorEvaluationPlan:
    factor_name: str
    status: str
    evaluation_method: str = ""
    required_metrics: list[str] = field(default_factory=list)
    evaluation_features: list[str] = field(default_factory=list)
    forward_return_periods: list[int] = field(default_factory=list)
    truth_source_ids: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PaperEvaluationPlan:
    library: str
    status: str
    factor_plans: list[PaperFactorEvaluationPlan]
    notes: list[str] = field(default_factory=list)


def build_paper_evaluation_plan(specs: list[FactorResearchSpec]) -> PaperEvaluationPlan:
    if not specs:
        raise ValueError("At least one FactorResearchSpec is required to build a paper evaluation plan.")
    factor_plans = [_build_factor_evaluation_plan(spec) for spec in specs]
    statuses = {plan.status for plan in factor_plans}
    if "needs_human_review" in statuses:
        status = "needs_human_review"
    elif statuses == {"ready_for_evaluation"}:
        status = "ready_for_evaluation"
    else:
        status = "mixed"
    return PaperEvaluationPlan(library=specs[0].library, status=status, factor_plans=factor_plans)


def _build_factor_evaluation_plan(spec: FactorResearchSpec) -> PaperFactorEvaluationPlan:
    selected_truth_sources = spec.metadata.get("selected_truth_sources", [])
    evaluation_truth_sources = [
        source
        for source in selected_truth_sources
        if isinstance(source, dict) and source.get("truth_type") == "evaluation_results"
    ]
    metrics: list[str] = []
    truth_ids: list[str] = []
    methods: list[str] = []
    for source in evaluation_truth_sources:
        truth_ids.append(str(source.get("truth_id", "")))
        source_metrics = source.get("metrics", {})
        if isinstance(source_metrics, dict):
            for metric in source_metrics:
                if metric not in metrics:
                    metrics.append(str(metric))
        method = str(source.get("evaluation_method", "")).strip()
        if method:
            methods.append(method)

    spec_method = str(spec.metadata.get("evaluation_method", "")).strip()
    evaluation_method = methods[0] if methods else spec_method
    blocked_reasons: list[str] = []
    if evaluation_truth_sources and not evaluation_method:
        blocked_reasons.append("paper evaluation method is missing")
    if evaluation_truth_sources and not metrics:
        blocked_reasons.append("paper evaluation metrics are missing")

    status = "needs_human_review" if blocked_reasons else "ready_for_evaluation"
    return PaperFactorEvaluationPlan(
        factor_name=spec.factor_name,
        status=status,
        evaluation_method=evaluation_method,
        required_metrics=metrics,
        evaluation_features=_evaluation_features(evaluation_method, metrics),
        forward_return_periods=_forward_return_periods(evaluation_method),
        truth_source_ids=[truth_id for truth_id in truth_ids if truth_id],
        blocked_reasons=blocked_reasons,
    )


def _evaluation_features(evaluation_method: str, metrics: list[str]) -> list[str]:
    text = " ".join([evaluation_method, *metrics]).lower().replace("-", "_")
    features: list[str] = []
    if "rank_ic" in text or "rank ic" in text:
        features.append("rank_ic")
    elif "ic" in text:
        features.append("pearson_ic")
    if "ir" in text:
        features.append("information_ratio")
    if "long_short" in text or "long short" in text or "spread" in text:
        features.append("long_short")
    if "sharpe" in text:
        features.append("sharpe")
    if "return" in text:
        features.append("forward_returns")
    return features or ["custom"]


def _forward_return_periods(evaluation_method: str) -> list[int]:
    text = evaluation_method.lower()
    periods = [int(match.group(1)) for match in re.finditer(r"(\d+)\s*[- ]?day", text)]
    if not periods and ("daily" in text or "1-day" in text or "1 day" in text):
        periods = [1]
    return sorted(set(periods or [1]))
