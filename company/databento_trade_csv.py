"""Offline adapter from Databento 'trades' DataFrame CSV to canonical tick CSV.

Input is an export of DBNStore.to_df(pretty_px=True, map_symbols=True), not
raw nanounit price records. No remote API calls, purchases, or credential use.
"""
import argparse
import csv
import io
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from quantlab import ticks
from company.market_profile import BILLION, COLUMNS, CONTRACT


def parse_event_ns(text: str) -> int:
    if isinstance(text, str) and re.fullmatch(r"[0-9]{18,20}", text):
        return int(text)
    match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|\+00:00|\+0000)",
        text or "",
    )
    if not match:
        raise ValueError("ts_event must be UTC ISO with timezone or epoch nanoseconds")
    dt = datetime.fromisoformat(match.group(1).replace(" ", "T")).replace(tzinfo=timezone.utc)
    whole_ns = int(dt.timestamp()) * BILLION
    return whole_ns + int((match.group(2) or "").ljust(9, "0") or "0")


def convert(input_csv: bytes, contract: str) -> bytes:
    if not isinstance(contract, str) or not CONTRACT.fullmatch(contract):
        raise ValueError("requires one NQ/MNQ quarterly contract")
    reader = csv.DictReader(io.StringIO(input_csv.decode("utf-8-sig"), newline=""))
    required = {"ts_event", "sequence", "symbol", "price", "size", "side"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("missing Databento export columns: " + ",".join(sorted(required)))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    last = None
    observations = 0
    for row in reader:
        if set(row) != set(reader.fieldnames) or any(v is None for v in row.values()):
            raise ValueError("malformed vendor row")
        if row["symbol"] != contract:
            raise ValueError("mixed symbols: export exactly one outright contract")
        if "action" in row and row["action"] not in ("T", "Trade"):
            raise ValueError("expected Databento trades schema, not book updates")
        ns = parse_event_ns(row["ts_event"])
        sequence = int(row["sequence"])
        if sequence < 0 or (last is not None and (ns, sequence) <= last):
            raise ValueError("out-of-order timestamp/sequence")
        last = (ns, sequence)
        p = ticks(row["price"]) / 4
        size = int(row["size"])
        if size <= 0:
            raise ValueError("invalid trade size")
        if row["side"] not in ("B", "A", "N"):
            raise ValueError("unknown aggressor-side encoding")
        writer.writerow([ns, contract, f"{p:.2f}", size, row["side"], sequence])
        observations += 1
    if not observations:
        raise ValueError("no input trades")
    return out.getvalue().encode("utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--contract", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    try:
        payload = convert(args.input.read_bytes(), args.contract)
        with args.output.open("xb") as handle:
            handle.write(payload)
    except (OSError, ValueError, TypeError, InvalidOperation, UnicodeError) as e:
        p.exit(2, "trade import rejected: " + str(e) + "\n")
    print("saved", args.output, "bytes", len(payload))


if __name__ == "__main__":
    main()
