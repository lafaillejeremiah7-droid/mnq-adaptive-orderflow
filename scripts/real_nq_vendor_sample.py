"""Exploratory ONE-DAY NQZ6 study of vendor-supplied historical trades.

Downloads a SHA-pinned sample privately on the runner, studies its REAL
vendor-reported trade records and publishes aggregate research only.
No exchange authenticity certification, trading, or alpha claim.
"""
import argparse
import hashlib
import io
import json
import math
import statistics
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from company.market_profile import Trade, first_touch, profile_levels, summarize, volume_profile

URL = "https://historicalfuturesdata.com/samples/pack/es-nq-tick-sample-2026-11-09.zip"
ARCHIVE_SHA = "0393ec579d453d016b5a838392349a0e6f21f3ddd211f3e7c24bb5c8cb63fc72"
TICK_SHA = "89a50dc88c4beacafd95b8cc4e2f7ee9000af498549dcb0910aa08feed82dba0"
TICK_FILE = "NQZ6_2026-11-09_ticks.parquet"
NANO = 1000000000
OPEN = int(datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc).timestamp()) * NANO
CLOSE = int(datetime(2026, 11, 9, 21, 0, tzinfo=timezone.utc).timestamp()) * NANO
HALFHOUR = 1800 * NANO


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_vendor_file():
    with urllib.request.urlopen(URL, timeout=120) as response:
        archive = response.read(20000001)
    if len(archive) > 20000000 or sha(archive) != ARCHIVE_SHA:
        raise ValueError("vendor archive hash mismatch")
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        names = [name for name in z.namelist() if Path(name).name == TICK_FILE]
        if len(names) != 1 or z.getinfo(names[0]).file_size > 8000000:
            raise ValueError("unexpected file name or size in vendor archive")
        raw = z.read(names[0])
    if sha(raw) != TICK_SHA:
        raise ValueError("NQZ6 parquet hash mismatch")
    return raw


def parse(raw):
    table = pq.read_table(io.BytesIO(raw))
    fields = {"ts", "symbol", "price", "volume", "trade_count", "bid_sz", "ask_sz"}
    if not fields.issubset(table.column_names) or len(table) != 710815:
        raise ValueError("published NQZ6 tick schema or record count mismatch")
    timestamps = table.column("ts").cast(pa.int64()).to_pylist()
    prices = table.column("price").to_pylist()
    volumes = table.column("volume").to_pylist()
    symbols = table.column("symbol").to_pylist()
    counts = table.column("trade_count").to_pylist()
    bids = table.column("bid_sz").to_pylist()
    asks = table.column("ask_sz").to_pylist()
    trades, total, last = [], 0, None
    for i, (stamp, price, size, symbol, count, bid, ask) in enumerate(
            zip(timestamps, prices, volumes, symbols, counts, bids, asks)):
        if not isinstance(stamp, int) or last is not None and stamp < last:
            raise ValueError("unsorted vendor ticks")
        last = stamp
        if symbol != "NQZ6" or not isinstance(size, int) or size <= 0:
            raise ValueError("vendor tick contract or size mismatch")
        if not isinstance(count, int) or count <= 0:
            raise ValueError("invalid trade count")
        if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            raise ValueError("invalid price")
        tick = round(price * 4)
        if abs(tick / 4 - price) > 1e-8:
            raise ValueError("invalid quarter-point price tick")
        if not isinstance(bid, int) or not isinstance(ask, int) or min(bid, ask) < 0:
            raise ValueError("invalid vendor executed side volumes")
        total += size
        if OPEN <= stamp < CLOSE:
            # Side classification deliberately unknown. Bid/ask SZ are not verified MBO.
            trades.append(Trade(stamp, "NQZ6", tick, size, "N", i))
    if total != 766017:
        raise ValueError("provider total-volume reconciliation failed")
    if not trades:
        raise ValueError("no regular-hours observations")
    return trades, {
        "full_utc_tick_records": len(table), "full_utc_contracts": total,
        "rth_tick_records": len(trades), "rth_contracts": sum(t.size for t in trades),
        "rth_first_ns": trades[0].timestamp_ns, "rth_last_ns": trades[-1].timestamp_ns,
    }


def compressed(p):
    return {
        "trades": p["trade_count"], "contracts": p["total_contracts_traded"],
        "poc": p["poc_ticks"] / 4, "vah": p["vah_ticks"] / 4,
        "val": p["val_ticks"] / 4, "vwap": p["vwap_points"],
        "hvn": [v / 4 for v in p["hvn_ticks"]],
        "lvn": [v / 4 for v in p["lvn_ticks"]],
        "value_area_coverage": p["value_area_volume_fraction_actual"],
    }


def reactions(p, future):
    observations = []
    for name, level in profile_levels(p):
        record = first_touch(future, level, tolerance=1, threshold=8, horizon_ns=300 * NANO)
        if record:
            observations.append({"kind": name, "session_date": "2026-11-09",
                                 "price_level": level / 4, **record})
    return observations


def study(trades, coverage):
    blocks = [[] for _ in range(13)]
    for t in trades:
        index = (t.timestamp_ns - OPEN) // HALFHOUR
        if not 0 <= index < 13:
            raise ValueError("trades out of session")
        blocks[index].append(t)
    if any(not b for b in blocks):
        raise ValueError("missing RTH half-hour block")
    opening = volume_profile(blocks[0], .70)
    rest = [t for b in blocks[1:] for t in b]
    if blocks[0][-1].timestamp_ns >= rest[0].timestamp_ns:
        raise ValueError("lookahead between opening profile and evaluation")
    opening_touch = reactions(opening, rest)
    rolling = []
    checkpoints = []
    for i in range(12):
        earlier, later = blocks[i], blocks[i + 1]
        if earlier[-1].timestamp_ns >= later[0].timestamp_ns:
            raise ValueError("profile contains future observations")
        p = volume_profile(earlier, .70)
        events = reactions(p, later)
        for e in events:
            e["profile_window"] = i
        rolling.extend(events)
        checkpoints.append({"profile_window": i, "profile_records": len(earlier),
                            "test_records": len(later), "levels": compressed(p),
                            "touch_events": len(events)})
    return {
        "study": "Vendor-supplied historical NQZ6 tick sample, 2026-11-09",
        "source": URL,
        "manifest": "https://historicalfuturesdata.com/samples/pack/manifest.json",
        "archive_sha256": ARCHIVE_SHA, "parquet_sha256": TICK_SHA,
        "contract": "NQZ6", "date": "2026-11-09",
        "source_authenticity": "Source/vendor counts and checksums verified; CME origin not independently verified",
        "time_window": "09:30-16:00 America/New_York",
        "profile_freeze": "09:30-10:00 ET; later reaction measured after 10:00 ET",
        "reaction_rule": "first printed touch within 1 tick, first 8-tick cross/rejection within 300 seconds",
        "coverage": coverage, "opening": compressed(opening),
        "opening_reactions": opening_touch,
        "opening_reaction_summary": summarize(opening_touch),
        "rolling_30m_results": checkpoints,
        "rolling_reaction_summary": summarize(rolling),
        "rolling_reaction_count": len(rolling),
        "independent_dates": 1, "statistical_significance": "Not estimable from one day",
        "alpha_validated": False, "execution_studied": False,
        "limits": [
            "One day only; 12 rolling windows are strongly dependent.",
            "The source vendor asserts CME origin; exchange authenticity is not independently verified.",
            "Vendor terms restrict raw-sample redistribution and commercial use.",
            "No quotes/MBO, queue, spreads or realistic transaction-cost simulation.",
            "Unknown aggressor direction: no trusted absorption conclusions.",
            "A touch from printed trades is not evidence that a limit order filled.",
            "No prospective holdout or significance estimate."
        ],
    }


def report(data):
    p = data["opening"]
    lines = [
        "# Historical NQZ6 volume profile and price reactions", "",
        "**This is an actual downloaded, checksum-verified vendor tick sample, not synthetic unit-test data.**",
        "Its CME provenance and completeness have not been verified independently.", "",
        "Date: 2026-11-09; contract: NQZ6; one trading day.", "",
        "Full UTC window: {:,} trade records and {:,} contracts.".format(
            data["coverage"]["full_utc_tick_records"], data["coverage"]["full_utc_contracts"]),
        "RTH 09:30-16:00 ET: {:,} trade records and {:,} contracts.".format(
            data["coverage"]["rth_tick_records"], data["coverage"]["rth_contracts"]),
        "Opening 09:30-10:00 ET frozen POC {:.2f}, VAH {:.2f}, VAL {:.2f}.".format(
            p["poc"], p["vah"], p["val"]),
        "Opening profile: {:,} contracts, VWAP {:.3f}.".format(p["contracts"], p["vwap"]),
        "HVNs: " + str(p["hvn"]), "LVNs: " + str(p["lvn"]), "",
        "## Price reaction after levels were frozen", "",
        "One level touch when price prints within 1 tick after previously being outside; "
        "the first 8-tick excursion within 300 seconds determines rejection/cross.",
        "",
        "| Level | Touches | Rejections | Crosses | Unresolved | Censored |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for kind, stats in sorted(data["opening_reaction_summary"].items()):
        fields = ("events", "rejection_first", "cross_first", "unresolved", "censored")
        lines.append("| " + kind + " | " + " | ".join(str(stats[x]) for x in fields) + " |")
    lines += ["", "## Earlier half-hour profile tested in following half-hour", "",
              "All 12 comparisons share the same date: not 12 independent trading days.",
              "",
              "| Level | Touches | Rejections | Crosses | Unresolved | Censored |",
              "|---|---:|---:|---:|---:|---:|"]
    for kind, stats in sorted(data["rolling_reaction_summary"].items()):
        fields = ("events", "rejection_first", "cross_first", "unresolved", "censored")
        lines.append("| " + kind + " | " + " | ".join(str(stats[x]) for x in fields) + " |")
    lines += ["", "## Research limitations", "",
              *["- " + x for x in data["limits"]], "",
              "No evidence of a profitable strategy or predictive edge is established.", "",
              "Source: " + data["source"],
              "Manifest: " + data["manifest"],
              "Archive SHA256: " + data["archive_sha256"],
              "Tick Parquet SHA256: " + data["parquet_sha256"], ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("studies/real-nq-20261109-sample"))
    args = parser.parse_args()
    raw = load_vendor_file()
    records, coverage = parse(raw)
    result = study(records, coverage)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    (output / "report.md").write_text(report(result))
    print(json.dumps({"status": "completed", "RTH": coverage["rth_tick_records"],
                      "POC": result["opening"]["poc"], "VAH": result["opening"]["vah"],
                      "VAL": result["opening"]["val"], "output": str(output)}))


if __name__ == "__main__":
    main()
