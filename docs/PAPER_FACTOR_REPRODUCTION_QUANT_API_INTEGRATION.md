# Paper Factor Reproduction — Data Access Notes

These notes explain how the paper-factor-reproduction workflow should access real input panels. Prefer explicit user-provided artifacts first, then `/Users/mac/recommended_data`, then Quant API v2 only as a fallback.

## Preferred local source

Use `/Users/mac/recommended_data` before API access. It contains curated Parquet files:

| File | Use |
|---|---|
| `kline_adj.parquet` | daily OHLCV, amount, adjustment factors, adjusted OHLC |
| `security_status.parquet` | trading, ST, suspension, and price-limit status |
| `market_cap_full.parquet` | daily market capitalization |
| `calendar.parquet` | trading calendar |
| `stock_info.parquet` | security master |
| `income_stmt.parquet` / `balance_sheet.parquet` | point-in-time fundamentals |
| `dividend_yield_v2.parquet` | daily dividend yield |

Recommended helper:

```python
from research_core.factor_lab.paper_reproduction.recommended_data import (
    apply_a_share_recommended_filters,
    load_recommended_daily_panel,
)

panel = load_recommended_daily_panel(
    start_date="2020-01-02",
    end_date="2026-04-09",
    adjusted=True,
    include_status=True,
    include_market_cap=True,
)
panel = apply_a_share_recommended_filters(panel)
```

This returns Factor Lab-style daily columns such as:

```text
date, code, open, high, low, close, volume, amount
```

with optional `is_trading`, `is_st`, `is_suspended`, limit flags, and `market_cap`.

## Quant API fallback

## Security rule

Do **not** write API tokens into source files, tests, generated specs, runtime artifacts, or committed docs. Read the token from an environment variable or an operator-provided runtime secret.

Recommended environment variable:

```bash
export QUANT_API_TOKEN="sk-..."
```

## Required API preflight

Before using API data endpoints, verify connectivity and available sources:

```python
import os
import requests

BASE = "http://115.159.73.134:8765"
TOK = os.environ["QUANT_API_TOKEN"]
H = {"Authorization": f"Bearer {TOK}"}


def call(path, params=None):
    r = requests.get(f"{BASE}{path}", params=params, headers=H, timeout=30)
    r.raise_for_status()
    return r.json()

whoami = call("/whoami")
sources = call("/sources")
ch = call("/ch")
```

If `/whoami` fails with 401, stop and ask for a valid admin token.

## Mapping extracted data requirements to API data

For daily price-volume factors not covered by `/Users/mac/recommended_data`, prefer API table `ods_kline_1d`.

Expected normalized input columns for Factor Lab:

```text
date, code, open, high, low, close, volume, amount
```

Quant API daily K columns usually use:

```text
trade_date, symbol, open, high, low, close, volume, total_turnover/amount-like columns
```

The adapter/pipeline should normalize:

| Factor Lab | Quant API likely source |
|---|---|
| `date` | `trade_date` |
| `code` | `symbol` |
| `open` | `open` |
| `high` | `high` |
| `low` | `low` |
| `close` | `close` |
| `volume` | `volume` |
| `amount` | turnover/amount column after inspecting returned schema |

## Endpoint choice

Use the API skill's decision tree:

- Small exploratory queries: JSON `/ch/{table}`.
- Input panels above ~10k rows: Parquet `/ch/{table}/parquet`.
- Very large tables: slice by `symbol`, `start_date`, `end_date`.

Example daily K download:

```python
import pandas as pd
import requests

r = requests.get(
    f"{BASE}/ch/ods_kline_1d/parquet",
    params={"start_date": "2020-01-01", "end_date": "2020-12-31"},
    headers=H,
    stream=True,
    timeout=300,
)
r.raise_for_status()
with open("runtime/factor_lab/frames/simplepv_input.parquet", "wb") as f:
    for chunk in r.iter_content(1024 * 1024):
        f.write(chunk)

panel = pd.read_parquet("runtime/factor_lab/frames/simplepv_input.parquet")
```

## Integration point with current code

After loading and normalizing a dataframe, run:

```python
from research_core.factor_lab.paper_reproduction.data_validation import (
    DataFrameValidationRequest,
    validate_input_frame,
)

request = DataFrameValidationRequest.from_factor(extracted_factor)
result = validate_input_frame(panel, request)
```

Only proceed to factor implementation if:

```python
result.valid and result.status == "passed"
```

If `needs_human_review`, write the validation result into the pipeline state and stop that stage.

## Current open adapter questions

- Confirm exact turnover/amount column name returned by `ods_kline_1d`.
- Confirm whether `symbol` is always `000001.SZ` style in ClickHouse output.
- Confirm if Quant API date output arrives as string/date/datetime in JSON vs Parquet.
- Decide whether to implement a repo-level Quant API adapter or keep API access as a skill-driven external data acquisition step.
