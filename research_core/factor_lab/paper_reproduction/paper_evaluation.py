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
    evaluation_cases: list[dict[str, Any]] = field(default_factory=list)
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
        evaluation_cases=[_evaluation_case_from_truth_source(source) for source in evaluation_truth_sources],
        blocked_reasons=blocked_reasons,
    )


def _evaluation_case_from_truth_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "truth_id": str(source.get("truth_id", "")),
        "evaluation_family": str(source.get("evaluation_family", "") or _infer_evaluation_family(source)),
        "evaluation_method": str(source.get("evaluation_method", "")),
        "evaluation_spec": dict(source.get("evaluation_spec", {}) if isinstance(source.get("evaluation_spec", {}), dict) else {}),
        "transform_spec": dict(source.get("transform_spec", {}) if isinstance(source.get("transform_spec", {}), dict) else {}),
        "required_data": dict(source.get("required_data", {}) if isinstance(source.get("required_data", {}), dict) else {}),
        "metrics": dict(source.get("metrics", {}) if isinstance(source.get("metrics", {}), dict) else {}),
        "source_location": str(source.get("source_location", "")),
    }


def _infer_evaluation_family(source: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(source.get("evaluation_method", "")),
            " ".join(str(metric) for metric in (source.get("metrics", {}) or {})),
        ]
    ).lower().replace("-", "_")
    if "half_life" in text or "decay" in text:
        return "ic_decay"
    if "top_layer" in text or "long_short" in text or "portfolio" in text or "layer" in text:
        return "layered_portfolio_backtest"
    if "t_abs" in text or "factor_return" in text or "regression" in text:
        return "regression_t_test"
    if "rank_ic" in text or "ic" in text:
        return "ic_analysis"
    return "custom"


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
