from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from research_core.factor_lab.paper_reproduction.extraction import ExtractedTruthSource


@dataclass(slots=True)
class PaperTruthMatchResult:
    truth_id: str
    truth_type: str
    passed: bool
    status: str
    diagnostics: dict[str, Any] = field(default_factory=dict)


def compare_evaluation_metrics_to_paper_truth(
    computed_metrics: dict[str, Any],
    truth_source: ExtractedTruthSource,
    *,
    resolved_evaluation_case: dict[str, Any] | None = None,
    comparability: str = "exact",
    eligible_metrics: list[str] | None = None,
    diagnostic_only_metrics: list[str] | None = None,
    tolerance: float = 1e-6,
    relative_tolerance: float = 0.1,
) -> PaperTruthMatchResult:
    if truth_source.truth_type != "evaluation_results":
        raise ValueError(f"truth_source {truth_source.truth_id} is not evaluation_results truth")
    if resolved_evaluation_case:
        comparability = str(resolved_evaluation_case.get("comparability", comparability) or comparability)
        eligible_metrics = list(resolved_evaluation_case.get("truth_match_eligible_metrics", eligible_metrics or []) or [])
        diagnostic_only_metrics = list(resolved_evaluation_case.get("diagnostic_only_metrics", diagnostic_only_metrics or []) or [])
    paper_metric_names = list(truth_source.metrics)
    if eligible_metrics is None:
        eligible_metrics = paper_metric_names
    eligible_metrics = [metric for metric in eligible_metrics if metric in truth_source.metrics]
    diagnostic_only_metrics = diagnostic_only_metrics or [metric for metric in paper_metric_names if metric not in eligible_metrics]
    if comparability == "not_comparable" or not eligible_metrics:
        diagnostics = {
            "matched_metrics": [],
            "missing_metrics": [],
            "failed_metrics": [],
            "metric_errors": {},
            "comparability": comparability,
            "eligible_metrics": eligible_metrics,
            "diagnostic_only_metrics": diagnostic_only_metrics,
            "quality": "not_evaluated" if comparability == "not_comparable" else "inconclusive_due_to_protocol_gap",
        }
        return PaperTruthMatchResult(
            truth_id=truth_source.truth_id,
            truth_type=truth_source.truth_type,
            passed=False,
            status=diagnostics["quality"],
            diagnostics=diagnostics,
        )

    missing_metrics = [metric for metric in eligible_metrics if metric not in computed_metrics]
    compared: dict[str, dict[str, float]] = {}
    failed_metrics: list[str] = []
    within_relative_tolerance: list[str] = []
    sign_matches: list[bool] = []
    for metric in eligible_metrics:
        paper_value = truth_source.metrics[metric]
        if metric in missing_metrics:
            continue
        try:
            computed_value = float(computed_metrics[metric])
            expected_value = float(paper_value)
        except (TypeError, ValueError):
            failed_metrics.append(metric)
            continue
        abs_error = abs(computed_value - expected_value)
        denominator = max(abs(expected_value), tolerance)
        relative_error = abs_error / denominator
        sign_match = _sign(computed_value) == _sign(expected_value)
        sign_matches.append(sign_match)
        compared[metric] = {
            "computed": computed_value,
            "paper": expected_value,
            "abs_error": abs_error,
            "relative_error": relative_error,
            "sign_match": float(sign_match),
        }
        if abs_error > tolerance:
            failed_metrics.append(metric)
        if relative_error <= relative_tolerance and sign_match:
            within_relative_tolerance.append(metric)

    exact_passed = comparability == "exact" and not missing_metrics and not failed_metrics and bool(compared)
    sign_match_ratio = sum(sign_matches) / len(sign_matches) if sign_matches else 0.0
    diagnostics = {
        "matched_metrics": [metric for metric in eligible_metrics if metric in compared],
        "missing_metrics": missing_metrics,
        "failed_metrics": sorted(failed_metrics),
        "metric_errors": compared,
        "comparability": comparability,
        "eligible_metrics": eligible_metrics,
        "diagnostic_only_metrics": diagnostic_only_metrics,
        "tolerance": tolerance,
        "relative_tolerance": relative_tolerance,
        "within_relative_tolerance_metrics": within_relative_tolerance,
        "sign_match_ratio": sign_match_ratio,
    }
    quality = interpret_truth_match_quality(exact_passed, diagnostics, comparability=comparability)
    diagnostics["quality"] = quality
    return PaperTruthMatchResult(
        truth_id=truth_source.truth_id,
        truth_type=truth_source.truth_type,
        passed=exact_passed,
        status=quality,
        diagnostics=diagnostics,
    )


def interpret_truth_match_quality(
    passed: bool,
    diagnostics: dict[str, Any],
    *,
    comparability: str = "exact",
) -> str:
    if passed:
        return "exact_match"
    if comparability == "not_comparable":
        return "not_evaluated"
    missing_metrics = diagnostics.get("missing_metrics", []) or []
    matched_metrics = diagnostics.get("matched_metrics", []) or []
    within_relative = diagnostics.get("within_relative_tolerance_metrics", []) or []
    sign_match_ratio = float(diagnostics.get("sign_match_ratio", 0.0) or 0.0)
    if not missing_metrics and matched_metrics and set(within_relative) == set(matched_metrics) and sign_match_ratio >= 0.8:
        if comparability in {"proxy", "directional_only"}:
            return "directionally_consistent"
        return "approximately_consistent"
    if comparability in {"proxy", "directional_only", "materially_comparable"} and matched_metrics:
        return "inconclusive_due_to_protocol_gap"
    return "inconsistent"


def _sign(value: float) -> int:
    if pd.isna(value):
        return 0
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0
