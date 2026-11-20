"""Research-only Monte Carlo risk simulator for hypothetical NQ/MNQ trade outcomes.

Resamples *whole observed trading days* to preserve within-day clustering and
sequence, simulates static/EOD-trailing drawdown and target-first outcomes,
and produces Wilson confidence intervals. Does not identify a profitable edge,
recommend position sizes, or place orders. Prop firm rules vary: the supplied
rules must be separately verified against the exact challenge contract.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
import re
import statistics
from collections import defaultdict
from pathlib import Path

TICKS = {"NQ": 5.0, "MNQ": 0.5}
COLUMNS = ("session_date", "trade_number", "contract", "pnl_ticks")
PARAMS = frozenset((
    "id", "source_sha256", "source_kind", "source_rights",
    "contract", "starting_balance_usd", "profit_target_usd",
    "maximum_drawdown_usd", "drawdown_mode", "eod_floor_cap_at_start",
    "daily_stop_usd", "round_trip_fees_per_contract_usd", "contracts",
    "max_trades_per_day", "horizon_days", "simulations", "seed",
    "sample_already_examined",
))


def validate_params(p):
    if not isinstance(p, dict) or set(p) != PARAMS:
        raise ValueError("missing or extra risk protocol fields")
    if not isinstance(p["id"], str) or not re.fullmatch("[a-z0-9][a-z0-9_-]{0,69}", p["id"]):
        raise ValueError("invalid research run id")
    if not isinstance(p["source_sha256"], str) or not re.fullmatch("[a-f0-9]{64}", p["source_sha256"]):
        raise ValueError("invalid source checksum")
    if p["contract"] not in TICKS:
        raise ValueError("contract must be explicitly NQ or MNQ; do not conflate tick values")
    if p["source_kind"] not in ("synthetic", "historical") or p["source_rights"] not in ("unverified", "verified_documentation"):
        raise ValueError("source provenance status is required")
    if p["drawdown_mode"] not in ("static", "eod_trailing"):
        raise ValueError("invalid drawdown policy")
    for key in ("eod_floor_cap_at_start", "sample_already_examined"):
        if type(p[key]) is not bool:
            raise ValueError("invalid boolean policy: " + key)
    for key, lo, hi in (
        ("starting_balance_usd", 100, 1e9),
        ("profit_target_usd", 1, 1e8),
        ("maximum_drawdown_usd", 1, 1e8),
        ("daily_stop_usd", 0, 1e7),
        ("round_trip_fees_per_contract_usd", 0, 1e4),
    ):
        value = p[key]
        if type(value) not in (float, int) or not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError("invalid positive monetary parameter: " + key)
    if p["maximum_drawdown_usd"] >= p["starting_balance_usd"]:
        raise ValueError("maximum drawdown must be less than starting balance")
    for key, lo, hi in (
        ("contracts", 1, 50), ("max_trades_per_day", 1, 20),
        ("horizon_days", 1, 365), ("simulations", 100, 50000),
        ("seed", 0, 2**32-1),
    ):
        if type(p[key]) is not int or not lo <= p[key] <= hi:
            raise ValueError("invalid integer parameter " + key)


def parse_history(source, p):
    validate_params(p)
    if hashlib.sha256(source).hexdigest() != p["source_sha256"]:
        raise ValueError("trade outcome source checksum mismatch")
    rows = csv.DictReader(io.StringIO(source.decode("utf-8-sig"), newline=""))
    if rows.fieldnames != list(COLUMNS):
        raise ValueError("trade outcome CSV schema mismatch")
    days = defaultdict(list)
    prev = None
    for row in rows:
        if set(row) != set(COLUMNS) or any(v is None for v in row.values()):
            raise ValueError("malformed historical trade row")
        date = row["session_date"]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError("invalid date")
        from datetime import date as Date
        try:
            d = Date.fromisoformat(date)
        except ValueError as error:
            raise ValueError("invalid calendar date") from error
        if d.weekday() >= 5:
            raise ValueError("weekend dates require exchange-calendar review")
        if row["contract"] != p["contract"]:
            raise ValueError("mixed instruments or unexpected contract")
        try:
            trade = int(row["trade_number"])
            ticks = int(row["pnl_ticks"])
        except ValueError as error:
            raise ValueError("trade index and outcome must be integers") from error
        if str(trade) != row["trade_number"] or str(ticks) != row["pnl_ticks"]:
            raise ValueError("noncanonical trade index or tick outcome")
        if trade < 1 or abs(ticks) > 50000:
            raise ValueError("invalid trade sequence or PnL")
        key = (date, trade)
        if prev is not None and key <= prev:
            raise ValueError("source must be strictly sorted by date and trade number")
        prev = key
        if trade != len(days[date]) + 1:
            raise ValueError("day must have contiguous trade numbers starting at one")
        days[date].append(ticks)
        if len(days[date]) > p["max_trades_per_day"]:
            raise ValueError("source contains more daily trades than registered rule")
    if len(days) < 10:
        raise ValueError("fewer than ten distinct trading dates; no credible path bootstrap")
    return [list(x) for _, x in sorted(days.items())], dict(sorted((d, len(v)) for d,v in days.items()))


def wilson(successes, total, z=1.959963984540054):
    if not 0 <= successes <= total or total <= 0:
        raise ValueError("invalid Wilson counts")
    p = successes / total
    denominator = 1 + z*z/total
    center = (p + z*z/(2*total))/denominator
    spread = z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/denominator
    return [max(0, center-spread), min(1, center+spread)]


def one_path(day_outcomes, p, rng):
    starting = p["starting_balance_usd"]
    target = starting + p["profit_target_usd"]
    equity = starting
    high_eod = starting
    floor = starting - p["maximum_drawdown_usd"]
    worst_dip = 0.0
    for day_no in range(1, p["horizon_days"]+1):
        outcomes = rng.choice(day_outcomes)
        day_start = equity
        for gross_ticks in outcomes:
            trade_net = gross_ticks*TICKS[p["contract"]]*p["contracts"] - p["round_trip_fees_per_contract_usd"]*p["contracts"]
            equity += trade_net
            worst_dip = max(worst_dip, high_eod-equity)
            # Trade-level drawdown checks even when the trailing high watermark
            # is updated only after completed session.
            if equity <= floor:
                return {"outcome":"failed_drawdown","day":day_no,"final_equity":equity,"worst_dip":worst_dip}
            if p["daily_stop_usd"] and day_start-equity >= p["daily_stop_usd"]:
                break
        if p["drawdown_mode"] == "eod_trailing":
            high_eod = max(high_eod, equity)
            candidate = high_eod - p["maximum_drawdown_usd"]
            floor = min(starting, candidate) if p["eod_floor_cap_at_start"] else candidate
        if equity >= target:
            return {"outcome":"passed_target","day":day_no,"final_equity":equity,"worst_dip":worst_dip}
    return {"outcome":"unfinished","day":p["horizon_days"],"final_equity":equity,"worst_dip":worst_dip}


def simulate(history, p):
    validate_params(p)
    rng = random.Random(p["seed"])
    results = [one_path(history, p, rng) for _ in range(p["simulations"])]
    counts = {name: sum(r["outcome"] == name for r in results)
              for name in ("passed_target", "failed_drawdown", "unfinished")}
    if sum(counts.values()) != p["simulations"]:
        raise ValueError("inconsistent path classifications")
    wins = counts["passed_target"]
    losses = counts["failed_drawdown"]
    # Report unresolved mass separately; never classify it as a win.
    return {
        "study": "hypothetical trade-outcome block bootstrap under declared drawdown policy",
        "contract": p["contract"],
        "tick_value_usd": TICKS[p["contract"]],
        "sample_days": len(history),
        "simulations": p["simulations"],
        "policy": {k:p[k] for k in (
            "starting_balance_usd","profit_target_usd","maximum_drawdown_usd",
            "drawdown_mode","eod_floor_cap_at_start","daily_stop_usd",
            "round_trip_fees_per_contract_usd","contracts","horizon_days")},
        "outcomes": counts,
        "target_hit_fraction": wins/p["simulations"],
        "target_hit_wilson95": wilson(wins, p["simulations"]),
        "drawdown_failure_fraction": losses/p["simulations"],
        "drawdown_failure_wilson95": wilson(losses, p["simulations"]),
        "unfinished_fraction": counts["unfinished"]/p["simulations"],
        "median_days_to_target_conditional": (
            statistics.median(r["day"] for r in results if r["outcome"] == "passed_target") if wins else None
        ),
        "median_worst_intraday_dip_from_prior_eod_peak_usd": statistics.median(r["worst_dip"] for r in results),
        "independent_market_data_evidence": False,
        "profitability_proven": False,
        "is_optimal_contract_sizing": False,
        "limits": [
            "Resamples the provided trade-outcome distribution; future stationarity is not established.",
            "Whole-day sampling preserves only within-day clusters, not longer losing regimes.",
            "Drawdown and profit evaluation are implemented as specified, but prop-firm rulebooks differ.",
            "End-of-day trailing high watermark changes only at day end; breaches checked after each recorded trade.",
            "A daily stop blocks later trades on that day, assuming all stopped trades are skipped.",
            "No intratrade adverse excursions, spread/impact/market capacity or missed orders are modeled.",
            "Outcomes are assumed to scale linearly with contracts, often invalid in reality.",
            "This is not a trade recommendation or a proof of payout probability.",
        ],
    }


def research(p, source):
    days, coverage = parse_history(source, p)
    result = simulate(days, p)
    result.update({
        "protocol_id": p["id"], "data_sha256": hashlib.sha256(source).hexdigest(),
        "source_kind": p["source_kind"], "source_rights": p["source_rights"],
        "historical_sample_previously_seen": p["sample_already_examined"],
        "source_calendar_trade_counts": coverage,
    })
    return result


def run(protocol_file, data_file, out_root):
    frozen = Path(protocol_file).read_bytes()
    p = json.loads(frozen)
    raw = Path(data_file).read_bytes()
    result = research(p, raw)
    result["protocol_sha256"] = hashlib.sha256(frozen).hexdigest()
    result["engine_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    folder = Path(out_root)/p["id"]
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.mkdir(exist_ok=False)
    (folder/"protocol.json").write_bytes(frozen)
    (folder/"result.json").write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False)+"\n")
    (folder/"research_note.md").write_text(
        "# NQ/MNQ path-dependent risk research\n\n"
        "Research only; no independently verified market-trading success.\n\n"
        "Source SHA-256: "+result["data_sha256"]+"\n\n"
        "Estimated target-first frequency: "+str(result["target_hit_fraction"])+"\n\n"
        "Estimated drawdown-failure frequency: "+str(result["drawdown_failure_fraction"])+"\n\n"
        "Unresolved: "+str(result["unfinished_fraction"])+"\n\n"
        "Hypothetical regime assumptions and account rules must be independently checked.\n"
    )
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--trades", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("research-runs/risk"))
    args = parser.parse_args()
    try:
        output = run(args.protocol, args.trades, args.out)
    except (ValueError, OSError, KeyError, TypeError, UnicodeError, csv.Error) as e:
        parser.exit(2, "risk experiment rejected: " + str(e) + "\n")
    print(json.dumps({"saved": str(output), "production_ready": False}))


if __name__ == "__main__":
    main()
