# Return-label method catalog

`return.forward_close_to_close` declares future close-to-close stock return. Record `horizon_exchange_days`, `output_field`, price-adjustment view, signal/target timing, and exchange-calendar rule.

Keep security-observation, exact exchange-calendar, and whole-natural-month horizons distinct. Missing return labels are pairwise dropped only when IC is computed; they are not factor missing exposure.

Use `custom.paper_defined` for another return construction and retain literal paper evidence.
