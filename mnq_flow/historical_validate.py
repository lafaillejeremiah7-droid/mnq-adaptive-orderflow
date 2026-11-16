"""3-5 year MNQ historical audit and fixed-rule print-by-print replay.

Requires genuine signed CME trade prints. NEVER substitutes OHLCV or bid/ask
quotes for aggressor-side executions. No data download or order placement.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean
from typing import Iterator

from .engine import ET, TICK, Trade, session_day
from .live_stream import LiveAnalyzer

TICK_USD = Decimal("0.50")
MIN_SESSIONS_YEAR = 200


@dataclass
class Session:
    first: int = 1440
    last: int = -1
    minutes: set[int] = field(default_factory=set)
    contracts: set[str] = field(default_factory=set)

    def add(self, print_: Trade):
        at = print_.timestamp.astimezone(ET)
        minute = at.hour * 60 + at.minute
        self.first = min(self.first, minute)
        self.last = max(self.last, minute)
        self.minutes.add(minute)
        self.contracts.add(print_.contract)

    @property
    def complete(self):
        # Conservative: no gaps from 09:30 through 15:55 ET; no half-days.
        return (self.first == 570 and self.last >= 955
                and len(self.contracts) == 1
                and all(m in self.minutes for m in range(570, 956)))


def source_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise ValueError("Historical directory does not exist: " + str(directory))
    found = sorted(p for p in directory.rglob("*.csv") if p.is_file())
    if not found:
        raise ValueError("No genuine signed-trade CSV history connected. Backtest BLOCKED.")
    return found


def iter_prints(files: list[Path]) -> Iterator[Trade]:
    """Require timestamp,price,size,side,contract for actual executed MNQ trades."""
    last = None
    expiry_per_session = {}
    for path in files:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            required = {"timestamp", "price", "size", "side", "contract"}
            if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                raise ValueError(f"{path.name}: missing {sorted(required)}. "
                                 "OHLCV and bid/ask QUOTES are not executed signed prints.")
            for row_num, row in enumerate(reader, 2):
                try:
                    ts = datetime.fromisoformat(row["timestamp"].strip().replace("Z", "+00:00"))
                    if ts.utcoffset() is None:
                        raise ValueError("timestamp requires UTC offset")
                    price = Decimal(row["price"].strip())
                    ticks = price / TICK
                    if not ticks.is_finite() or ticks != ticks.to_integral_value():
                        raise ValueError("MNQ price must align to 0.25 tick")
                    qty = int(row["size"])
                    side = row["side"].strip().upper()
                    contract = row["contract"].strip().upper()
                    if qty <= 0 or side not in ("B", "S") or not contract.startswith("MNQ"):
                        raise ValueError("Invalid trade size, aggressor side, or MNQ expiry")
                    if last is not None and ts < last:
                        raise ValueError("Input files not globally chronological")
                    last = ts
                    rth_day = session_day(ts)
                    if rth_day is not None:
                        key = rth_day.isoformat()
                        if key in expiry_per_session and expiry_per_session[key] != contract:
                            raise ValueError("Mixed contract rollover within session " + key)
                        expiry_per_session[key] = contract
                    yield Trade(ts, int(ticks), qty, side, contract)
                except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
                    raise ValueError(f"{path.name} line {row_num}: {exc}") from exc


def audit(files: list[Path], min_years: int = 3) -> tuple[dict, set[str]]:
    if min_years not in (3, 4, 5):
        raise ValueError("min_years must be 3, 4 or 5")
    sessions: dict[str, Session] = {}
    first = last = None
    n = 0
    for print_ in iter_prints(files):
        n += 1
        if first is None:
            first = print_.timestamp.isoformat()
        last = print_.timestamp.isoformat()
        d = session_day(print_.timestamp)
        if d is not None:
            sessions.setdefault(d.isoformat(), Session()).add(print_)
    good = {d for d, s in sessions.items() if s.complete}
    by_year = Counter(int(d[:4]) for d in good)
    qualifying = {y for y, count in by_year.items() if count >= MIN_SESSIONS_YEAR}
    windows = [[y + i for i in range(min_years)] for y in sorted(qualifying)
               if all(y + i in qualifying for i in range(min_years))]
    years = windows[-1] if windows else []
    selected = {d for d in good if int(d[:4]) in years}
    return {
        "status": "COVERAGE_VERIFIED_SCHEMA_ONLY" if years else "BLOCKED_HISTORY_INCOMPLETE",
        "source_authenticity": "NOT independently authenticated; CSV vendor provenance required",
        "first": first, "last": last, "signed_prints": n,
        "rth_sessions_seen": len(sessions),
        "complete_rth_sessions": len(good),
        "incomplete_sessions_excluded": len(sessions) - len(good),
        "sessions_by_full_year": dict(sorted(by_year.items())),
        "min_complete_sessions_per_year": MIN_SESSIONS_YEAR,
        "consecutive_years_required": min_years,
        "selected_years": years, "selected_sessions": len(selected),
        "notice": ("No win rate, expectancy or payout probability may be reported unless "
                   "this gate passes on genuine executed MNQ trades with aggressor sides."),
    }, selected


@dataclass
class Position:
    direction: int
    entry: int
    stop: int
    target: int
    timestamp: str


def replay(files: list[Path], days: set[str], *, commission: Decimal,
           slippage: int, reward_multiple: Decimal) -> dict:
    """Frozen candidate test; next-LATER-print entry; 1 MNQ, touched target fills.

    An approximate EOD trailing-drawdown simulation, not firm-rule parity.
    """
    if not days:
        raise ValueError("Historical coverage gate failed")
    if commission < 0 or slippage < 0 or reward_multiple <= 0:
        raise ValueError("Invalid transaction cost or reward multiple")
    profile = LiveAnalyzer()
    balance = Decimal("25000")
    floor = Decimal("24000")
    peak_eod = balance
    day_start = balance
    day_net = Decimal("0")
    trades_today = consecutive_losses = 0
    completed_episode = False
    current_day = None
    last_print = None
    position = None
    pending = None
    results = []
    episodes = Counter()
    candidate_counts = Counter()

    def close(tick: Trade, raw: int, reason: str):
        nonlocal balance, day_net, consecutive_losses, position, completed_episode
        assert position is not None
        exit_tick = raw - position.direction * slippage
        net = (Decimal(position.direction * (exit_tick - position.entry))
               * TICK_USD - commission)
        balance += net
        day_net += net
        consecutive_losses = consecutive_losses + 1 if net < 0 else 0
        results.append({
            "year": tick.timestamp.astimezone(ET).year,
            "entry_timestamp": position.timestamp,
            "exit_timestamp": tick.timestamp.isoformat(),
            "side": "long" if position.direction == 1 else "short",
            "net_usd": float(net),
            "exit_reason": reason,
        })
        position = None
        if balance >= Decimal("26500"):
            completed_episode = True
            episodes["passed"] += 1
        elif balance <= floor or day_net <= Decimal("-600"):
            completed_episode = True
            episodes["failed"] += 1

    for print_ in iter_prints(files):
        session = session_day(print_.timestamp)
        if session is None or session.isoformat() not in days:
            continue
        local = print_.timestamp.astimezone(ET)
        if session != current_day:
            if position is not None and last_print is not None:
                close(last_print, last_print.price_ticks, "SESSION_END")
            current_day = session
            if completed_episode:
                balance, floor, peak_eod = Decimal("25000"), Decimal("24000"), Decimal("25000")
                completed_episode = False
            else:
                peak_eod = max(peak_eod, balance)
                floor = max(floor, peak_eod - Decimal("1000"))
            day_start, day_net = balance, Decimal("0")
            trades_today = consecutive_losses = 0
            pending = None
            profile = LiveAnalyzer()
        if position is not None:
            floating = (Decimal(position.direction * (print_.price_ticks - position.entry))
                        * TICK_USD - commission)
            if local.time() >= time(15, 0):
                close(print_, print_.price_ticks, "TIME_EXIT")
            elif balance + floating <= floor or day_net + floating <= Decimal("-600"):
                close(print_, print_.price_ticks, "FIRM_BREACH_SIMULATED")
            elif ((position.direction == 1 and print_.price_ticks <= position.stop)
                  or (position.direction == -1 and print_.price_ticks >= position.stop)):
                close(print_, print_.price_ticks, "STOP")
            elif ((position.direction == 1 and print_.price_ticks >= position.target)
                  or (position.direction == -1 and print_.price_ticks <= position.target)):
                close(print_, position.target, "TARGET_TOUCH_ASSUMED_FILL")
        if pending is not None and position is None and not completed_episode:
            age = (print_.timestamp - pending["observed"]).total_seconds()
            if age > 60 or local.time() >= time(15, 0):
                pending = None
            elif age > 0:
                if trades_today >= 2 or consecutive_losses >= 2 or day_net <= Decimal("-100"):
                    candidate_counts["personal_stop"] += 1
                else:
                    sign = pending["sign"]
                    entry = print_.price_ticks + sign * slippage
                    distance = sign * (entry - pending["stop"])
                    planned = Decimal(distance + slippage) * TICK_USD + commission
                    if (distance > 0 and planned <= Decimal("50")
                            and planned <= balance - floor - Decimal("150")
                            and day_net - planned > Decimal("-100")):
                        target = entry + sign * max(1, int(Decimal(distance) * reward_multiple))
                        position = Position(sign, entry, pending["stop"], target,
                                            print_.timestamp.isoformat())
                        trades_today += 1
                        candidate_counts["entered"] += 1
                    else:
                        candidate_counts["risk_rejected"] += 1
                pending = None
        snapshot = profile.on_trade(print_)
        if snapshot and snapshot.get("signal") in ("long_candidate", "short_candidate"):
            candidate_counts["detected"] += 1
            if not completed_episode and position is None and pending is None:
                sign = 1 if snapshot["signal"] == "long_candidate" else -1
                bar = snapshot["one_minute"]
                reference = bar["low"] if sign == 1 else bar["high"]
                pending = {
                    "sign": sign, "stop": round(reference / .25) - sign * 2,
                    "observed": print_.timestamp,
                }
        last_print = print_
    if position is not None and last_print is not None:
        close(last_print, last_print.price_ticks, "DATASET_END")
    pnl_by_year = defaultdict(list)
    for entry in results:
        pnl_by_year[entry["year"]].append(entry["net_usd"])
    years = sorted({int(day[:4]) for day in days})
    holdout = years[-1]

    def stats(values):
        return {
            "trades": len(values),
            "net_usd": round(sum(values), 2),
            "win_rate": round(sum(v > 0 for v in values) / len(values), 4) if values else None,
            "expectancy_usd": round(mean(values), 2) if values else None,
        }
    return {
        "status": "HISTORICAL_HYPOTHESIS_SIMULATION_NOT_TRADING_PROOF",
        "frozen_rule": "Existing Python LiveAnalyzer candidate; later-print 1-MNQ entry; 2R",
        "cost_assumptions": {
            "roundtrip_commission_usd": float(commission), "adverse_slippage_each_side_ticks": slippage
        },
        "all_years": stats([item["net_usd"] for item in results]),
        "per_year": {str(y): stats(pnl_by_year[y]) for y in years},
        "chronological_holdout_year": holdout,
        "holdout": stats(pnl_by_year[holdout]),
        "completed_evaluation_episodes": dict(episodes),
        "candidate_counts": dict(candidate_counts),
        "disclaimer": (
            "Does not optimize parameters or prove walk-forward predictive edge. "
            "Python signal parity with native Tradovate JS not yet established. "
            "Historical fills at target touched are optimistic; printed trades do not "
            "reconstruct passive order book or queue. EOD trailing rule is approximate, "
            "and firm intraday-risk interpretation may differ. Do not trade from this report alone."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="MNQ 3-to-5-year signed-tick verification and replay")
    parser.add_argument("--ticks-dir", required=True, help="Your authorized MNQ trade print CSV directory")
    parser.add_argument("--min-years", type=int, choices=(3, 4, 5), default=3)
    parser.add_argument("--fee", default="2.50", help="1 MNQ roundtrip fees USD")
    parser.add_argument("--slippage-ticks", type=int, default=1)
    parser.add_argument("--reward-multiple", default="2")
    parser.add_argument("--out", help="Optional JSON result, keep local")
    args = parser.parse_args()
    try:
        paths = source_files(Path(args.ticks_dir))
        coverage, eligible = audit(paths, args.min_years)
        result = {"coverage": coverage, "results": None}
        if eligible:
            result["results"] = replay(
                paths, eligible, commission=Decimal(args.fee),
                slippage=args.slippage_ticks,
                reward_multiple=Decimal(args.reward_multiple))
        payload = json.dumps(result, indent=2)
        if args.out:
            Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(payload)
        if not eligible:
            raise SystemExit(2)
    except (ValueError, OSError, InvalidOperation) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
