from __future__ import annotations

import os
from dataclasses import dataclass

import pandas as pd


@dataclass(slots=True)
class QuantApiConfig:
    token: str
    base_url: str = "http://115.159.73.134:8765"

    @classmethod
    def from_env(cls, env_var: str = "QUANT_API_TOKEN") -> QuantApiConfig:
        token = os.environ.get(env_var, "").strip()
        if not token:
            raise ValueError(f"{env_var} is required for Quant API access")
        return cls(token=token)

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def __repr__(self) -> str:
        return f"QuantApiConfig(base_url={self.base_url!r}, token='***')"


AMOUNT_CANDIDATES = ("amount", "total_turnover", "turnover", "money")


def normalize_quant_daily_kline_frame(raw_frame: pd.DataFrame) -> pd.DataFrame:
    required = ["trade_date", "symbol", "open", "high", "low", "close", "volume"]
    missing = [column for column in required if column not in raw_frame.columns]
    if missing:
        raise ValueError(f"missing Quant API daily kline columns: {', '.join(missing)}")
    amount_column = next((column for column in AMOUNT_CANDIDATES if column in raw_frame.columns), "")
    if not amount_column:
        raise ValueError(f"amount column not found; tried: {', '.join(AMOUNT_CANDIDATES)}")

    panel = raw_frame[["trade_date", "symbol", "open", "high", "low", "close", "volume", amount_column]].copy()
    panel = panel.rename(columns={"trade_date": "date", "symbol": "code", amount_column: "amount"})
    panel["date"] = pd.to_datetime(panel["date"])
    return panel[["date", "code", "open", "high", "low", "close", "volume", "amount"]]
