# Extraction patterns

## One table, many factors

One homogeneous table becomes one truth source; put all printed factor rows in `reported_results`. Each covered factor may select that same truth-source ID.

## One table, heterogeneous row blocks

If raw factors and sequentially orthogonalized factors use different preprocessing, create separate truth sources with the same table locator and different `row_block` values.

## Ordered missing and preprocessing

If a paper says standardize then replace missing exposure with zero, encode z-score first and `factor_missing.fill_zero` second. Do not move missing handling to a fixed global position.

## Sequential neutralization

Encode industry residualization and subsequent log-market-cap/beta residualization as two neutralization steps. Keep log market cap as a transform on the market-cap control so Stage 3 can apply or reuse it based on value state.
