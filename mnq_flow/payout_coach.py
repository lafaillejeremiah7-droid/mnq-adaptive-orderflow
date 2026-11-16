"""Local MNQ payout and risk assistant. Advisory only; never places orders."""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from datetime import datetime, date, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TICK = Decimal("0.25")
DOLLARS_PER_POINT = Decimal("2")

def number(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError("Invalid finite dollar number") from None
    if not result.is_finite():
        raise ValueError("Invalid finite dollar number")
    return result

def usd(value):
    return float(value.quantize(Decimal("0.01")))

def config_read(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    required = (
        "stage", "starting_balance", "risk_per_trade", "personal_daily_stop",
        "max_trades_per_day", "max_mnq_contracts", "max_consecutive_losses",
        "roundtrip_cost_per_contract", "slippage_ticks_per_contract",
        "drawdown_reserve_usd", "winning_days_required", "winning_day_minimum",
        "minimum_payout", "maximum_payout", "payout_fraction",
        "trader_share", "evaluation_target", "evaluation_consistency",
    )
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError("Missing account config: " + ", ".join(missing))
    if config["stage"] not in ("evaluation", "funded"):
        raise ValueError("Stage must be evaluation or funded")
    for key in required[1:]:
        if config[key] is None and key in ("evaluation_target", "evaluation_consistency"):
            continue
        if number(config[key]) < 0:
            raise ValueError(key + " cannot be negative")
    for key in ("max_trades_per_day", "max_mnq_contracts", "max_consecutive_losses", "winning_days_required"):
        if int(config[key]) < 1:
            raise ValueError(key + " must be positive")
    for key in ("payout_fraction", "trader_share"):
        if number(config[key]) > 1:
            raise ValueError(key + " cannot exceed 1")
    return config

def journal_read(path):
    file = Path(path)
    if not file.exists():
        return []
    rows = []
    for i, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        try:
            date.fromisoformat(item["date"])
            rows.append({"date": item["date"], "net_pnl": number(item["net_pnl"])})
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Journal line {i}: {exc}") from exc
    return rows

def summary(config, rows):
    days = defaultdict(lambda: Decimal(0))
    for row in rows:
        days[row["date"]] += row["net_pnl"]
    net = sum(days.values(), Decimal(0))
    result = {
        "stage": config["stage"], "recorded_trades": len(rows),
        "recorded_net_profit": usd(net),
        "daily_net": {d: usd(days[d]) for d in sorted(days)},
        "provisional": True,
        "warning": "Manual journal is not proof of broker P&L or prop-firm payout eligibility.",
    }
    if config["stage"] == "evaluation":
        target = config["evaluation_target"]
        fraction = config["evaluation_consistency"]
        largest = max(days.values(), default=Decimal(0))
        result.update({
            "evaluation_profit_target": None if target is None else usd(number(target)),
            "profit_remaining": None if target is None else usd(max(Decimal(0), number(target) - net)),
            "largest_day_share": None if net <= 0 else round(float(largest / net), 4),
            "consistency_met": (
                None if fraction is None or net <= 0
                else largest <= net * number(fraction)
            ),
            "eligible_for_payout": False,
            "next_step": "Pass evaluation and obtain a funded account.",
        })
    else:
        winners = sorted(d for d, pnl in days.items()
                         if pnl >= number(config["winning_day_minimum"]))
        max_request = min(
            number(config["maximum_payout"]),
            max(Decimal(0), net) * number(config["payout_fraction"]),
        )
        possible = (len(winners) >= int(config["winning_days_required"])
                    and max_request >= number(config["minimum_payout"]))
        result.update({
            "winning_days": winners,
            "winning_days_count": len(winners),
            "winning_days_remaining": max(0, int(config["winning_days_required"]) - len(winners)),
            "maximum_theoretical_payout_request": usd(max_request),
            "estimated_share_before_processing_fees": usd(max_request * number(config["trader_share"])),
            "eligible_for_payout": possible,
            "eligibility_note": "Requires official approval and confirmation of all account terms.",
        })
    return result

def last_signal(path, now):
    """Requires a fresh candidate in the last object of JSONL or a single JSON object."""
    if path is None:
        return "none"
    content = Path(path).read_text(encoding="utf-8").strip()
    if not content:
        return "none"
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        obj = json.loads(content.splitlines()[-1])
    if not isinstance(obj, dict) or obj.get("signal") not in ("long_candidate", "short_candidate"):
        return "none"
    observed = datetime.fromisoformat(obj["asof"])
    if observed.utcoffset() is None:
        return "none"
    age = (now - observed).total_seconds()
    if not 0 <= age <= 180:
        return "none"
    return obj["signal"]

def risk_check(config, rows, *, side, entry, stop, contracts, equity, floor,
               open_contracts, broker_day_net, broker_trades, broker_losses,
               at, setup):
    if at.utcoffset() is None:
        raise ValueError("At time must include UTC offset")
    now = at.astimezone(ET)
    reasons = []
    if now.weekday() not in (0, 1, 2, 3) or not time(10, 0) <= now.time() < time(15, 0):
        reasons.append("Outside personal Mon-Thu 10:00-15:00 ET trading window")
    if not 1 <= contracts <= int(config["max_mnq_contracts"]):
        reasons.append("Contract count exceeds configured limit")
    if open_contracts != 0:
        reasons.append("Open position exists")
    if broker_trades >= int(config["max_trades_per_day"]):
        reasons.append("Daily trade-count stop reached")
    if broker_losses >= int(config["max_consecutive_losses"]):
        reasons.append("Consecutive-loss stop reached")
    if broker_day_net <= -number(config["personal_daily_stop"]):
        reasons.append("Daily dollar stop reached")
    if equity <= floor:
        reasons.append("At or below broker drawdown floor")
    if entry % TICK != 0 or stop % TICK != 0:
        reasons.append("Prices must be 0.25-tick aligned")
    if (side == "long" and stop >= entry) or (side == "short" and stop <= entry):
        reasons.append("Stop is on wrong side of entry")
    expected = (abs(entry - stop) * DOLLARS_PER_POINT * contracts
                + number(config["roundtrip_cost_per_contract"]) * contracts
                + number(config["slippage_ticks_per_contract"]) * Decimal("0.50") * contracts)
    allowable = min(
        number(config["risk_per_trade"]),
        number(config["personal_daily_stop"]) + broker_day_net,
        equity - floor - number(config["drawdown_reserve_usd"]),
    )
    if expected > allowable:
        reasons.append("Planned loss plus cost/slippage buffer exceeds available risk budget")
    if setup != ("long_candidate" if side == "long" else "short_candidate"):
        reasons.append("No current matching 15m/5m/1m setup candidate")
    today = [item for item in rows if item["date"] == now.date().isoformat()]
    today_net = sum((item["net_pnl"] for item in today), Decimal(0))
    if len(today) != broker_trades or today_net != broker_day_net:
        reasons.append("Manual journal and broker day P&L/trade count disagree")
    if broker_losses > broker_trades or broker_losses < 0:
        reasons.append("Invalid consecutive-loss count")
    return {
        "decision": "BLOCK" if reasons else "REVIEW_ONLY",
        "reasons": reasons,
        "estimated_planned_risk_usd": usd(expected),
        "available_risk_budget_usd": usd(max(Decimal(0), allowable)),
        "broker_equity": usd(equity),
        "broker_drawdown_floor": usd(floor),
        "setup_candidate": setup,
        "warning": (
            "REVIEW_ONLY does not mean BUY or SELL. No edge verified. "
            "Actual stop fills may slip beyond this estimate; manually supplied "
            "account metrics and candidate data are not independently verified."
        ),
    }

def main():
    parser = argparse.ArgumentParser(description="Local MNQ payout risk coach; no orders.")
    parser.add_argument("--config", default="account.json")
    parser.add_argument("--journal", default="trades.jsonl")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("status")
    rec = subs.add_parser("record")
    rec.add_argument("--date", required=True, help="New York session YYYY-MM-DD")
    rec.add_argument("--net", required=True, help="Realized net trade P&L after fees")
    rec.add_argument("--setup", default="manual")
    check = subs.add_parser("check")
    check.add_argument("--side", choices=("long", "short"), required=True)
    check.add_argument("--entry", required=True)
    check.add_argument("--stop", required=True)
    check.add_argument("--contracts", type=int, required=True)
    check.add_argument("--equity", required=True, help="Live account equity, including unrealized P&L")
    check.add_argument("--floor", required=True, help="Live official drawdown floor")
    check.add_argument("--open-contracts", type=int, required=True)
    check.add_argument("--broker-day-net", required=True)
    check.add_argument("--broker-trades", type=int, required=True)
    check.add_argument("--broker-losses", type=int, required=True)
    check.add_argument("--snapshot", help="Live/recent JSON or JSONL signal snapshots")
    check.add_argument("--at", help="Offset-aware ISO time for reproducible checks")
    args = parser.parse_args()
    try:
        cfg = config_read(args.config)
        rows = journal_read(args.journal)
        if args.command == "status":
            result = summary(cfg, rows)
        elif args.command == "record":
            date.fromisoformat(args.date)
            item = {"date": args.date, "net_pnl": usd(number(args.net)), "setup": args.setup}
            with open(args.journal, "a", encoding="utf-8") as file:
                file.write(json.dumps(item) + "\n")
            result = {"recorded": item, "status": summary(cfg, journal_read(args.journal))}
        else:
            at = datetime.fromisoformat(args.at) if args.at else datetime.now(ET)
            result = risk_check(
                cfg, rows, side=args.side, entry=number(args.entry), stop=number(args.stop),
                contracts=args.contracts, equity=number(args.equity), floor=number(args.floor),
                open_contracts=args.open_contracts, broker_day_net=number(args.broker_day_net),
                broker_trades=args.broker_trades, broker_losses=args.broker_losses,
                at=at, setup=last_signal(args.snapshot, at),
            )
        print(json.dumps(result, indent=2))
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

if __name__ == "__main__":
    main()
