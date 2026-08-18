# Preprocessing method catalog

Use these IDs instead of free-form method dictionaries:

| Method ID | Category | Main parameters | Scope |
|---|---|---|---|
| `factor_missing.drop` | factor exposure missing | none | current ordered step |
| `factor_missing.fill_zero` | factor exposure missing | none | current ordered step |
| `factor_missing.use_previous_exchange_day` | factor exposure missing | `maximum_age_exchange_days: 1` | same security, exact prior exchange session |
| `factor_missing.none` | factor exposure missing | none | explicit no-imputation |
| `winsorize.median_mad` | winsorization | `threshold` | cross-section by signal date |
| `transform.natural_log` | value transform | none | declared input only |
| `standardize.cross_sectional_zscore` | standardization | `ddof` if paper states it | cross-section by signal date |

Missing policy here applies only to missing factor exposure. It is ordered with all other preprocessing. Do not use unconstrained forward fill: previous-day imputation is only from the exact preceding exchange session.

If no catalog method faithfully represents the paper, use `custom.paper_defined` with literal source text, narrow evidence location, inputs, outputs, parameters, and capability requirement.
