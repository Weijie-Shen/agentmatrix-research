# Recommended Data Contracts

Read `/Users/mac/recommended_data_v2/README.md` and the linked dataset notes for current coverage and provider caveats. Use repository loaders rather than recreating temporal joins.

| Requirement | API | Required selection |
|---|---|---|
| Daily stock panel | `load_recommended_daily_panel` | Paper dates, QFQ/HFQ view, formula fields |
| Financial statements | `load_recommended_financial_statements` | Fields, historical `as_of_date`, version policy |
| Valuation/dividend yield | `load_recommended_valuation_panel` | Fields, dates, decimal/raw convention |
| Dividend events/history | `load_recommended_dividend_history` | Event family and historical information cutoff |
| Trading calendar | `load_recommended_trading_calendar` | Date range including label look-ahead |
| Benchmark levels | `load_recommended_index_levels` | Exact index identifier and dates |
| Index constituents | `load_recommended_index_constituents` | Exact index identifier and effective dates |
| Index weights | `load_recommended_index_weights` | Exact index identifier and explicit `monthly` or `daily` family |
| Government curve | `load_recommended_yield_curve` | Exact tenor and dates |

## Point-in-time rules

- Statements: enforce `ann_date <= T` before choosing a version. The logical version key is `symbol, report_period, ann_date, if_adjusted, rice_create_tm`. Preserve all versions when the paper requires revision history. Treat most Q2/Q3/Q4 income and cash-flow fields as fiscal-year-to-date unless the paper supports standalone-quarter use.
- Valuation: provider ratios are exact only when their definition matches the paper. Canonical dividend yields are decimal fractions; retained raw yields use the documented provider scale.
- Dividend events: use declaration or `info_date` availability, not a later ex/pay date, to decide what was known.
- Constituents/weights: join by `effective_date`; `provider_create_tm` is ingestion lineage. Never use a current list retrospectively.
- Weight families: monthly provider weights and reconstructed daily weights are distinct protocols. Never select or combine them implicitly.
- Calendar: map `T+h` using the exchange calendar and preserve the look-ahead dates needed to form labels. A missing security price at the target date remains missing.
- Yield curve: stored values are decimal annual rates. Record tenor and any day-count or period conversion explicitly.

## Scenario boundaries

Stock QFQ/HFQ multipliers apply only to stock price-like fields. Never apply them to capitalization, shares, financial statements, valuation ratios, index levels, index weights, or yield curves. Keep reference inputs in the evaluation context rather than widening the rolling calculation panel unless the paper formula directly requires them.
