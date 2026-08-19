from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, is_dataclass
from typing import Any

import pandas as pd


CALCULATION_CONTRACT_SCHEMA_VERSION = "factor_calculation_contract/v1"

WINDOW_METHODS = {
    "window.trailing_natural_months": "natural_month",
    "window.trailing_exchange_sessions": "exchange_session",
    "window.trailing_security_observations": "security_observation",
}

WEIGHTED_MEAN_METHOD = "aggregation.weighted_mean"
WEIGHTED_MEAN_NORMALIZATION = "sum_weighted_values_divided_by_sum_weights"

TEST_WEIGHTED_DENOMINATOR = "weighted_mean_denominator_is_sum_of_weights"
TEST_LITERAL_PARAMETER_UNITS = "literal_source_parameter_units"
TEST_NATURAL_MONTH_BOUNDARY = "natural_month_window_boundaries"
TEST_EXCHANGE_SESSION_DISTANCE = "exchange_session_distance_advances_on_missing_security_rows"
TEST_PRE_SAMPLE_HISTORY = "first_scoring_date_has_full_history"

_TEMPORAL_FORMULA_RE = re.compile(
    r"(?:\b(?:delay|delta|sum|mean|stddev|correlation|covariance|ts_[a-z0-9_]+|rolling|lookback)\s*\(|"
    r"\b(?:lookback|rolling|trailing|month|months|year|years)\b|最近|过去|个月)",
    re.IGNORECASE,
)
_WEIGHTED_FORMULA_RE = re.compile(r"(?:weighted|weight(?:ed)?[_ -]?mean|加权|\bwgt\b|wgt_)", re.IGNORECASE)
_EXPONENTIAL_FORMULA_RE = re.compile(r"(?:\bexp\s*\(|exponential|指数衰减)", re.IGNORECASE)


def calculation_contract_features(factor: Any) -> set[str]:
    """Return semantic risks that require a typed calculation contract."""

    payload = _factor_payload(factor)
    text = " ".join(
        str(payload.get(key, ""))
        for key in ("factor_id", "factor_name", "paper_label", "formula", "description")
    )
    features: set[str] = set()
    if _TEMPORAL_FORMULA_RE.search(text):
        features.add("temporal_window")
    if _WEIGHTED_FORMULA_RE.search(text):
        features.add("weighted_mean")
    if _EXPONENTIAL_FORMULA_RE.search(text):
        features.add("exponential_parameter")
    return features


def validate_factor_calculation_contract(factor: Any, *, prefix: str = "factor") -> list[str]:
    """Validate source parameters, window semantics, aggregation, and history as one contract."""

    payload = _factor_payload(factor)
    contract = payload.get("calculation_contract") or {}
    features = calculation_contract_features(payload)
    if not contract:
        if features:
            return [
                f"{prefix}.calculation_contract is required for formula features: {sorted(features)}"
            ]
        return []
    if not isinstance(contract, dict):
        return [f"{prefix}.calculation_contract must be an object"]

    errors: list[str] = []
    if contract.get("schema_version") != CALCULATION_CONTRACT_SCHEMA_VERSION:
        errors.append(
            f"{prefix}.calculation_contract.schema_version must be "
            f"{CALCULATION_CONTRACT_SCHEMA_VERSION!r}"
        )

    source_parameters = contract.get("source_parameters") or {}
    if not isinstance(source_parameters, dict):
        errors.append(f"{prefix}.calculation_contract.source_parameters must be an object")
        source_parameters = {}
    for symbol, definition in source_parameters.items():
        parameter_prefix = f"{prefix}.calculation_contract.source_parameters[{symbol!r}]"
        if not isinstance(definition, dict):
            errors.append(f"{parameter_prefix} must preserve value, unit, and role in an object")
            continue
        if "value" not in definition:
            errors.append(f"{parameter_prefix}.value is required")
        if not str(definition.get("unit", "")).strip():
            errors.append(f"{parameter_prefix}.unit is required")
        if not str(definition.get("role", "")).strip():
            errors.append(f"{parameter_prefix}.role is required")

    extracted_parameters = payload.get("parameters") or {}
    if source_parameters:
        if not isinstance(extracted_parameters, dict):
            errors.append(f"{prefix}.parameters must be an object when source parameters are declared")
            extracted_parameters = {}
        for symbol, definition in source_parameters.items():
            extracted = extracted_parameters.get(symbol)
            extracted_prefix = f"{prefix}.parameters[{symbol!r}]"
            if not isinstance(extracted, dict):
                errors.append(
                    f"{extracted_prefix} must preserve the literal source value and unit in an object"
                )
                continue
            if extracted.get("value") != definition.get("value"):
                errors.append(
                    f"{extracted_prefix}.value differs from calculation_contract.source_parameters"
                )
            if str(extracted.get("unit", "")) != str(definition.get("unit", "")):
                errors.append(
                    f"{extracted_prefix}.unit differs from calculation_contract.source_parameters"
                )

    window = contract.get("window") or {}
    if "temporal_window" in features or window:
        if not isinstance(window, dict):
            errors.append(f"{prefix}.calculation_contract.window must be an object")
            window = {}
        method_id = str(window.get("method_id", ""))
        if method_id not in WINDOW_METHODS:
            errors.append(
                f"{prefix}.calculation_contract.window.method_id must be one of {sorted(WINDOW_METHODS)}"
            )
        length = _positive_int(window.get("length"))
        if length is None:
            errors.append(f"{prefix}.calculation_contract.window.length must be a positive integer")
        source_parameter = str(window.get("source_parameter", "")).strip()
        if source_parameter:
            if source_parameter not in source_parameters:
                errors.append(
                    f"{prefix}.calculation_contract.window.source_parameter is not declared: "
                    f"{source_parameter}"
                )
            elif length is not None:
                literal = source_parameters[source_parameter].get("value")
                try:
                    matches = float(literal) == float(length)
                except (TypeError, ValueError):
                    matches = False
                if not matches:
                    errors.append(
                        f"{prefix}.calculation_contract window length must equal the literal source "
                        f"parameter {source_parameter}; derived observation counts belong in runtime_conversions"
                    )
                source_unit = str(source_parameters[source_parameter].get("unit", ""))
                unit_method = {
                    "natural_month": "window.trailing_natural_months",
                    "exchange_session": "window.trailing_exchange_sessions",
                    "security_observation": "window.trailing_security_observations",
                }.get(source_unit)
                if unit_method and method_id != unit_method:
                    errors.append(
                        f"{prefix}.calculation_contract window method {method_id!r} is incompatible "
                        f"with literal source parameter unit {source_unit!r}; preserve the source unit"
                    )
        if method_id == "window.trailing_natural_months":
            if str(window.get("endpoint_rule", "")) != "exchange_month_end_to_exchange_month_end":
                errors.append(
                    f"{prefix}.calculation_contract.window.endpoint_rule must be "
                    "'exchange_month_end_to_exchange_month_end' for natural-month windows"
                )

    aggregation = contract.get("aggregation") or {}
    if "weighted_mean" in features or aggregation:
        if not isinstance(aggregation, dict):
            errors.append(f"{prefix}.calculation_contract.aggregation must be an object")
            aggregation = {}
        if aggregation.get("method_id") != WEIGHTED_MEAN_METHOD:
            errors.append(
                f"{prefix}.calculation_contract.aggregation.method_id must be {WEIGHTED_MEAN_METHOD!r}"
            )
        if aggregation.get("normalization") != WEIGHTED_MEAN_NORMALIZATION:
            errors.append(
                f"{prefix}.calculation_contract.aggregation.normalization must be "
                f"{WEIGHTED_MEAN_NORMALIZATION!r}"
            )
        if not str(aggregation.get("value_expression", "")).strip():
            errors.append(f"{prefix}.calculation_contract.aggregation.value_expression is required")
        if not str(aggregation.get("weight_expression", "")).strip():
            errors.append(f"{prefix}.calculation_contract.aggregation.weight_expression is required")

    runtime_conversions = contract.get("runtime_conversions", []) or []
    if not isinstance(runtime_conversions, list):
        errors.append(f"{prefix}.calculation_contract.runtime_conversions must be a list")
    else:
        for index, conversion in enumerate(runtime_conversions):
            if not isinstance(conversion, dict):
                errors.append(
                    f"{prefix}.calculation_contract.runtime_conversions[{index}] must be an object"
                )
                continue
            if not str(conversion.get("derived_name", "")).strip():
                errors.append(
                    f"{prefix}.calculation_contract.runtime_conversions[{index}].derived_name is required"
                )
            if not str(conversion.get("provenance", "")).strip():
                errors.append(
                    f"{prefix}.calculation_contract.runtime_conversions[{index}].provenance is required"
                )

    distance = contract.get("distance")
    if distance is not None:
        if not isinstance(distance, dict):
            errors.append(f"{prefix}.calculation_contract.distance must be an object")
        elif distance.get("method_id") not in {
            "distance.exchange_sessions",
            "distance.security_observations",
            "distance.calendar_days",
        }:
            errors.append(
                f"{prefix}.calculation_contract.distance.method_id is unsupported: "
                f"{distance.get('method_id')!r}"
            )

    history = contract.get("history") or {}
    if "temporal_window" in features or window:
        if not isinstance(history, dict):
            errors.append(f"{prefix}.calculation_contract.history must be an object")
            history = {}
        if history.get("mode") != "full_history_before_scoring":
            errors.append(
                f"{prefix}.calculation_contract.history.mode must be 'full_history_before_scoring'"
            )
        periods = _positive_int(history.get("required_pre_sample_periods"))
        window_length = _positive_int(window.get("length")) if isinstance(window, dict) else None
        if periods is None:
            errors.append(
                f"{prefix}.calculation_contract.history.required_pre_sample_periods must be a positive integer"
            )
        elif window_length is not None and periods < window_length:
            errors.append(
                f"{prefix}.calculation_contract.history.required_pre_sample_periods cannot be shorter "
                "than the formula window"
            )
        method_id = str(window.get("method_id", "")) if isinstance(window, dict) else ""
        expected_unit = WINDOW_METHODS.get(method_id)
        if expected_unit and history.get("unit") != expected_unit:
            errors.append(
                f"{prefix}.calculation_contract.history.unit must be {expected_unit!r} for {method_id}"
            )

    required_tests = set(calculation_contract_required_test_ids(payload))
    declared_tests = {
        str(item) for item in contract.get("required_semantic_test_ids", []) or [] if str(item)
    }
    missing_tests = sorted(required_tests - declared_tests)
    if missing_tests:
        errors.append(
            f"{prefix}.calculation_contract.required_semantic_test_ids is missing {missing_tests}"
        )
    return errors


def calculation_contract_required_test_ids(factor: Any) -> list[str]:
    payload = _factor_payload(factor)
    contract = payload.get("calculation_contract") or {}
    features = calculation_contract_features(payload)
    tests: list[str] = []
    if "weighted_mean" in features:
        tests.append(TEST_WEIGHTED_DENOMINATOR)
    if "exponential_parameter" in features:
        tests.append(TEST_LITERAL_PARAMETER_UNITS)
    window = contract.get("window", {}) if isinstance(contract, dict) else {}
    if window.get("method_id") == "window.trailing_natural_months":
        tests.append(TEST_NATURAL_MONTH_BOUNDARY)
    distance = contract.get("distance", {}) if isinstance(contract, dict) else {}
    if distance.get("method_id") == "distance.exchange_sessions":
        tests.append(TEST_EXCHANGE_SESSION_DISTANCE)
    if "temporal_window" in features or window:
        tests.append(TEST_PRE_SAMPLE_HISTORY)
    return list(dict.fromkeys(tests))


def required_calculation_start(
    contract: dict[str, Any],
    scoring_start: object,
    *,
    trading_calendar: pd.DataFrame | None = None,
) -> pd.Timestamp | None:
    """Return the earliest required date for the first scored signal."""

    start = pd.Timestamp(scoring_start)
    history = contract.get("history", {}) if isinstance(contract, dict) else {}
    periods = _positive_int(history.get("required_pre_sample_periods"))
    unit = str(history.get("unit", ""))
    if periods is None:
        return None
    if unit == "natural_month":
        return start - pd.DateOffset(months=periods)
    if unit == "exchange_session" and trading_calendar is not None:
        source = "trade_date" if "trade_date" in trading_calendar.columns else "date"
        dates = pd.to_datetime(trading_calendar[source], errors="coerce").dropna().drop_duplicates().sort_values()
        before = dates[dates < start]
        if len(before) >= periods:
            return pd.Timestamp(before.iloc[-periods])
    return None


def calculation_history_errors(
    frame: pd.DataFrame,
    contract: dict[str, Any],
    *,
    scoring_start: object,
    date_column: str = "date",
    code_column: str = "code",
    trading_calendar: pd.DataFrame | None = None,
) -> list[str]:
    """Block panels that begin at the score sample instead of retaining warm-up history."""

    if date_column not in frame.columns:
        return [f"calculation history cannot be validated without {date_column!r}"]
    dates = pd.to_datetime(frame[date_column], errors="coerce").dropna()
    if dates.empty:
        return ["calculation history cannot be validated on an empty/invalid date column"]
    start = pd.Timestamp(scoring_start)
    history = contract.get("history", {}) if isinstance(contract, dict) else {}
    periods = _positive_int(history.get("required_pre_sample_periods"))
    unit = str(history.get("unit", ""))
    if periods is None:
        return ["calculation history contract has no positive required_pre_sample_periods"]

    errors: list[str] = []
    required_start = required_calculation_start(
        contract,
        start,
        trading_calendar=trading_calendar,
    )
    if required_start is not None and dates.min() > required_start:
        errors.append(
            "calculation panel starts after required pre-sample history: "
            f"actual={dates.min().date().isoformat()}, required_on_or_before={required_start.date().isoformat()}, "
            f"first_scoring_date={start.date().isoformat()}"
        )

    if unit == "natural_month":
        target_period = (start.to_period("M") - periods)
        available_periods = set(dates[dates < start].dt.to_period("M"))
        if target_period not in available_periods:
            errors.append(
                "calculation panel lacks the natural-month endpoint period required by the first score: "
                f"{target_period}"
            )
    elif unit == "exchange_session":
        unique_pre_sample = dates[dates < start].drop_duplicates().nunique()
        if unique_pre_sample < periods:
            errors.append(
                f"calculation panel has {unique_pre_sample} pre-sample exchange dates; {periods} are required"
            )
    elif unit == "security_observation" and code_column in frame.columns:
        normalized_dates = pd.to_datetime(frame[date_column], errors="coerce")
        pre_sample = frame.loc[normalized_dates < start]
        scoring_codes = set(frame.loc[normalized_dates >= start, code_column].dropna().unique())
        counts = pre_sample.groupby(code_column)[date_column].count().reindex(scoring_codes, fill_value=0)
        insufficient = counts[counts < periods]
        if not scoring_codes:
            errors.append("calculation panel has no securities on or after the first scoring date")
        elif not insufficient.empty:
            minimum = int(counts.min())
            errors.append(
                f"calculation panel has {len(insufficient)} scoring securities with fewer than {periods} "
                f"pre-sample observations; minimum={minimum}"
            )
    return errors


def calculation_contracts_hash(contracts_by_id: dict[str, dict[str, Any]]) -> str:
    encoded = json.dumps(
        contracts_by_id,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _factor_payload(factor: Any) -> dict[str, Any]:
    if isinstance(factor, dict):
        return factor
    if is_dataclass(factor):
        return asdict(factor)
    return {
        key: getattr(factor, key)
        for key in (
            "factor_id",
            "factor_name",
            "paper_label",
            "formula",
            "description",
            "parameters",
            "calculation_contract",
        )
        if hasattr(factor, key)
    }


def _positive_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None
