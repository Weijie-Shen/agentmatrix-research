from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research_core.factor_lab.paper_reproduction.evaluators import (
    PROCESSED_FACTOR_COL,
    apply_evaluation_recipe,
    compute_ic_analysis,
)
from research_core.factor_lab.paper_reproduction.recommended_data import (
    IndustryClassificationSelection,
    load_recommended_daily_panel,
    normalize_recommended_symbol,
)
from research_core.factor_lab.paper_reproduction.recommended_reference import (
    load_recommended_trading_calendar,
    materialize_natural_month_forward_return,
)
from research_core.factor_lab.libraries.huatai_momentum_20161220 import compute_corrected_factors


FACTORS = (
    "exp_wgt_return_6m",
    "exp_wgt_return_3m",
    "wgt_return_1m",
    "return_1m",
)
PAPER_METRICS = {
    "exp_wgt_return_6m": {"ic_mean": -0.0770, "ic_std": 0.0835, "ic_ir": 0.92, "ic_positive_ratio": 0.1608, "ic_abs_gt_002_ratio": 0.8531},
    "exp_wgt_return_3m": {"ic_mean": -0.0774, "ic_std": 0.0807, "ic_ir": 0.96, "ic_positive_ratio": 0.1538, "ic_abs_gt_002_ratio": 0.8462},
    "wgt_return_1m": {"ic_mean": -0.0724, "ic_std": 0.0784, "ic_ir": 0.92, "ic_positive_ratio": 0.1818, "ic_abs_gt_002_ratio": 0.8671},
    "return_1m": {"ic_mean": -0.0573, "ic_std": 0.0907, "ic_ir": 0.63, "ic_positive_ratio": 0.2797, "ic_abs_gt_002_ratio": 0.8252},
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Controlled Huatai momentum IC counterfactual")
    parser.add_argument("--source-bundle", required=True)
    parser.add_argument("--legacy-module", required=True)
    parser.add_argument(
        "--market-cap-history",
        required=True,
        help="Path to the point-in-time market-cap-history Parquet file",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source_bundle = Path(args.source_bundle).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    recipe, harvested_metrics = _load_recipe_and_metrics(source_bundle)
    legacy_compute = _load_legacy_callable(Path(args.legacy_module).expanduser().resolve())

    calculation_start = pd.Timestamp("2004-09-01")
    sample_start = pd.Timestamp("2005-04-29")
    sample_end = pd.Timestamp("2016-11-30")
    label_end = pd.Timestamp("2016-12-30")
    calendar = load_recommended_trading_calendar(start_date=calculation_start, end_date=label_end)
    panel = load_recommended_daily_panel(
        start_date=calculation_start,
        end_date=label_end,
        price_view="hfq",
        include_status=True,
        market_cap_fields=("circulating_market_cap",),
        industry_classification=IndustryClassificationSelection(source="citics", level=1),
    )
    panel["adjusted_close"] = pd.to_numeric(panel["close"], errors="coerce")
    # Preserve the rejected run's locally constructed turnover convention so
    # that only the three requested causes change in the counterfactual.
    shares = _load_circulating_shares(
        Path(args.market_cap_history).expanduser().resolve(),
        calculation_start,
        label_end,
    )
    panel = panel.merge(shares, on=["date", "code"], how="left", validate="one_to_one")
    panel["turnover"] = (
        pd.to_numeric(panel["volume"], errors="coerce")
        .div(pd.to_numeric(panel["circulation_a"], errors="coerce"))
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
    )

    legacy_panel = panel.loc[panel["date"].ge(sample_start)].copy()
    legacy_factors = legacy_compute(legacy_panel, factor_names=list(FACTORS))
    corrected_factors = compute_corrected_factors(panel, trading_calendar=calendar, factor_names=FACTORS)
    evaluation_panel = _evaluation_panel(
        panel,
        calendar=calendar,
        sample_start=sample_start,
        sample_end=sample_end,
    )

    legacy_results = _evaluate_factor_set(evaluation_panel, legacy_factors, recipe=recipe)
    corrected_results = _evaluate_factor_set(evaluation_panel, corrected_factors, recipe=recipe)
    comparison: dict[str, Any] = {}
    for factor in FACTORS:
        parity_error = _metric_max_abs_error(harvested_metrics[factor], legacy_results[factor])
        comparison[factor] = {
            "paper": PAPER_METRICS[factor],
            "harvested_legacy": harvested_metrics[factor],
            "recomputed_legacy": _compact_metrics(legacy_results[factor]),
            "corrected": _compact_metrics(corrected_results[factor]),
            "legacy_parity_max_abs_error": parity_error,
            "legacy_parity_status": "exact" if parity_error <= 1e-12 else "not_reproduced",
            "paper_absolute_error_harvested": _absolute_errors(PAPER_METRICS[factor], harvested_metrics[factor]),
            "paper_absolute_error_recomputed_legacy": _absolute_errors(PAPER_METRICS[factor], legacy_results[factor]),
            "paper_absolute_error_corrected": _absolute_errors(PAPER_METRICS[factor], corrected_results[factor]),
        }

    payload = {
        "schema_version": "huatai_momentum_counterfactual_ic/v1",
        "purpose": "Isolate manual corrections for causes 1-3 without rerunning the paper pipeline.",
        "price_view": "hfq",
        "sample": [sample_start.date().isoformat(), sample_end.date().isoformat()],
        "calculation_history_start": calculation_start.date().isoformat(),
        "unchanged_known_problem": "The rejected run's signal-date ST/suspension prefilters remain in place before the global policy.",
        "turnover_construction": "volume / point-in-time circulation_a shares",
        "turnover_binding_status": "canonical reconstruction; the rejected worker did not persist its turnover construction lineage",
        "interpretation_guardrail": "return_1m has exact legacy parity. Weighted-factor before/after attribution is provisional because their legacy parity is not reproduced.",
        "corrections": [
            "weighted denominator is sum(turnover * decay)",
            "natural-month endpoint lookbacks with exchange-session decay distance and literal month-valued N",
            "pre-sample calculation history begins 2004-09-01 while scoring begins 2005-04-29",
        ],
        "comparison": comparison,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "comparison": comparison}, ensure_ascii=False, indent=2))


def _evaluation_panel(
    panel: pd.DataFrame,
    *,
    calendar: pd.DataFrame,
    sample_start: pd.Timestamp,
    sample_end: pd.Timestamp,
) -> pd.DataFrame:
    narrow = panel[["date", "code", "adjusted_close"]].copy()
    labels = materialize_natural_month_forward_return(
        narrow,
        1,
        trading_calendar=calendar,
        price_col="adjusted_close",
        output_col="forward_return_1m",
    )
    calendar_dates = pd.to_datetime(calendar["trade_date"])
    signal_dates = set(calendar_dates.groupby(calendar_dates.dt.to_period("M")).max())
    mask = labels["date"].isin(signal_dates) & labels["date"].between(sample_start, sample_end)
    labels = labels.loc[mask, ["date", "code", "forward_return_1m"]]
    controls = panel.loc[
        panel["date"].isin(signal_dates) & panel["date"].between(sample_start, sample_end),
        ["date", "code", "industry", "circulating_market_cap", "is_st", "is_suspended", "next_is_suspended"],
    ]
    result = controls.merge(labels, on=["date", "code"], how="left", validate="one_to_one")
    # Intentionally retain problem 4 to isolate the requested counterfactual.
    result = result.loc[
        _false_status(result["is_st"]) & _false_status(result["is_suspended"])
    ].copy()
    return result


def _evaluate_factor_set(
    evaluation_panel: pd.DataFrame,
    factors: pd.DataFrame,
    *,
    recipe: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    signal_factors = factors.loc[factors[list(FACTORS)].notna().any(axis=1)].copy()
    for factor in FACTORS:
        merged = evaluation_panel.merge(
            signal_factors[["date", "code", factor]], on=["date", "code"], how="left", validate="one_to_one"
        )
        transformed, diagnostics = apply_evaluation_recipe(merged, value_col=factor, recipe=recipe)
        metrics = compute_ic_analysis(
            transformed,
            factor_col=PROCESSED_FACTOR_COL,
            return_col="forward_return_1m",
            method="pearson",
            ic_ir_convention="absolute",
        )
        metrics["global_policy_diagnostics"] = diagnostics["global_policy"]
        result[factor] = metrics
    return result


def _load_recipe_and_metrics(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, float]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics: dict[str, dict[str, float]] = {}
    recipe = None
    for record in payload["records"]:
        factor = record["factor_name"]
        evaluator_metrics = record["evaluator_output"]["metrics"]
        metrics[factor] = _compact_metrics(evaluator_metrics)
        if recipe is None:
            recipe = record["resolved_protocol"]["evaluation_recipe"]
    if recipe is None:
        raise ValueError("source bundle has no resolved evaluation recipe")
    return recipe, metrics


def _load_legacy_callable(path: Path):
    spec = importlib.util.spec_from_file_location("huatai_momentum_rejected_legacy", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load legacy factor module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.compute_factors


def _false_status(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.notna() & numeric.eq(0)


def _load_circulating_shares(
    path: Path,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    shares = pd.read_parquet(
        path,
        columns=["symbol", "trade_date", "circulation_a"],
        filters=[
            ("trade_date", ">=", start_date),
            ("trade_date", "<=", end_date),
        ],
    ).rename(columns={"symbol": "code", "trade_date": "date"})
    shares["date"] = pd.to_datetime(shares["date"])
    shares["code"] = shares["code"].map(normalize_recommended_symbol)
    return shares


def _compact_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    keys = ("ic_mean", "ic_std", "ic_ir", "ic_positive_ratio", "ic_abs_gt_002_ratio", "cross_section_count")
    return {key: float(metrics[key]) for key in keys}


def _metric_max_abs_error(expected: dict[str, Any], actual: dict[str, Any]) -> float:
    keys = ("ic_mean", "ic_std", "ic_ir", "ic_positive_ratio", "ic_abs_gt_002_ratio", "cross_section_count")
    return max(abs(float(expected[key]) - float(actual[key])) for key in keys)


def _absolute_errors(paper: dict[str, float], actual: dict[str, Any]) -> dict[str, float]:
    return {key: abs(float(paper[key]) - float(actual[key])) for key in paper}


if __name__ == "__main__":
    main()
