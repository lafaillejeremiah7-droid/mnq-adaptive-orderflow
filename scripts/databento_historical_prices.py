"""Explicitly authorized Databento historical MNQ/NQ price-bar download.

No data is downloaded unless the caller supplies a user-owned API key and
--allow-provider-charges. Each request is capped to 7 calendar days. Output is
atomic numeric OHLC in exchange tick units for the OCaml --price-replay mode.
Nothing here predicts trades or processes order flow.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from scripts.price_bar_format import format_ohlcv


def parse_dates(start: str, end: str) -> tuple[datetime, datetime]:
    """UTC half-open date range; seven days maximum per query."""
    try:
        first = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        last = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("Dates must use YYYY-MM-DD (UTC)") from exc
    if not first < last:
        raise ValueError("End date must be after start date")
    if last - first > timedelta(days=7):
        raise ValueError("Maximum 7 days per request to limit data cost")
    if last > datetime.now(timezone.utc):
        raise ValueError("Historical end date may not be in the future")
    return first, last


def symbol_type(symbol: str) -> str:
    if symbol in ("MNQ.c.0", "NQ.c.0"):
        return "continuous"
    if re.fullmatch(r"M?NQ[HMUZ][0-9]{1,2}", symbol):
        return "raw_symbol"
    raise ValueError("Use MNQ.c.0, NQ.c.0, or an outright quarterly raw symbol such as MNQZ6")


@dataclass(frozen=True)
class ContractExport:
    rows: int
    instrument_id: int
    sha256: str


def export_contract_bars(data, output_path: Path) -> ContractExport:
    """Write bars for exactly one vendor instrument, or publish nothing.

    Historical futures sessions have genuine missing minutes. They are
    retained as gaps for OCaml's segment-aware replay and are never filled.
    """
    if output_path.exists():
        raise FileExistsError(f"Refusing to replace existing file: {output_path}")
    if not output_path.parent.is_dir():
        raise FileNotFoundError(f"Output directory does not exist: {output_path.parent}")
    count = 0
    instrument_id = None
    digest = hashlib.sha256()
    previous = None
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output_path.parent,
            prefix=".mnq-price-",
            suffix=".csv.tmp",
            delete=False,
        ) as file:
            tmp_path = Path(file.name)
            for record in data:
                line = format_ohlcv(record)
                if line is None:
                    continue
                current_id = getattr(record, "instrument_id", None)
                if type(current_id) is not int or not 0 < current_id < 0xFFFFFFFF:
                    raise ValueError("Missing or invalid Databento instrument_id on OHLC bar")
                if instrument_id is None:
                    instrument_id = current_id
                elif current_id != instrument_id:
                    raise ValueError(
                        "Multiple futures instrument IDs in response. "
                        "Export each contract separately with its raw symbol."
                    )
                ts_ms = int(line.split(",", 1)[0])
                if previous is not None and ts_ms <= previous:
                    raise ValueError(
                        "Historical records contain duplicate or out-of-order timestamps"
                    )
                previous = ts_ms
                encoded = (line + "\n").encode("ascii")
                file.write(encoded)
                digest.update(encoded)
                count += 1
        if instrument_id is None:
            raise ValueError("No OHLCV minute bars returned for this interval")
        # Atomic same-directory hard-link: never expose a partially
        # written CSV and never overwrite an existing destination file.
        os.link(tmp_path, output_path)
        return ContractExport(count, instrument_id, digest.hexdigest())
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def write_price_rows(data, output_path: Path) -> int:
    """Return the number of published rows for callers using the original API."""
    return export_contract_bars(data, output_path).rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Historical MNQ/NQ price-only importer")
    parser.add_argument("--symbol", default="MNQ.c.0", help="Continuous or quarterly raw symbol")
    parser.add_argument("--start", required=True, help="UTC date, YYYY-MM-DD inclusive")
    parser.add_argument("--end", required=True, help="UTC date, YYYY-MM-DD exclusive")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-provider-charges",
        action="store_true",
        help="Explicitly acknowledge that historical data may cost money",
    )
    args = parser.parse_args()

    try:
        start, end = parse_dates(args.start, args.end)
        stype = symbol_type(args.symbol)
    except ValueError as exc:
        parser.error(str(exc))

    if not args.allow_provider_charges:
        parser.error("No historical request made. Specify --allow-provider-charges to opt in.")

    key = os.environ.get("DATABENTO_API_KEY", "").strip()
    if not key:
        print("Missing DATABENTO_API_KEY. No data request sent.", file=sys.stderr)
        return 2
    if args.output.exists():
        print("Output exists; refusing to replace it. No data requested.", file=sys.stderr)
        return 2
    try:
        import databento as db
    except ImportError:
        print("Install Databento SDK: python3 -m pip install databento", file=sys.stderr)
        return 2

    try:
        client = db.Historical(key=key)
        records = client.timeseries.get_range(
            dataset="GLBX.MDP3",
            symbols=args.symbol,
            schema="ohlcv-1m",
            stype_in=stype,
            start=start,
            end=end,
        )
        result = export_contract_bars(records, args.output)
        print(json.dumps({
            "dataset": "GLBX.MDP3",
            "schema": "ohlcv-1m",
            "symbol": args.symbol,
            "stype_in": stype,
            "start_utc_inclusive": start.isoformat(),
            "end_utc_exclusive": end.isoformat(),
            "exported_at_utc": datetime.now(timezone.utc).isoformat(),
            "timestamp_convention": "bar_start_utc_ms",
            **asdict(result),
        }, sort_keys=True))
        print(
            f"Saved {result.rows} price-only MNQ/NQ bars to {args.output}. "
            "Historical bars are not live signals.",
            file=sys.stderr,
        )
        return 0
    except Exception as exc:
        print(f"Historical request failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
