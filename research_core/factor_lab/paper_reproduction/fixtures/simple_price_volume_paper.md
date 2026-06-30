# Simple Price-Volume Signals

Authors: Factor Lab Team
Source: Factor Lab fixture
Year: 2026

## Summary

This short fixture paper defines two daily price-volume signals for liquid common stocks.
The intended sample period is 2020-01-01 to 2020-12-31.
Prices should be adjusted, and observations should be sorted by date and code before evaluation.

## Factors

### pv_close_to_open

Formula: `(close - open) / open`

Required fields: `open`, `close`

Frequency: day

Description: Daily close-to-open return.

### pv_volume_momentum_5d

Formula: `volume / mean(volume, 5) - 1`

Required fields: `volume`

Frequency: day

Description: Volume relative to its 5-day moving average.

## Evaluation

Evaluate daily rank IC and a long-short quintile spread. The portfolio rule is long top quintile and short bottom quintile.

## Paper-Reported Truth Sources

The paper reports both point-in-time factor values and evaluation metrics for `pv_close_to_open`.

Table 2 reports calculated `pv_close_to_open` values for the 2020 sample:

| date | code | pv_close_to_open |
|---|---|---:|
| 2020-01-02 | AAA | 0.01 |
| 2020-01-02 | BBB | -0.02 |

Table 3 reports evaluation results for both factors over the 2020 sample:

| factor | rank IC mean | rank IC IR |
|---|---:|---:|
| pv_close_to_open | 0.042 | 0.31 |
| pv_volume_momentum_5d | 0.018 | 0.12 |

If point-in-time factor values are available, reproduction should match those values. If only evaluation
results are available, reproduction should match the reported evaluation method and metrics instead.
