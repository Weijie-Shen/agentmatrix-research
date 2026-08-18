# Return-label method catalog

`return.forward_close_to_close` declares future close-to-close stock return. Always record one typed `interval_type`; do not reduce every numeric horizon to trading days.

| `interval_type` | Required horizon field | Meaning |
|---|---|---|
| `security_observation_days` | `horizon_security_observations` | The next retained observations for each security. Use only when the paper defines that behavior. |
| `exchange_calendar_days` | `horizon_exchange_days` | Exact exchange sessions from the signal date, independent of a security's surviving rows. |
| `following_whole_natural_month` | `horizon_natural_months` | The complete following calendar month or months, ending on the exchange calendar's last session. |
| `next_evaluation_period` | `horizon_periods` | The next period defined by the signal/evaluation schedule. Resolve it only when the schedule makes the target unambiguous. |
| `fixed_date_interval` | `horizon_periods` | A paper-declared start/target date rule that does not fit the other types; preserve that rule explicitly. |

Also record `output_field`, price-adjustment view, signal/target timing, exchange-calendar rule, and literal evidence. Treat `T+1 period` as a period-relative expression. A monthly schedule does not make it a one-exchange-day horizon; require explicit trading-day evidence before using `exchange_calendar_days`.

Keep security-observation, exact exchange-calendar, and whole-natural-month horizons distinct. Missing return labels are pairwise dropped only when IC is computed; they are not factor missing exposure.

Use `custom.paper_defined` for another return construction and retain literal paper evidence.
