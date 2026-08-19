# Paper Reproduction Project — Progress Report

**Benchmark snapshot:** 3 August 2026

**Repository handoff status:** 19 August 2026

> This report preserves the measured Huatai benchmark results from the local
> research runs. For the current framework architecture, validated test command,
> skills, RQData setup, and next-owner checklist, read
> [`docs/PAPER_REPRODUCTION_HANDOFF.md`](docs/PAPER_REPRODUCTION_HANDOFF.md).
> Large source panels and generated workbooks remain local and are intentionally
> excluded from Git.

## Executive Summary

The paper-reproduction pipeline is now **operational end to end**. An agent can read a paper, extract factor definitions and reported benchmarks, prepare data, implement factors, run evaluations, compare results with the paper, and preserve a full evidence package.

We have completed several full tests on seven factors from the Huatai paper: **Alpha3, Alpha13, Alpha15, Alpha16, Alpha44, Alpha50, and Alpha55**. The pipeline produced factor values for millions of stock-date observations and completed both paper-metric comparisons and external factor-value comparisons.

The central result is clear:

> The pipeline reproduces the factors' direction and broad signal very well, but it does not yet reproduce the paper's exact numerical results.

This is meaningful progress. The current challenge is no longer whether the pipeline can finish a reproduction. It can. The challenge is aligning our data and calculation protocol closely enough with the paper to achieve truth-level agreement.

## 1. What Has Been Achieved

The complete workflow has successfully:

- extracted the seven Huatai factor formulas and evaluation benchmarks;
- generated executable factor implementations;
- passed factor and pipeline test suites;
- calculated and saved full factor-value panels;
- run IC and regression evaluations;
- compared reproduced metrics with the paper;
- compared Alpha13 values with an independent external factor source; and
- preserved code, specifications, reports, factor panels, and checksums for audit.

### Scale of the completed run

| Output | Result |
|---|---:|
| Historical factor panel | **6,019,470 rows** |
| Historical period | 2010-01-04 to 2019-06-28 |
| Historical securities | **3,667** |
| Recent factor panel | **7,277,562 rows** |
| Recent period | 2020-01-02 to 2026-07-22 |
| Recent securities | **5,392** |
| Duplicate `(date, code)` keys | **0** |
| Factor implementation tests | **16 passed** in the full-period rerun |
| Reproduction-framework tests | **85 passed** |

The run is therefore not a prototype demonstration. It is a complete large-panel reproduction workflow with auditable outputs.

## 2. Comparison with the Huatai Paper

### 2020–2026 unneutralized Rank IC test

This run compared our results with the paper's Table 7 values. All seven reproduced factors retained the paper's positive direction.

| Factor | Reproduced Rank IC | Paper Rank IC | Relative gap | Reproduced IC IR | Paper IC IR |
|---|---:|---:|---:|---:|---:|
| Alpha3 | 0.0419 | 0.0496 | −15.6% | 0.758 | 0.91 |
| Alpha13 | 0.0534 | 0.0592 | −9.8% | 0.835 | 0.95 |
| Alpha15 | 0.0387 | 0.0457 | −15.3% | 0.740 | 0.85 |
| Alpha16 | 0.0531 | 0.0573 | −7.3% | 0.836 | 0.91 |
| Alpha44 | 0.0498 | 0.0596 | −16.4% | 0.806 | 0.89 |
| Alpha50 | 0.0446 | 0.0541 | −17.5% | 0.738 | 0.87 |
| Alpha55 | 0.0375 | 0.0477 | −21.4% | 0.729 | 0.90 |

**Interpretation:** the signal direction is reproduced consistently. Alpha13 and Alpha16 are the closest. Magnitudes remain systematically lower than the paper, so this is strong directional evidence, not an exact match.

### Full-period Table 52 proxy test

The fuller 2010–2019 run also completed. Its implementation and pipeline tests passed, and all seven factors again showed the expected positive direction. However, only **1–5 of eight metrics per factor** were within 10% of the paper values.

The largest relative metric errors were:

| Factor | Largest relative error |
|---|---:|
| Alpha3 | 34.6% |
| Alpha13 | 27.9% |
| Alpha15 | 73.8% |
| Alpha16 | 51.4% |
| Alpha44 | 41.7% |
| Alpha50 | 69.8% |
| Alpha55 | 29.3% |

This run used OLS because the paper's free-float-market-cap WLS weight was unavailable. It is therefore a completed proxy evaluation, not an exact reproduction of Table 52.

## 3. Comparison with an Independent Factor Source

We compared the reproduced Alpha13 values with an external WorldQuant Alpha13 dataset.

### Direct value comparison

| Measure | Result |
|---|---:|
| External truth rows in 2020–2026 | 131,015 |
| Matched non-null values | **123,715** |
| Key coverage | **94.52%** |
| Pearson correlation | **0.9717** |
| Spearman correlation | **0.9719** |
| Mean daily Spearman | **0.9683** |
| Median daily Spearman | **0.9761** |
| Mean absolute difference | 0.0384 |
| Median absolute difference | 0.0198 |
| Aggregate relative error | 7.66% |
| Exact matches | 13 |

### Value-agreement rates

| Tolerance | Values within tolerance |
|---|---:|
| 0.01 | 32.46% |
| 0.05 | 76.82% |
| 0.10 | 91.18% |
| Difference greater than 0.10 | 8.82% |

### Portfolio-bucket agreement

| Comparison | Agreement |
|---|---:|
| Same quintile | 82.67% |
| Same decile | 68.83% |
| Same or adjacent decile | 95.42% |

**Interpretation:** our Alpha13 captures essentially the same cross-sectional signal as the independent source. It is highly rank-consistent and broadly value-consistent, but it is not formula-level identical.

## 4. Reproducibility Across Pipeline Runs

Two recent factor panels were aligned over exactly **7,277,562 identical stock-date keys**. Their common-value correlations were between **0.9979 and 0.999997**.

| Factor | Correlation between runs | Common values differing by more than 0.1 |
|---|---:|---:|
| Alpha3 | 0.99791 | 0.244% |
| Alpha13 | 0.99972 | 0.047% |
| Alpha15 | 0.999997 | 0.0005% |
| Alpha16 | 0.99977 | 0.045% |
| Alpha44 | 0.99945 | 0.070% |
| Alpha50 | 0.99989 | 0.017% |
| Alpha55 | 0.99935 | 0.100% |

The system is therefore highly stable over common coverage. Exact equality failed mainly because the newer run omitted the 2019 warm-up period and changed some partial-window rules. For Alpha3, **17,685 of 17,713** material differences occurred in only 23 dates at the start of 2020.

This gives us a concrete improvement: load a formula-derived warm-up period, calculate factors, and only then trim to the requested output dates.

## 5. Why the Paper Values Do Not Yet Match

### Leading cause 1: insufficient protocol-equivalent data

Earlier testing used only 2017–2019 against paper results calculated over 2010–2019. The fuller run improved coverage, but exact paper inputs are still unavailable:

- the paper uses square-root free-float market capitalization for WLS;
- our complete historical equivalent was unavailable, so OLS was used;
- industry data is a current/static mapping rather than verified point-in-time history;
- provider universe and security-status history may differ from the paper; and
- the paper does not provide daily factor values, daily IC series, or portfolio curves for point-by-point verification.

This makes exact Table 52 reproduction impossible with the current inputs, even when the pipeline completes successfully.

### Price adjustment is now an explicit two-view protocol

The retired adjusted K-line source has been replaced by
`kline_raw_rqdata.parquet`, an RQData `adjust_type="none"` panel with raw OHLC,
raw turnover fields, cumulative factor history, historical ST status, suspension
status, and explicit price-observation flags.

Every paper reproduction now runs two price views from the same raw observations:

- testing-end-anchored QFQ: `raw_price[t] * F[t] / F[test_end]`;
- initial-baseline HFQ: `raw_price[t] * F[t]`.

The test end is supplied by each paper configuration rather than hard-coded.
OHLC, price limits, `prev_close`, and derived `amount / volume` VWAP use the same
view multiplier; volume and amount are not adjusted. Results from the two views
must be computed and reported separately.

The new primary panel contains 17,508,571 unique security-date rows for 5,542
securities from 2000-01-04 through 2026-08-06. Factor recursion, raw OHLC
integrity, status-only null behavior, and the published checksum were independently
verified. Remaining source caveats are explicit: 1,051 non-suspended price gaps,
27,724 provider-returned zero-volume rows, and a small minority of raw VWAP/candle
inconsistencies.

### Other measured contributors

- Eligibility filters were applied before rolling-factor calculation, changing each stock's history.
- The 20-day return used the next 20 surviving stock rows, not explicitly 20 market-calendar trading days.
- Some 5-, 6-, and 10-day operators accepted only three observations.
- Missing values were sometimes filled despite the paper's `do_not_fill` policy.
- Some evaluations used a common complete-case sample across all seven factors instead of a per-factor sample.

These are fixable pipeline semantics and may explain additional residual differences.

## 6. Current Assessment

| Question | Answer |
|---|---|
| Can the agent complete the full reproduction workflow? | **Yes** |
| Can it process full-market, multi-year data? | **Yes** |
| Are the factor implementations and pipeline mechanically stable? | **Yes** |
| Do reproduced factors have the same broad signal as the paper? | **Yes** |
| Does Alpha13 agree with an independent factor source? | **Strongly at signal level** |
| Are exact factor values reproduced? | **No** |
| Are the paper's exact evaluation metrics reproduced? | **No** |
| Is the main remaining problem identifiable? | **Yes: data/protocol fidelity and calculation semantics** |

## 7. Next Milestone

The next milestone is a controlled sensitivity study, not another framework rewrite:

1. Use raw OHLC/VWAP for factor formulas and a separately validated adjusted close for returns.
2. Normalize and validate the adjustment-factor history before using the new adjusted dataset.
3. Compute factors on unfiltered history; apply eligibility only at the correct signal or entry date.
4. Enforce full rolling windows and formula-derived warm-up periods.
5. Build forward returns on the market trading calendar.
6. Compare raw-price and adjusted-price runs against both the paper and the external Alpha13 source.
7. Report which changes improve value agreement and which affect only coverage.

## Meeting Takeaway

The project has crossed an important threshold: **it can autonomously complete a large-scale paper reproduction and produce auditable evidence**.

The results already show strong signal recovery—seven of seven factors have the expected direction, Alpha13 reaches approximately **0.972 correlation** with an independent source, and repeat runs correlate above **0.9979**. The remaining gap is exact truth matching.

Our next phase is therefore focused and measurable: align the price-adjustment convention, strengthen historical data equivalence, and remove the remaining calculation-protocol differences. If these changes close the numerical gap, we will have moved from a functioning reproduction agent to a credible research-validation system.
