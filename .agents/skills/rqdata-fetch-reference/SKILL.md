---
name: rqdata-fetch-reference
description: Fetch RQData reference and evaluation datasets on demand without local persistence. Use for China benchmark or index daily levels, point-in-time index constituents, monthly or supported daily index weights, the China exchange trading calendar, and the China government yield curve when a paper-reproduction or factor-evaluation job needs data that should not be copied into recommended_data_v2 or cached in the repository.
---

# RQData On-Demand Reference Data

First check the canonical reference datasets documented in `/Users/mac/recommended_data_v2/README.md` and use repository loaders when they cover the exact identifier, convention, and dates. Fetch only a missing, unsupported, or newer reference slice required by the active calculation or evaluation. Keep fetched results in memory or stream them through stdout; never create a local dataset cache.

## Security and persistence boundary

- Use an already authenticated local RQData environment or a preconfigured SSH alias. Let SSH perform normal host-key verification.
- Never accept, request, print, embed, or persist an SSH password, RQData license URI, API token, or private key.
- Never pass a credential as a command-line argument or add one to a script, environment example, report, or provenance record.
- Never use `--output`, shell redirection to a file, `tee`, Parquet/CSV writers, or promotion into `recommended_data_v2`.
- Treat the returned frame as process-scoped. Release it after the consuming evaluation finishes.
- If authentication is unavailable, stop with a configuration limitation. Do not recover credentials from attachments, shell history, repository files, or prior logs.

## Choose the query

Do not fetch merely because a local caller has not yet inspected the canonical bundle. Use on-demand access for out-of-coverage dates, unsupported indices/tenors, or an explicitly requested newer provider snapshot. Record why local data was insufficient.

Use `scripts/rqdata_reference.py` for:

- `index-levels`: daily OHLC, volume, turnover, and previous close for one or more benchmark/index identifiers;
- `index-components`: point-in-time or ranged constituent snapshots with provider creation time when available;
- `index-weights`: monthly provider weights, or supported daily reconstructed weights when explicitly required;
- `calendar`: China-market exchange trading dates;
- `yield-curve`: China government yield-curve observations.

Read [query-contracts.md](references/query-contracts.md) before choosing index-weight frequency, interpreting a constituent snapshot, or joining yield-curve observations.

## Configure the execution environment

Prefer a local authenticated RQData Python environment when available:

```bash
python .agents/skills/rqdata-fetch-reference/scripts/rqdata_reference.py \
  --transport local calendar --start 2010-01-01 --end 2020-12-31
```

For a licensed remote environment, configure only a normal SSH destination and optional Python path:

```bash
export RQDATA_SSH_TARGET=rqdata-host
export RQDATA_REMOTE_PYTHON=/home/data/conda-envs/rqsdk/bin/python
```

The SSH destination must resolve through the user's SSH configuration, agent, keychain, or another secure system facility. Do not add password automation or disable host-key checking.

## Fetch and consume

For agent inspection, use the default `summary` format. It prints schema, row count, provenance, and a small preview without saving the dataset:

```bash
python .agents/skills/rqdata-fetch-reference/scripts/rqdata_reference.py \
  index-levels --index 000300.XSHG --index 000905.XSHG \
  --start 2010-01-01 --end 2019-04-30
```

For Python evaluation code, import the module and keep the result in memory:

```python
from pathlib import Path
import importlib.util
import sys

path = Path(".agents/skills/rqdata-fetch-reference/scripts/rqdata_reference.py")
spec = importlib.util.spec_from_file_location("rqdata_reference", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

request = module.QueryRequest(
    dataset="calendar",
    start_date="2010-01-01",
    end_date="2019-04-30",
)
calendar = module.fetch_reference(request)
```

Use `--format arrow` or `--format jsonl` only for a direct pipe into a consuming process. Do not redirect either stream into a file.

## Validate use in a reproduction

1. Record the full request and returned provenance from `DataFrame.attrs["rqdata_provenance"]`.
2. Validate required columns, date coverage, key uniqueness, and missingness before evaluation.
3. Keep the calculation panel separate from evaluation-only reference inputs.
4. Join constituents and weights by their effective date; do not substitute current membership for historical membership.
5. Report unsupported daily weights, missing dates, or unavailable entitlements as non-blocking evaluation limitations unless the dataset is a formula input.
6. Do not claim local-data completeness merely because the on-demand query succeeded.

## Failure behavior

- Treat RQData authentication, entitlement, and network failures as explicit data-access limitations.
- Treat malformed dates, unsupported fields, ambiguous date/range combinations, and excessive row counts as blocking query errors.
- Never silently shorten the period, switch monthly weights to daily weights, replace one benchmark with another, or persist a partial response.
- Retry only idempotent reads. Re-run the same request after connectivity returns.
