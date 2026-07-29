#!/usr/bin/env python3
"""Build canonical wide-coverage files for recommended_data_v2.

The source files are retained as provenance. Outputs are written atomically so a
failed refresh cannot replace the last complete canonical dataset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq


DEFAULT_DATA_DIR = Path("/Users/mac/recommended_data_v2")


def _normalized_symbol(column: str = "symbol") -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.String)
        .str.replace(r"\.XSHE$", ".SZ")
        .str.replace(r"\.XSHG$", ".SH")
    )


def _atomic_sink(frame: pl.LazyFrame, destination: Path) -> None:
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    if temporary.exists():
        temporary.unlink()
    frame.sink_parquet(temporary, compression="zstd", statistics=True)
    os.replace(temporary, destination)


def build_security_status(data_dir: Path) -> Path:
    st_sources = [
        data_dir / "st_status_2010_2016.parquet",
        data_dir / "st_status_full.parquet",
    ]
    rich_source = data_dir / "security_status_through_2026-04-09.parquet"
    for path in [*st_sources, rich_source]:
        if not path.exists():
            raise FileNotFoundError(path)

    # The broad ST histories are authoritative for is_st. The rich source adds
    # trading, suspension, and limit fields where its shorter window overlaps.
    broad_st = pl.concat(
        [
            pl.scan_parquet(path)
            .select(_normalized_symbol().alias("symbol"), pl.col("trade_date").cast(pl.Date), pl.col("is_st"))
            for path in st_sources
        ]
    )
    rich = (
        pl.scan_parquet(rich_source)
        .with_columns(_normalized_symbol().alias("symbol"), pl.col("trade_date").cast(pl.Date))
        .drop("is_st")
    )
    unified = broad_st.join(rich, on=["symbol", "trade_date"], how="left").sort(["symbol", "trade_date"])
    destination = data_dir / "security_status.parquet"
    _atomic_sink(unified, destination)
    return destination


def build_market_cap(data_dir: Path) -> Path:
    broad_source = data_dir / "market_cap_2010_2026.parquet"
    recent_source = data_dir / "shares_market_cap_recent_2026-06-22_onward.parquet"
    for path in (broad_source, recent_source):
        if not path.exists():
            raise FileNotFoundError(path)

    broad = pl.scan_parquet(broad_source).select(
        _normalized_symbol("order_book_id").alias("symbol"),
        pl.col("date").cast(pl.Date).alias("trade_date"),
        pl.col("market_cap"),
    )
    recent_shares = pl.scan_parquet(recent_source).select(
        _normalized_symbol().alias("symbol"),
        pl.col("trade_date").cast(pl.Date),
        pl.col("total"),
        pl.col("circulation_a"),
        pl.col("free_circulation"),
    )
    unified = broad.join(recent_shares, on=["symbol", "trade_date"], how="left").sort(["symbol", "trade_date"])
    destination = data_dir / "market_cap.parquet"
    _atomic_sink(unified, destination)
    return destination


def update_manifest(data_dir: Path, outputs: list[Path]) -> None:
    manifest_path = data_dir / "MANIFEST.json"
    existing = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    output_names = {path.name for path in outputs}
    entries = [entry for entry in existing if entry.get("file") not in output_names]
    for path in outputs:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        metadata = pq.ParquetFile(path).metadata
        entries.append(
            {
                "file": path.name,
                "bytes": path.stat().st_size,
                "rows": metadata.num_rows,
                "columns": metadata.schema.names,
                "sha256": digest.hexdigest(),
                "role": "canonical",
            }
        )
    entries.sort(key=lambda entry: entry.get("file", ""))
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(entries, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()
    outputs = [build_security_status(args.data_dir), build_market_cap(args.data_dir)]
    update_manifest(args.data_dir, outputs)
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
