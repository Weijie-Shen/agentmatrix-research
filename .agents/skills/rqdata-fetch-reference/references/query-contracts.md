# Query contracts and interpretation

## Dataset schemas

`calendar`

- Key: `trade_date`
- Source call: `rqdatac.get_trading_dates(..., market="cn")`
- Use exchange dates for label horizons and market-day mapping. Do not derive a complete exchange calendar from security observations.

`index-levels`

- Key: `order_book_id`, `date`
- Default fields: `open`, `high`, `low`, `close`, `prev_close`, `volume`, `total_turnover`
- Source call: daily `rqdatac.get_price(..., adjust_type="none", skip_suspended=False, expect_df=True)`
- Index levels are benchmark observations. Do not apply equity QFQ/HFQ multipliers.

`index-components`

- Key: `index_id`, `effective_date`, `component_id`
- Additional lineage: `provider_create_tm` when RQData returns it
- Source call: `rqdatac.index_components(..., return_create_tm=True)`
- Treat each returned date as a provider snapshot. Use the snapshot effective for the paper's formation or evaluation date; never backfill a present-day list through history.

`index-weights`

- Key: `index_id`, `effective_date`, `component_id`
- Value: `weight`
- Lineage: `weight_frequency` is `monthly` or `daily`
- Monthly source: `rqdatac.index_weights`; RQData documents this dataset as monthly updated.
- Daily source: `rqdatac.index_weights_ex`; use only when the requested index is supported and the paper needs daily weights. RQData documents these weights as reconstructed from month-end constituents, market movement, and, during specified adjustment intervals for supported indices, ETF creation/redemption lists. They are not interchangeable with monthly published snapshots.

`yield-curve`

- Key: `date`; tenor columns retain provider names such as `1M` and `1Y`
- Source call: `rqdatac.get_yield_curve(..., market="cn")`
- RQData describes this as the ChinaBond China government yield curve, available from 2002 onward. Preserve provider units and document any conversion before using it as a risk-free rate.

## Request and provenance rules

- Use ISO dates (`YYYY-MM-DD`) or compact dates (`YYYYMMDD`).
- Specify either `date` or the complete `start_date`/`end_date` pair for constituents and weights.
- Use one explicit weight frequency; never fall back between endpoints.
- Retain `rqdata_provenance` from the returned DataFrame. It includes dataset, normalized request, UTC retrieval time, transport, source API, and persistence policy.
- Enforce an explicit `max_rows` bound. A response exceeding it fails instead of truncating.
- Treat provider creation time as lineage, not as the effective membership date.

## Non-persistence contract

The bundled client does not expose a file-output option and uses an Arrow IPC stream for remote transport. The client holds the response in memory. Callers must not add disk caching, durable temporary files, repository artifacts, or copies under `/Users/mac/recommended_data_v2`.
