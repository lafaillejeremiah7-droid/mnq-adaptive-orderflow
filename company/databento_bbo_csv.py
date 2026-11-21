"""Offline Databento MBP-1 CSV -> normalized BBO tick quote adapter.

Input must come from an already obtained and permitted GLBX.MDP3 mbp-1
DataFrame CSV with pretty_px=True and mapped outright symbols. This is NOT
a licensed feed downloader or an MBO/order-queue reconstruction.

For timing-sensitive scenarios, bad receive timestamps, book resets and
partial/crossed snapshots fail closed instead of inventing executable quotes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from company.databento_trade_csv import parse_event_ns
from company.execution_replay import FIELDS as QUOTE_FIELDS
from company.market_profile import CONTRACT
from quantlab import ticks

COLUMNS = {
    "ts_event", "ts_recv", "sequence", "symbol", "rtype",
    "publisher_id", "instrument_id", "flags", "action",
    "bid_px_00", "bid_sz_00", "ask_px_00", "ask_sz_00",
}
LAST_FLAG = 1 << 7
BAD_TS_RECV = 1 << 3


def convert(raw, contract):
    if not isinstance(contract, str) or CONTRACT.fullmatch(contract) is None:
        raise ValueError("Databento adapter requires one quarterly NQ/MNQ contract")
    if not isinstance(raw, bytes):
        raise ValueError("Databento adapter input must be bytes")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    except UnicodeError as exc:
        raise ValueError("MBP-1 export must be UTF-8") from exc
    if reader.fieldnames is None or not COLUMNS.issubset(reader.fieldnames):
        raise ValueError("missing required MBP-1 DataFrame fields; check pretty_px and index")
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(QUOTE_FIELDS)
    seen_instrument = None
    seen_publisher = None
    previous = None
    discarded_partial = 0
    count = 0
    for row in reader:
        if set(row) != set(reader.fieldnames) or any(value is None for value in row.values()):
            raise ValueError("malformed MBP-1 vendor row")
        if row["symbol"] != contract:
            raise ValueError("mixed symbols; export only one quarterly outright")
        if row["rtype"] != "1":
            raise ValueError("MBP-1 rtype must be 1; cannot mix TBBO/MBO/trades")
        if row["action"] not in ("A", "C", "M", "T"):
            raise ValueError("unsupported MBP-1 action or book clear; cannot assume BBO continuity")
        try:
            flags, publisher, instrument = (
                int(row["flags"]), int(row["publisher_id"]), int(row["instrument_id"])
            )
            sequence = int(row["sequence"])
            bid_size, ask_size = int(row["bid_sz_00"]), int(row["ask_sz_00"])
        except ValueError as exc:
            raise ValueError("invalid integer in vendor quote row") from exc
        if (not 0 <= flags <= 255 or publisher < 0 or instrument < 1
                or sequence < 0 or bid_size < 0 or ask_size < 0):
            raise ValueError("invalid vendor quote enum, ID, sequence, or size")
        if flags & BAD_TS_RECV:
            raise ValueError("MBP-1 receive-time quality flag invalidates latency research")
        if seen_instrument is not None and instrument != seen_instrument:
            raise ValueError("instrument_id changes within one mapped contract export")
        if seen_publisher is not None and publisher != seen_publisher:
            raise ValueError("publisher_id changes within one mapped contract export")
        seen_instrument, seen_publisher = instrument, publisher
        event, received = parse_event_ns(row["ts_event"]), parse_event_ns(row["ts_recv"])
        if received < event:
            raise ValueError("MBP-1 receive timestamp precedes exchange event")
        key = (received, sequence)
        if previous is not None and key <= previous:
            raise ValueError("MBP-1 receive/sequence order is invalid")
        previous = key
        # LAST marks the last update in a matching-engine event; avoid using
        # intermediate snapshots before all legs of the event are visible.
        if not flags & LAST_FLAG:
            discarded_partial += 1
            continue
        if not bid_size or not ask_size:
            raise ValueError("missing book side; cannot assume executable BBO")
        bid, ask = ticks(row["bid_px_00"]), ticks(row["ask_px_00"])
        if bid >= ask:
            raise ValueError("locked or crossed vendor BBO")
        writer.writerow((event, received, contract, bid, bid_size, ask, ask_size, sequence))
        count += 1
    if count == 0:
        raise ValueError("MBP-1 export has no complete, valid top-of-book records")
    converted = output.getvalue().encode("utf-8")
    return converted, {
        "status": "offline_mbp1_normalization_only",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "output_sha256": hashlib.sha256(converted).hexdigest(),
        "contract": contract,
        "records": count,
        "discarded_intermediate_event_rows": discarded_partial,
        "vendor_instrument_id": seen_instrument,
        "vendor_publisher_id": seen_publisher,
        "source_schema_declared": "GLBX.MDP3:mbp-1",
        "input_price_mode": "pretty_px=True points",
        "independent_vendor_authentication": False,
        "independent_license_verification": False,
        "resting_queue_reconstructed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result, metadata = convert(args.input.read_bytes(), args.contract)
        with args.output.open("xb") as destination:
            destination.write(result)
        with args.report.open("x") as destination:
            json.dump(metadata, destination, indent=2, sort_keys=True)
            destination.write("\n")
    except (ValueError, OSError, TypeError, UnicodeError, csv.Error) as exc:
        parser.exit(2, "MBP-1 normalization rejected: " + str(exc) + "\n")
    print(json.dumps({"output_sha256": metadata["output_sha256"],
                      "records": metadata["records"],
                      "independent_vendor_authentication": False}))


if __name__ == "__main__":
    main()
