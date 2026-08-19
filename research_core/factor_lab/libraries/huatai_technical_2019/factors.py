from __future__ import annotations

import numpy as np
import pandas as pd

FACTORS = ("Alpha3", "Alpha13", "Alpha15", "Alpha16", "Alpha44", "Alpha50", "Alpha55")

def _rank(frame: pd.DataFrame, value: pd.Series) -> pd.Series:
    return value.groupby(frame["date"], sort=False).rank(pct=True, method="average")

def _roll(frame: pd.DataFrame, left: pd.Series, right: pd.Series, window: int, cov: bool = False) -> pd.Series:
    work = pd.DataFrame({"code": frame["code"].to_numpy(), "left": left.to_numpy(), "right": right.to_numpy()})
    if cov:
        out = work.groupby("code", sort=False).apply(lambda x: x["left"].rolling(window, min_periods=window).cov(x["right"]), include_groups=False)
    else:
        out = work.groupby("code", sort=False).apply(lambda x: x["left"].rolling(window, min_periods=window).corr(x["right"]), include_groups=False)
    return out.reset_index(level=0, drop=True).reindex(frame.index)

def compute_factors(panel: pd.DataFrame, selected_factors: list[str] | None = None) -> pd.DataFrame:
    required = {"date", "code", "open", "high", "low", "close", "volume", "amount"}
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    frame = panel.sort_values(["code", "date"]).reset_index(drop=True).copy()
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    vwap = pd.to_numeric(frame["amount"], errors="coerce") / volume.replace(0, np.nan)
    ro = _rank(frame, frame["open"]); rh = _rank(frame, frame["high"]); rc = _rank(frame, frame["close"]); rv = _rank(frame, volume); rw = _rank(frame, vwap)
    raw = {
        "Alpha3": -_roll(frame, ro, rv, 10),
        "Alpha13": -_rank(frame, _roll(frame, rc, rv, 5, cov=True)),
        "Alpha15": -_rank(frame, _roll(frame, rh, rv, 3)),
        "Alpha16": -_rank(frame, _roll(frame, rh, rv, 5, cov=True)),
        "Alpha44": -_roll(frame, frame["high"], rv, 5),
        "Alpha50": -_rank(frame, _roll(frame, rv, rw, 5)),
        "Alpha55": -_roll(frame, _rank(frame, (frame["close"] - frame.groupby("code")["low"].transform(lambda x: x.rolling(12, min_periods=12).min())) / (frame.groupby("code")["high"].transform(lambda x: x.rolling(12, min_periods=12).max()) - frame.groupby("code")["low"].transform(lambda x: x.rolling(12, min_periods=12).min())).replace(0, np.nan)), rv, 6),
    }
    # Alpha15/50 are time-series sums/max, not correlations with constants.
    raw["Alpha15"] = raw["Alpha15"].groupby(frame["code"], sort=False).transform(lambda x: x.rolling(3, min_periods=3).sum())
    raw["Alpha50"] = raw["Alpha50"].groupby(frame["code"], sort=False).transform(lambda x: x.rolling(5, min_periods=5).max())
    selected = selected_factors or list(FACTORS)
    return pd.concat([frame[["date", "code"]], pd.DataFrame({name: raw[name] for name in selected})], axis=1).replace([np.inf, -np.inf], np.nan)
