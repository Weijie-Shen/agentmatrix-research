# Paper Factor Reproduction — Data Access Notes

These notes explain how the paper-factor-reproduction workflow should access real input panels. Prefer explicit user-provided artifacts first, then `/Users/mac/recommended_data_v2`, then Quant API v2 only as a fallback.

## Preferred local source

Use `/Users/mac/recommended_data_v2` before API access. Normal workflow code should use the loader below and should not select physical files itself. The loader resolves these canonical datasets:

| File | Use |
|---|---|
| `kline_raw_rqdata.parquet` | RQData unadjusted daily OHLCV/amount, cumulative factors, factor-event dates, historical ST status, suspension status, and explicit price-observation flags; 2000-01-04 to 2026-08-06 |
| `market_cap.parquet` | unified daily market capitalization for 2010-01-04 to 2026-07-22, plus recent share fields |
| `trading_calendar.parquet` | trading calendar |
| `security_master.parquet` | security master |
| `income_statement.parquet` / `balance_sheet.parquet` | point-in-time fundamentals |
| `dividend_yield.parquet` | daily dividend yield |
| `industry_map.parquet` | current industry mapping snapshot |

Recommended helper:

```python
from research_core.factor_lab.paper_reproduction.recommended_data import (
    apply_a_share_recommended_filters,
    load_recommended_paper_panels,
)

panels = load_recommended_paper_panels(
    test_end_date=paper_test_end,
    start_date=paper_data_start,
    end_date=paper_test_end,
    include_status=True,
    include_market_cap=True,
    include_industry=True,
)
qfq_panel = apply_a_share_recommended_filters(panels["qfq"])
hfq_panel = apply_a_share_recommended_filters(panels["hfq"])
```

This returns Factor Lab-style daily columns such as:

```text
date, code, open, high, low, close, volume, amount
```

with raw audit columns, `vwap`, `is_trading`, `is_st`, `is_suspended`,
`has_price_observation`, `next_is_suspended`, factor fields, and optional
`market_cap`/`industry`.

Every paper reproduction must run both price conventions from the same raw panel:

```text
QFQ(t; T) = raw_price(t) * ex_cum_factor(t) / ex_cum_factor(T)
HFQ(t)    = raw_price(t) * ex_cum_factor(t)
```

`T` is the paper's testing-period end and is configuration, never a fixed
Huatai-specific date. The same multiplier applies to OHLC, VWAP, price limits,
and `prev_close`; `volume` and `amount` remain unchanged. Do not mix the two
views inside one factor/evaluation run.

Loader rules:

- `load_recommended_paper_panels(test_end_date=...)` is the normal paper-reproduction entry point and always returns `qfq` and `hfq` panels.
- `load_recommended_daily_panel(..., price_view="raw"|"qfq"|"hfq")` remains available for explicit diagnostics and non-paper workflows.
- `resolve_recommended_data_sources()` reports the physical files selected for diagnostics; do not use it to hand-pick smaller sources.
- Filter price computations to `has_price_observation=true`; the standard A-share filter also requires positive volume through derived `is_trading`.
- Status-only rows remain null and must not be forward-filled.
- `has_factor_event` is authoritative; do not infer event presence solely from `ex_factor != 1`, because valid unit-factor events exist.

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

For daily price-volume factors not covered by `/Users/mac/recommended_data_v2`, prefer API table `ods_kline_1d`.

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

Before selecting a paper truth case for evaluation, build a structured data profile with `build_data_profile(...)` and feed it into `build_paper_evaluation_plan(..., data_profiles={...})` or `assess_evaluation_case_support(...)`. Formula-required missing fields can block factor implementation; evaluation-only gaps should become deviations, proxy/reduced-period cases, deferred evaluator targets, or `not_evaluated` truth outcomes.

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

Proceed to factor implementation if formula-required validation is valid. Formula-stage failures block implementation; evaluation-only gaps should be handled by evaluation support assessment and documented degradation.

```python
result.valid
```

## Current open adapter questions

- Confirm exact turnover/amount column name returned by `ods_kline_1d`.
- Confirm whether `symbol` is always `000001.SZ` style in ClickHouse output.
- Confirm if Quant API date output arrives as string/date/datetime in JSON vs Parquet.
- Decide whether to implement a repo-level Quant API adapter or keep API access as a skill-driven external data acquisition step.
