#!/usr/bin/env python3
"""Fetch selected RQData reference datasets without writing local files."""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

DATASETS = {
    "calendar",
    "index-levels",
    "index-components",
    "index-weights",
    "yield-curve",
}
PRICE_FIELDS = {
    "open",
    "high",
    "low",
    "close",
    "prev_close",
    "volume",
    "total_turnover",
}
DEFAULT_PRICE_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "prev_close",
    "volume",
    "total_turnover",
)
DEFAULT_REMOTE_PYTHON = "/home/data/conda-envs/rqsdk/bin/python"
SSH_TARGET_RE = re.compile(r"^[A-Za-z0-9_.@:-]+$")
REMOTE_PYTHON_RE = re.compile(r"^/[A-Za-z0-9_./-]+$")


def _normal_date(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    try:
        parsed = (
            dt.datetime.strptime(text, "%Y%m%d").date()
            if len(text) == 8 and text.isdigit()
            else dt.date.fromisoformat(text)
        )
    except ValueError as exc:
        raise ValueError(
            f"invalid date {value!r}; use YYYY-MM-DD or YYYYMMDD"
        ) from exc
    return parsed.isoformat()


def _tuple(value: Iterable[str] | str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = value.split(",")
    return tuple(item.strip() for item in value if item and item.strip())


@dataclass(frozen=True)
class QueryRequest:
    dataset: str
    start_date: str | None = None
    end_date: str | None = None
    date: str | None = None
    indices: tuple[str, ...] = ()
    index_id: str | None = None
    fields: tuple[str, ...] = ()
    weight_frequency: str | None = None
    tenors: tuple[str, ...] = ()
    market: str = "cn"

    def normalized(self) -> "QueryRequest":
        request = QueryRequest(
            dataset=self.dataset.strip().lower(),
            start_date=_normal_date(self.start_date),
            end_date=_normal_date(self.end_date),
            date=_normal_date(self.date),
            indices=_tuple(self.indices),
            index_id=self.index_id.strip() if self.index_id else None,
            fields=_tuple(self.fields),
            weight_frequency=(
                self.weight_frequency.strip().lower()
                if self.weight_frequency
                else None
            ),
            tenors=_tuple(self.tenors),
            market=self.market.strip().lower(),
        )
        request.validate()
        return request

    def validate(self) -> None:
        if self.dataset not in DATASETS:
            raise ValueError(f"unsupported dataset {self.dataset!r}")
        if self.market != "cn":
            raise ValueError("this skill supports only market='cn'")
        if self.date and (self.start_date or self.end_date):
            raise ValueError("specify date or start/end, not both")
        if bool(self.start_date) != bool(self.end_date):
            raise ValueError("start_date and end_date must be supplied together")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not be later than end_date")
        if self.dataset in {"calendar", "index-levels", "yield-curve"} and not (
            self.start_date and self.end_date
        ):
            raise ValueError(f"{self.dataset} requires start_date and end_date")
        if self.dataset in {"index-components", "index-weights"} and not (
            self.date or (self.start_date and self.end_date)
        ):
            raise ValueError(f"{self.dataset} requires date or start_date/end_date")
        if self.dataset == "index-levels":
            if not self.indices:
                raise ValueError("index-levels requires at least one index")
            unknown = set(self.fields or DEFAULT_PRICE_FIELDS) - PRICE_FIELDS
            if unknown:
                raise ValueError(
                    f"unsupported index price fields: {sorted(unknown)}"
                )
        if self.dataset in {"index-components", "index-weights"} and not self.index_id:
            raise ValueError(f"{self.dataset} requires index_id")
        if (
            self.dataset == "index-weights"
            and self.weight_frequency not in {"monthly", "daily"}
        ):
            raise ValueError(
                "index-weights requires weight_frequency monthly or daily"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "QueryRequest":
        data = dict(value)
        for key in ("indices", "fields", "tenors"):
            data[key] = _tuple(data.get(key))
        return cls(**data).normalized()


def _canonical_columns(frame: Any) -> Any:
    columns = {}
    for column in frame.columns:
        text = str(column)
        lowered = text.strip().lower().replace(" ", "_")
        if lowered in {"order_book_id", "orderbookid", "instrument", "symbol"}:
            columns[column] = "order_book_id"
        elif lowered in {"date", "datetime", "trade_date", "trading_date"}:
            columns[column] = "date"
        elif lowered in {"weight", "weights", "value", "0"}:
            columns[column] = "weight"
    return frame.rename(columns=columns)


def _as_frame(value: Any, value_name: str | None = None) -> Any:
    import pandas as pd

    if isinstance(value, pd.Series):
        frame = value.rename(value.name or value_name or "value").to_frame()
    elif isinstance(value, pd.DataFrame):
        frame = value.copy()
    else:
        frame = pd.DataFrame(value)
    if not isinstance(frame.index, pd.RangeIndex) or any(
        name is not None for name in getattr(frame.index, "names", [])
    ):
        frame = frame.reset_index()
    return _canonical_columns(frame)


def _query_calendar(provider: Any, request: QueryRequest) -> Any:
    import pandas as pd

    dates = provider.get_trading_dates(
        request.start_date, request.end_date, market=request.market
    )
    return pd.DataFrame({"trade_date": pd.to_datetime(list(dates))})


def _query_index_levels(provider: Any, request: QueryRequest) -> Any:
    frame = _as_frame(
        provider.get_price(
            list(request.indices),
            start_date=request.start_date,
            end_date=request.end_date,
            frequency="1d",
            fields=list(request.fields or DEFAULT_PRICE_FIELDS),
            adjust_type="none",
            skip_suspended=False,
            expect_df=True,
            market=request.market,
        )
    )
    if "order_book_id" not in frame and len(request.indices) == 1:
        frame.insert(0, "order_book_id", request.indices[0])
    required = {"order_book_id", "date"}
    if not required.issubset(frame.columns):
        missing = sorted(required - set(frame.columns))
        raise RuntimeError(f"RQData index-level response lacks keys {missing}")
    return frame.sort_values(["order_book_id", "date"]).reset_index(drop=True)


def _component_rows(
    index_id: str, effective_date: str, payload: Any
) -> list[dict[str, Any]]:
    components, create_tm = (
        payload
        if isinstance(payload, tuple) and len(payload) == 2
        else (payload, None)
    )
    return [
        {
            "index_id": index_id,
            "effective_date": effective_date,
            "component_id": component,
            "provider_create_tm": create_tm,
        }
        for component in (components or [])
    ]


def _query_index_components(provider: Any, request: QueryRequest) -> Any:
    import pandas as pd

    kwargs: dict[str, Any] = {
        "market": request.market,
        "return_create_tm": True,
    }
    if request.date:
        kwargs["date"] = request.date
        raw = provider.index_components(request.index_id, **kwargs)
        rows = _component_rows(request.index_id or "", request.date, raw)
    else:
        kwargs.update(start_date=request.start_date, end_date=request.end_date)
        raw = provider.index_components(request.index_id, **kwargs)
        rows = []
        for effective_date, payload in sorted(
            raw.items(), key=lambda item: str(item[0])
        ):
            rows.extend(
                _component_rows(
                    request.index_id or "", str(effective_date)[:10], payload
                )
            )
    frame = pd.DataFrame(
        rows,
        columns=[
            "index_id",
            "effective_date",
            "component_id",
            "provider_create_tm",
        ],
    )
    for column in ("effective_date", "provider_create_tm"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def _query_index_weights(provider: Any, request: QueryRequest) -> Any:
    import pandas as pd

    endpoint = (
        provider.index_weights_ex
        if request.weight_frequency == "daily"
        else provider.index_weights
    )
    kwargs: dict[str, Any] = {}
    if request.date:
        kwargs["date"] = request.date
    else:
        kwargs.update(start_date=request.start_date, end_date=request.end_date)
    if request.weight_frequency == "daily":
        kwargs["market"] = request.market
    frame = _as_frame(endpoint(request.index_id, **kwargs), value_name="weight")
    if "order_book_id" not in frame.columns:
        unnamed = [
            column
            for column in frame.columns
            if str(column).lower().startswith("level_")
        ]
        if unnamed:
            frame = frame.rename(columns={unnamed[-1]: "order_book_id"})
    if "date" not in frame.columns and request.date:
        frame.insert(0, "date", request.date)
    if "weight" not in frame.columns:
        candidates = [
            column
            for column in frame.columns
            if column not in {"date", "order_book_id"}
        ]
        if len(candidates) == 1:
            frame = frame.rename(columns={candidates[0]: "weight"})
    required = {"date", "order_book_id", "weight"}
    if not required.issubset(frame.columns):
        missing = sorted(required - set(frame.columns))
        raise RuntimeError(f"RQData index-weight response lacks columns {missing}")
    frame = frame.rename(
        columns={"date": "effective_date", "order_book_id": "component_id"}
    )
    frame.insert(0, "index_id", request.index_id)
    frame["effective_date"] = pd.to_datetime(
        frame["effective_date"], errors="coerce"
    )
    frame["weight_frequency"] = request.weight_frequency
    columns = [
        "index_id",
        "effective_date",
        "component_id",
        "weight",
        "weight_frequency",
    ]
    return frame[columns].sort_values(
        ["effective_date", "component_id"]
    ).reset_index(drop=True)


def _query_yield_curve(provider: Any, request: QueryRequest) -> Any:
    kwargs: dict[str, Any] = {
        "start_date": request.start_date,
        "end_date": request.end_date,
        "market": request.market,
    }
    if len(request.tenors) == 1:
        kwargs["tenor"] = request.tenors[0]
    frame = _as_frame(provider.get_yield_curve(**kwargs))
    if "date" not in frame.columns:
        raise RuntimeError("RQData yield-curve response lacks date")
    if len(request.tenors) > 1:
        missing = set(request.tenors) - set(frame.columns)
        if missing:
            raise RuntimeError(
                f"yield-curve response lacks requested tenors {sorted(missing)}"
            )
        frame = frame[["date", *request.tenors]]
    return frame.sort_values("date").reset_index(drop=True)


def execute_query(request: QueryRequest, provider: Any) -> Any:
    request = request.normalized()
    handlers = {
        "calendar": _query_calendar,
        "index-levels": _query_index_levels,
        "index-components": _query_index_components,
        "index-weights": _query_index_weights,
        "yield-curve": _query_yield_curve,
    }
    return handlers[request.dataset](provider, request)


def _source_api(request: QueryRequest) -> str:
    if request.dataset == "index-weights":
        return (
            "rqdatac.index_weights_ex"
            if request.weight_frequency == "daily"
            else "rqdatac.index_weights"
        )
    return {
        "calendar": "rqdatac.get_trading_dates",
        "index-levels": "rqdatac.get_price",
        "index-components": "rqdatac.index_components",
        "yield-curve": "rqdatac.get_yield_curve",
    }[request.dataset]


def _set_provenance(frame: Any, request: QueryRequest, transport: str) -> Any:
    frame.attrs["rqdata_provenance"] = {
        "source": "RQData",
        "source_api": _source_api(request),
        "request": request.to_dict(),
        "retrieved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "transport": transport,
        "persistence": "none_process_scoped",
    }
    return frame


def _arrow_bytes(frame: Any) -> bytes:
    import pyarrow as pa
    import pyarrow.ipc as ipc

    table = pa.Table.from_pandas(frame, preserve_index=False)
    metadata = dict(table.schema.metadata or {})
    metadata[b"rqdata_provenance"] = json.dumps(
        frame.attrs.get("rqdata_provenance", {}), sort_keys=True
    ).encode()
    table = table.replace_schema_metadata(metadata)
    sink = pa.BufferOutputStream()
    with ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def _frame_from_arrow(payload: bytes) -> Any:
    import pyarrow as pa
    import pyarrow.ipc as ipc

    table = ipc.open_stream(pa.py_buffer(payload)).read_all()
    frame = table.to_pandas()
    raw = (table.schema.metadata or {}).get(b"rqdata_provenance")
    if raw:
        frame.attrs["rqdata_provenance"] = json.loads(raw.decode())
    return frame


def _local_fetch(request: QueryRequest) -> Any:
    try:
        import rqdatac
    except ImportError as exc:
        raise RuntimeError(
            "rqdatac is unavailable; use an authenticated RQData host or "
            "configure RQDATA_SSH_TARGET"
        ) from exc
    with contextlib.redirect_stdout(sys.stderr):
        rqdatac.init()
        frame = execute_query(request, rqdatac)
    return _set_provenance(frame, request, "local")


def _ssh_fetch(
    request: QueryRequest,
    ssh_target: str,
    remote_python: str,
    *,
    remote_shell_init: bool = False,
) -> Any:
    if not SSH_TARGET_RE.fullmatch(ssh_target) or ssh_target.startswith("-"):
        raise ValueError(
            "invalid SSH target; use a configured host alias or user@host"
        )
    if not REMOTE_PYTHON_RE.fullmatch(remote_python):
        raise ValueError(
            "remote Python must be an absolute path without shell metacharacters"
        )
    encoded = base64.urlsafe_b64encode(
        json.dumps(request.to_dict(), sort_keys=True).encode()
    ).decode()
    remote_argv = [remote_python, "-", "--remote-worker", encoded]
    if remote_shell_init:
        remote_command = "exec " + " ".join(
            shlex.quote(value) for value in remote_argv
        )
        command = [
            "ssh",
            "-T",
            ssh_target,
            f"bash -ic {shlex.quote(remote_command)}",
        ]
    else:
        command = ["ssh", "-T", ssh_target, *remote_argv]
    result = subprocess.run(
        command,
        input=Path(__file__).read_bytes(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(
            f"remote RQData query failed (exit {result.returncode}): "
            f"{detail[-2000:]}"
        )
    frame = _frame_from_arrow(result.stdout)
    provenance = dict(frame.attrs.get("rqdata_provenance", {}))
    provenance["transport"] = (
        "ssh_arrow_stream_interactive_shell"
        if remote_shell_init
        else "ssh_arrow_stream"
    )
    frame.attrs["rqdata_provenance"] = provenance
    return frame


def fetch_reference(
    request: QueryRequest,
    *,
    transport: str = "auto",
    ssh_target: str | None = None,
    remote_python: str | None = None,
    remote_shell_init: bool | None = None,
    max_rows: int = 2_000_000,
) -> Any:
    """Return an in-memory DataFrame; never write a local file."""
    request = request.normalized()
    target = ssh_target or os.environ.get("RQDATA_SSH_TARGET")
    selected = (
        "ssh"
        if transport == "auto" and target
        else ("local" if transport == "auto" else transport)
    )
    if selected not in {"local", "ssh"}:
        raise ValueError("transport must be auto, local, or ssh")
    if selected == "ssh":
        if not target:
            raise ValueError(
                "SSH transport requires RQDATA_SSH_TARGET or ssh_target"
            )
        frame = _ssh_fetch(
            request,
            target,
            remote_python
            or os.environ.get("RQDATA_REMOTE_PYTHON", DEFAULT_REMOTE_PYTHON),
            remote_shell_init=(
                _environment_flag("RQDATA_REMOTE_SHELL_INIT")
                if remote_shell_init is None
                else remote_shell_init
            ),
        )
    else:
        frame = _local_fetch(request)
    if max_rows <= 0:
        raise ValueError("max_rows must be positive")
    if len(frame) > max_rows:
        raise RuntimeError(
            f"query returned {len(frame):,} rows, exceeding "
            f"max_rows={max_rows:,}; narrow the request"
        )
    return frame


def _environment_flag(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return False
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"{name} must be one of 1/0, true/false, yes/no, or on/off"
    )


def _request_from_args(args: argparse.Namespace) -> QueryRequest:
    return QueryRequest(
        dataset=args.dataset,
        start_date=getattr(args, "start", None),
        end_date=getattr(args, "end", None),
        date=getattr(args, "date", None),
        indices=tuple(getattr(args, "indices", ()) or ()),
        index_id=getattr(args, "index_id", None),
        fields=_tuple(getattr(args, "fields", None)),
        weight_frequency=getattr(args, "frequency", None),
        tenors=_tuple(getattr(args, "tenors", None)),
        market="cn",
    ).normalized()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transport", choices=("auto", "local", "ssh"), default="auto"
    )
    parser.add_argument(
        "--ssh-target",
        help="Configured SSH alias or user@host; never a password",
    )
    parser.add_argument(
        "--remote-python",
        help=f"Remote Python path (default: {DEFAULT_REMOTE_PYTHON})",
    )
    parser.add_argument(
        "--remote-shell-init",
        action="store_true",
        default=None,
        help=(
            "Run remote Python through bash -ic so a preconfigured shell may "
            "initialize RQData; never places credentials on the command line"
        ),
    )
    parser.add_argument(
        "--format", choices=("summary", "jsonl", "arrow"), default="summary"
    )
    parser.add_argument("--max-rows", type=int, default=2_000_000)
    subparsers = parser.add_subparsers(dest="dataset", required=True)

    calendar = subparsers.add_parser("calendar")
    calendar.add_argument("--start", required=True)
    calendar.add_argument("--end", required=True)

    levels = subparsers.add_parser("index-levels")
    levels.add_argument(
        "--index", dest="indices", action="append", required=True
    )
    levels.add_argument("--start", required=True)
    levels.add_argument("--end", required=True)
    levels.add_argument("--fields", default=",".join(DEFAULT_PRICE_FIELDS))

    components = subparsers.add_parser("index-components")
    components.add_argument("--index", dest="index_id", required=True)
    components.add_argument("--date")
    components.add_argument("--start")
    components.add_argument("--end")

    weights = subparsers.add_parser("index-weights")
    weights.add_argument("--index", dest="index_id", required=True)
    weights.add_argument(
        "--frequency", choices=("monthly", "daily"), required=True
    )
    weights.add_argument("--date")
    weights.add_argument("--start")
    weights.add_argument("--end")

    curve = subparsers.add_parser("yield-curve")
    curve.add_argument("--start", required=True)
    curve.add_argument("--end", required=True)
    curve.add_argument("--tenor", dest="tenors", action="append")
    return parser


def _emit(frame: Any, output_format: str) -> None:
    if output_format == "arrow":
        sys.stdout.buffer.write(_arrow_bytes(frame))
    elif output_format == "jsonl":
        sys.stdout.write(
            frame.to_json(
                orient="records", lines=True, date_format="iso"
            )
        )
        if len(frame):
            sys.stdout.write("\n")
    else:
        summary = {
            "rows": len(frame),
            "columns": list(frame.columns),
            "provenance": frame.attrs.get("rqdata_provenance", {}),
            "preview": json.loads(
                frame.head(5).to_json(orient="records", date_format="iso")
            ),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def _remote_worker(encoded_request: str) -> int:
    request = QueryRequest.from_dict(
        json.loads(base64.urlsafe_b64decode(encoded_request.encode()))
    )
    frame = _local_fetch(request)
    sys.stdout.buffer.write(_arrow_bytes(frame))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 2 and argv[0] == "--remote-worker":
        return _remote_worker(argv[1])
    args = _parser().parse_args(argv)
    request = _request_from_args(args)
    frame = fetch_reference(
        request,
        transport=args.transport,
        ssh_target=args.ssh_target,
        remote_python=args.remote_python,
        remote_shell_init=args.remote_shell_init,
        max_rows=args.max_rows,
    )
    _emit(frame, args.format)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
