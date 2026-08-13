# Paper Factor Reproduction — Data Access Notes

These notes explain how the paper-factor-reproduction workflow should access real input panels. Prefer explicit user-provided artifacts first, then `/Users/mac/recommended_data_v2`, then Quant API v2 only as a fallback.

## Preferred local source

Use `/Users/mac/recommended_data_v2` before API access. Normal workflow code should use the loader below and should not select physical files itself. The loader resolves these canonical datasets:

| File | Use |
|---|---|
| `kline_raw_rqdata.parquet` | RQData unadjusted daily OHLCV/amount, cumulative factors, factor-event dates, historical ST status, suspension status, and explicit price-observation flags; 2000-01-04 to 2026-08-06 |
| `market_cap_history_rqdata.parquet` | 2000-01-04 to 2026-08-10 PIT total, A-share, circulating-A, free-float capitalization, and share fields |
| `trading_calendar.parquet` | China exchange trading calendar used to map `T+h` labels |
| `security_master.parquet` | security master |
| `financial_statements_pit_rqdata.parquet` | versioned PIT balance-sheet, income, and cash-flow fields |
| `valuation_factors_rqdata.parquet` | daily valuation factors, including decimal and raw dividend-yield fields |
| `dividend_events_rqdata.parquet` / `dividend_amount_history_rqdata.parquet` | declaration-date and information-date dividend histories |
| `standard_index_daily_levels.parquet` | provider-unadjusted standard-index levels |
| `index_components_rqdata/` | annual effective-date constituent partitions |
| `index_weights_monthly_rqdata/` / `index_weights_daily_rqdata/` | distinct monthly and daily weight families |
| `china_government_yield_curve.parquet` | decimal annual government yields by explicit tenor |
| `industry_membership_history_rqdata.parquet` | interval memberships for `sws`, `citics`, `citics_2019`, and `gildata`, by level |
| `industry_taxonomy_history_rqdata.parquet` | historical taxonomy names and parent relationships |

Recommended helper:

```python
from research_core.factor_lab.paper_reproduction.recommended_data import (
    apply_a_share_recommended_filters,
    IndustryClassificationSelection,
    load_recommended_paper_panels,
)

panels = load_recommended_paper_panels(
    test_end_date=paper_test_end,
    start_date=paper_data_start,
    end_date=paper_test_end,
    include_status=True,
    market_cap_fields=("market_cap", "free_float_market_cap"),
    industry_classification=IndustryClassificationSelection(paper_industry_source, paper_industry_level),
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
selected capitalization fields and point-in-time `industry`/industry-provenance columns.

Select capitalization semantics from the paper: `market_cap` maps to total
`market_cap_3`, while `a_share_market_cap`, `circulating_market_cap`, and
`free_float_market_cap` remain distinct. Capitalization is already on an
unadjusted price basis and must not be rescaled for QFQ/HFQ. Select industry
source and level explicitly and resolve membership with
`start_date <= evaluation_or_formation_date < cancel_date`; never replace an
unavailable paper taxonomy with a present-day snapshot silently.

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
- Use `load_recommended_financial_statements(...)` for PIT statements; enforce `ann_date <= T` before version selection and record the version policy. Do not silently interpret year-to-date Q2/Q3/Q4 income or cash-flow values as standalone quarters.
- Use `load_recommended_valuation_panel(...)` and `load_recommended_dividend_history(...)` for valuation and dividend inputs. The normalized dividend-yield columns are decimal yields.
- Use the `recommended_reference` loaders for trading dates, index levels, effective-date membership, explicit monthly/daily weights, and selected yield tenors. `materialize_calendar_forward_return(...)` maps `T+h` on the exchange calendar and leaves the label missing when that security has no price on the exact target date.

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
