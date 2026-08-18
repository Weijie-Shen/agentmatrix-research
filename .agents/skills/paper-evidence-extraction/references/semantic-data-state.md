# Semantic data value state

Stage 1 extracts semantic concepts and requested operations. Stage 3 binds each concept to a value state:

- `physical_field`;
- `semantic_concept`;
- `unit` and `price_basis`;
- `value_space` such as `level` or `log_level`;
- ordered `transform_chain`;
- `temporal_semantics` and source lineage.

Each requested transform receives `execution_mode`: `apply`, `reuse_materialized`, `blocked_unknown_state`, or `incompatible`. Preserve the paper operation even when reusing a materialized field. Never apply natural log twice.

Recommended capitalization fields are unadjusted CNY levels with an empty transform chain. QFQ/HFQ affects price-like fields, not market capitalization.
