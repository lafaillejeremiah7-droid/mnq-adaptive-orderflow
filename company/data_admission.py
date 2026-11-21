"""Offline fail-closed validation of declared NQ/MNQ trade datasets.

This checks an immutable CSV and declared NY-session inventory. It does NOT
independently authenticate CME feed records, official calendars or licenses.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from company.market_profile import BILLION, CONTRACT, read_trades, time_hhmm

NY = ZoneInfo("America/New_York")
FIELDS = frozenset({
    "version", "dataset_id", "provider", "venue", "schema", "contract",
    "data_sha256", "source_kind", "rights_status", "rights_reference",
    "session_start", "session_end", "session_dates",
    "opening_tolerance_seconds", "closing_tolerance_seconds",
    "max_intertrade_gap_seconds", "max_trades",
})


def _integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"invalid {name}")
    return value


def _date(value):
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError("session dates must use canonical YYYY-MM-DD")
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid calendar date") from exc
    if not 2000 <= result.year <= 2099 or result.weekday() >= 5:
        raise ValueError("expected session dates must be supported weekdays")
    return result


def check_manifest(m):
    if not isinstance(m, dict) or set(m) != FIELDS:
        raise ValueError("admission manifest missing or unexpected fields")
    if type(m["version"]) is not int or m["version"] != 1:
        raise ValueError("unsupported manifest version")
    if not isinstance(m["dataset_id"], str) or re.fullmatch(
        r"[a-z0-9][a-z0-9_-]{0,79}", m["dataset_id"]
    ) is None:
        raise ValueError("invalid dataset_id")
    if not isinstance(m["provider"], str) or not m["provider"].strip() or len(m["provider"]) > 160:
        raise ValueError("source provider must be documented")
    if m["schema"] != "canonical_trades_v1":
        raise ValueError("OHLCV cannot be passed off as canonical executed trades")
    if not isinstance(m["contract"], str) or CONTRACT.fullmatch(m["contract"]) is None:
        raise ValueError("one quarterly NQ/MNQ contract is required")
    if m["source_kind"] not in ("historical", "synthetic"):
        raise ValueError("invalid source_kind")
    if m["venue"] not in ("CME_GLOBEX", "SIMULATED"):
        raise ValueError("invalid venue")
    if (m["source_kind"] == "historical") != (m["venue"] == "CME_GLOBEX"):
        raise ValueError("historical evidence must declare CME_GLOBEX venue")
    if m["rights_status"] not in ("documented", "unverified"):
        raise ValueError("invalid rights_status")
    if not isinstance(m["rights_reference"], str) or len(m["rights_reference"]) > 1000:
        raise ValueError("invalid rights_reference")
    if m["rights_status"] == "documented" and not m["rights_reference"].strip():
        raise ValueError("documented rights require a reference")
    if not isinstance(m["data_sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", m["data_sha256"]) is None:
        raise ValueError("invalid SHA-256")
    start, end = time_hhmm(m["session_start"]), time_hhmm(m["session_end"])
    if end <= start or end - start > 720:
        raise ValueError("session must be same-day and <=12 hours")
    dates = m["session_dates"]
    if not isinstance(dates, list) or not 1 <= len(dates) <= 1500:
        raise ValueError("expected session list must contain 1-1500 dates")
    parsed = [_date(d) for d in dates]
    if parsed != sorted(set(parsed)):
        raise ValueError("expected session dates must be sorted and unique")
    _integer(m["opening_tolerance_seconds"], "opening_tolerance_seconds", 0, 3600)
    _integer(m["closing_tolerance_seconds"], "closing_tolerance_seconds", 0, 3600)
    _integer(m["max_intertrade_gap_seconds"], "max_intertrade_gap_seconds", 1, 7200)
    _integer(m["max_trades"], "max_trades", 1, 5_000_000)
    return parsed, start, end


def _boundary_ns(day, minute):
    local = datetime.combine(day, time(minute // 60, minute % 60), tzinfo=NY)
    return int(local.astimezone(timezone.utc).timestamp()) * BILLION


def admit_trades(manifest, raw):
    """Reconcile declared sessions, bounded print gaps and checksum.

    A successful report is a quality screen, not independent proof that the
    declaration, data rights, CME venue, or exchange calendar are accurate.
    """
    expected, start, end = check_manifest(manifest)
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != manifest["data_sha256"]:
        raise ValueError("input does not match declared SHA-256")
    trades = read_trades(raw, manifest["contract"], manifest["max_trades"])
    sessions = defaultdict(list)
    outside_window = 0
    for trade in trades:
        # Integral seconds suffice for selecting the enclosing NY minute;
        # preserve nanosecond event precision in all boundary and gap checks.
        local = datetime.fromtimestamp(trade.timestamp_ns // BILLION, timezone.utc).astimezone(NY)
        minute = 60 * local.hour + local.minute
        if local.weekday() < 5 and start <= minute < end:
            sessions[local.date()].append(trade)
        else:
            outside_window += 1
    missing, extra = set(expected) - set(sessions), set(sessions) - set(expected)
    if missing or extra:
        raise ValueError(
            "declared sessions differ: missing=" + str([str(d) for d in sorted(missing)]) +
            ", unexpected=" + str([str(d) for d in sorted(extra)])
        )
    details = []
    for day in expected:
        records = sessions[day]
        start_ns, end_ns = _boundary_ns(day, start), _boundary_ns(day, end)
        first_delay = records[0].timestamp_ns - start_ns
        last_delay = end_ns - records[-1].timestamp_ns
        if first_delay < 0 or first_delay > manifest["opening_tolerance_seconds"] * BILLION:
            raise ValueError(f"{day}: first print too far from open")
        if last_delay <= 0 or last_delay > manifest["closing_tolerance_seconds"] * BILLION:
            raise ValueError(f"{day}: last print too far from close")
        biggest_gap = max(
            (right.timestamp_ns - left.timestamp_ns
             for left, right in zip(records, records[1:])), default=0
        )
        if biggest_gap > manifest["max_intertrade_gap_seconds"] * BILLION:
            raise ValueError(f"{day}: excessive intertrade gap")
        details.append({
            "date": str(day),
            "trades": len(records),
            "volume_contracts": sum(t.size for t in records),
            "unknown_aggressor_contracts": sum(t.size for t in records if t.side == "N"),
            "first_event_ns": records[0].timestamp_ns,
            "last_event_ns": records[-1].timestamp_ns,
            "open_delay_seconds": first_delay / BILLION,
            "close_delay_seconds": last_delay / BILLION,
            "largest_intertrade_gap_seconds": biggest_gap / BILLION,
        })
    return {
        "status": "declared_session_inventory_reconciled",
        "dataset_id": manifest["dataset_id"],
        "source_kind": manifest["source_kind"],
        "provider_declared": manifest["provider"],
        "venue_declared": manifest["venue"],
        "rights_status_declared": manifest["rights_status"],
        "rights_reference_declared": manifest["rights_reference"],
        "schema": manifest["schema"],
        "contract": manifest["contract"],
        "session_start": manifest["session_start"],
        "session_end": manifest["session_end"],
        "data_sha256": manifest["data_sha256"],
        "trade_records": len(trades),
        "outside_window_records": outside_window,
        "sessions": details,
        "independent_exchange_authentication": False,
        "independent_license_verification": False,
        "independent_exchange_calendar_verification": False,
        "independent_quote_book_reconciliation": False,
        "tradable_edge_validated": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--trades", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest_raw = args.manifest.read_bytes()
        result = admit_trades(json.loads(manifest_raw), args.trades.read_bytes())
        result["manifest_sha256"] = hashlib.sha256(manifest_raw).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as destination:
            json.dump(result, destination, sort_keys=True, indent=2)
            destination.write("\n")
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(2, "data admission rejected: " + str(exc) + "\n")
    print(json.dumps({"status": result["status"], "sessions": len(result["sessions"])}))


if __name__ == "__main__":
    main()
