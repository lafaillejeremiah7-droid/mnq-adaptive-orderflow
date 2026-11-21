"""Multi-contract, multi-year offline CME futures data inventory reconciliation.

Checks local files, one-contract trade partitions, registered session dates and
declared rollover assignments. Authenticates neither vendors nor licenses nor
the user-supplied calendar. It never downloads market data.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from datetime import date
from pathlib import Path

from company.data_admission import admit_trades

KEYS = frozenset({
    "version", "dataset_id", "dataset", "contract_root", "source_kind",
    "rights_status", "rights_reference", "calendar_file",
    "calendar_sha256", "partitions",
})
PART_KEYS = frozenset({"file", "manifest"})
DATES = ("session_date", "contract")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _file(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("expected relative dataset file path")
    base = root.resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError("dataset file missing or escapes configured root")
    return path


def _root(contract):
    if not isinstance(contract, str):
        raise ValueError("contract must be a string")
    if contract.startswith("MNQ"):
        return "MNQ"
    if contract.startswith("NQ"):
        return "NQ"
    raise ValueError("unknown NQ/MNQ contract root")


def _calendar(raw, root):
    try:
        csvfile = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    except UnicodeError as exc:
        raise ValueError("calendar file must be UTF-8") from exc
    if csvfile.fieldnames != list(DATES):
        raise ValueError("expected calendar header session_date,contract")
    expected = {}
    prior = ""
    for row in csvfile:
        if set(row) != set(DATES) or any(v is None for v in row.values()):
            raise ValueError("malformed calendar row")
        key = row["session_date"]
        try:
            day = date.fromisoformat(key)
        except ValueError as exc:
            raise ValueError("malformed ISO session date") from exc
        if day.isoformat() != key or day.weekday() >= 5:
            raise ValueError("calendar expects canonical weekday sessions")
        if key <= prior:
            raise ValueError("calendar must be sorted with unique dates")
        prior = key
        if _root(row["contract"]) != root or re.fullmatch(
            rf"{root}[HMUZ][0-9]{{1,4}}", row["contract"]
        ) is None:
            raise ValueError("calendar contract does not match requested NQ/MNQ root")
        expected[key] = row["contract"]
    if not expected:
        raise ValueError("empty expected calendar")
    return expected


def check_registry(registry, root_path):
    if not isinstance(registry, dict) or set(registry) != KEYS:
        raise ValueError("invalid dataset registry fields")
    if type(registry["version"]) is not int or registry["version"] != 1:
        raise ValueError("unsupported registry version")
    if not isinstance(registry["dataset_id"], str) or re.fullmatch(
        r"[a-z0-9][a-z0-9_-]{0,79}", registry["dataset_id"]
    ) is None:
        raise ValueError("invalid dataset id")
    if registry["dataset"] != "GLBX.MDP3":
        raise ValueError("unsupported dataset identity; do not relabel other instruments")
    root = registry["contract_root"]
    if root not in ("NQ", "MNQ"):
        raise ValueError("contract_root must be NQ or MNQ")
    if registry["source_kind"] not in ("synthetic", "historical"):
        raise ValueError("invalid source kind")
    if registry["rights_status"] not in ("unverified", "documented"):
        raise ValueError("invalid declared license status")
    if not isinstance(registry["rights_reference"], str):
        raise ValueError("invalid rights reference")
    if registry["rights_status"] == "documented" and not registry["rights_reference"].strip():
        raise ValueError("documented rights need a source reference")
    if not isinstance(registry["calendar_sha256"], str) or re.fullmatch(
        r"[a-f0-9]{64}", registry["calendar_sha256"]
    ) is None:
        raise ValueError("invalid calendar hash")
    expected_bytes = _file(Path(root_path), registry["calendar_file"]).read_bytes()
    if _sha(expected_bytes) != registry["calendar_sha256"]:
        raise ValueError("expected calendar SHA-256 mismatch")
    expected = _calendar(expected_bytes, root)
    partitions = registry["partitions"]
    if not isinstance(partitions, list) or not 1 <= len(partitions) <= 1500:
        raise ValueError("expected 1-1500 declared partitions")
    observed = {}
    seen_files = set()
    validated = []
    for item in partitions:
        if not isinstance(item, dict) or set(item) != PART_KEYS:
            raise ValueError("invalid partition descriptor")
        trade_path = _file(Path(root_path), item["file"])
        manifest_path = _file(Path(root_path), item["manifest"])
        if trade_path in seen_files or manifest_path in seen_files:
            raise ValueError("duplicate partition or manifest")
        seen_files.update((trade_path, manifest_path))
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        if (manifest.get("source_kind") != registry["source_kind"]
                or manifest.get("rights_status") != registry["rights_status"]
                or _root(manifest.get("contract")) != root):
            raise ValueError("partition source/contract/rights mismatch")
        admission = admit_trades(manifest, trade_path.read_bytes())
        for session in admission["sessions"]:
            day = session["date"]
            if day in observed:
                raise ValueError("duplicate session across partitions: " + day)
            if expected.get(day) != admission["contract"]:
                raise ValueError("unexpected date or wrong rollover contract: " + day)
            observed[day] = admission["contract"]
        validated.append({
            "file": item["file"],
            "manifest": item["manifest"],
            "manifest_sha256": _sha(manifest_bytes),
            "data_sha256": admission["data_sha256"],
            "contract": admission["contract"],
            "sessions": len(admission["sessions"]),
            "trade_records": admission["trade_records"],
            "outside_window_records": admission["outside_window_records"],
        })
    if observed != expected:
        missing = sorted(set(expected) - set(observed))
        raise ValueError("dataset calendar missing declared sessions: " + str(missing[:25]))
    return {
        "status": "declared_multi_contract_inventory_reconciled",
        "dataset_id": registry["dataset_id"],
        "dataset_declared": registry["dataset"],
        "source_kind_declared": registry["source_kind"],
        "rights_status_declared": registry["rights_status"],
        "expected_calendar_sha256": registry["calendar_sha256"],
        "contract_root": root,
        "expected_sessions": len(expected),
        "observed_sessions": len(observed),
        "partitions_checked": validated,
        "partition_count": len(validated),
        "total_trade_records": sum(p["trade_records"] for p in validated),
        "independent_exchange_data_authentication": False,
        "independent_vendor_entitlement_verified": False,
        "independent_exchange_calendar_verified": False,
        "independent_contract_roll_verified": False,
        "independent_quote_book_integrity_verified": False,
        "production_ready": False,
        "limits": [
            "Calendar and rollover assignments are user-declared and may omit trading dates.",
            "Source identity, distribution licenses and venue are not independently authenticated.",
            "Trade partitions do not contain quote or market-by-order depth data.",
            "Partition checks are bounded and do not prove multi-year exchange completeness.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        frozen = args.registry.read_bytes()
        report = check_registry(json.loads(frozen), args.root)
        report["registry_sha256"] = _sha(frozen)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as destination:
            json.dump(report, destination, indent=2, sort_keys=True)
            destination.write("\n")
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, csv.Error) as exc:
        parser.exit(2, "dataset inventory rejected: " + str(exc) + "\n")
    print(json.dumps({"status": report["status"], "sessions": report["observed_sessions"],
                      "independent_exchange_data_authentication": False}))


if __name__ == "__main__":
    main()
