"""Offline, fixed-size, flat-to-flat account stress replay. See docs/survival_stress.md."""
import argparse
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import random
import re


class StressInputError(ValueError):
    """The supplied path or rule model cannot be replayed."""


def fields(obj, expected, label):
    if type(obj) is not dict or set(obj) != set(expected.split()):
        raise StressInputError(f"{label} requires exactly: {expected}")


def integer(value, label, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise StressInputError(f"Invalid integer for {label}")
    return value


def array(value, label, nonempty=True):
    if type(value) is not list or (nonempty and not value):
        raise StressInputError(f"Invalid list for {label}")
    return value


def nonblank(value, label):
    if type(value) is not str or not value.strip():
        raise StressInputError(f"{label} needs a source or identifier")
    return value


@dataclass(frozen=True)
class Rules:
    initial_equity_cents: int
    initial_eod_peak_cents: int
    trail_cents: int
    initial_floor_cents: int
    floor_cap_cents: int | None
    daily_loss_cents: int
    per_trade_ceiling_cents: int
    personal_daily_budget_cents: int
    reserve_cents: int
    contracts: int
    max_contracts: int
    max_trades_per_day: int
    entry_fee_cents_per_contract: int
    exit_fee_cents_per_contract: int
    planned_slippage_ticks: int

    def floor(self, peak):
        raw = peak - self.trail_cents
        return raw if self.floor_cap_cents is None else min(raw, self.floor_cap_cents)

    @classmethod
    def parse(cls, obj):
        fields(obj, " ".join(cls.__annotations__), "rules")
        for key, value in obj.items():
            if key == "floor_cap_cents" and value is None:
                continue
            integer(value, key, 0)
        rule = cls(**obj)
        if not (0 < rule.initial_equity_cents <= rule.initial_eod_peak_cents):
            raise StressInputError("Equity must be positive and at most the prior EOD peak")
        if rule.trail_cents == 0 or rule.floor(rule.initial_eod_peak_cents) != rule.initial_floor_cents:
            raise StressInputError("Initial floor disagrees with the EOD trailing rule")
        if not (1 <= rule.contracts <= rule.max_contracts and 1 <= rule.max_trades_per_day <= 2):
            raise StressInputError("Fixed contract size or daily trade limit exceeds position policy")
        if not (0 < rule.per_trade_ceiling_cents <= 10_000 and rule.daily_loss_cents > 0):
            raise StressInputError("Invalid daily or per-trade limit (maximum $100 per trade)")
        return rule


@dataclass(frozen=True)
class Trade:
    stop_ticks: int
    exits_on_stop: bool
    marks_ticks: tuple


def read_sessions(rows, cutoff):
    sessions = []
    previous_date = date.min
    for row in array(rows, "sessions"):
        fields(row, "date trades", "session")
        try:
            session_date = date.fromisoformat(row["date"])
        except (TypeError, ValueError) as exc:
            raise StressInputError("Session date needs ISO year-month-day") from exc
        if not previous_date < session_date <= cutoff:
            raise StressInputError("Duplicate, reversed or future session date")
        previous_date = session_date
        trades = []
        previous_end = -1
        for trade in array(row["trades"], "trades", False):
            fields(trade, "start_second end_second stop_ticks exit marks_ticks", "trade")
            start = integer(trade["start_second"], "start_second", 0)
            end = integer(trade["end_second"], "end_second", 0)
            if not previous_end < start <= end < 86_400:
                raise StressInputError("Trade timestamps overlap or leave the flat intraday session")
            previous_end = end
            stop = integer(trade["stop_ticks"], "stop_ticks", 1)
            if trade["exit"] not in ("stop", "other"):
                raise StressInputError("Unknown exit type")
            marks = tuple(integer(m, "mark ticks") for m in array(trade["marks_ticks"], "marks_ticks"))
            trades.append(Trade(stop, trade["exit"] == "stop", marks))
        sessions.append(trades)
    return sessions


@dataclass(frozen=True)
class Shock:
    name: str
    extra_exit_ticks: int
    extra_stop_ticks: int
    forced_exit_ticks: int

    @classmethod
    def parse(cls, row):
        fields(row, "name extra_exit_ticks extra_stop_ticks forced_exit_ticks", "scenario")
        nonblank(row["name"], "scenario name")
        for key in ("extra_exit_ticks", "extra_stop_ticks", "forced_exit_ticks"):
            integer(row[key], key, 0)
        return cls(**row)


@dataclass
class PathResult:
    ending_equity_cents: int
    final_floor_cents: int
    account_failed: bool = False
    daily_limit_touched: bool = False
    max_drawdown_cents: int = 0
    longest_underwater_eod_sessions: int = 0
    sessions_seen: int = 0
    trades_opened: int = 0
    proposals_skipped: int = 0


def replay(sessions, rule, tick_cents, shock):
    equity = rule.initial_equity_cents
    eod_peak = rule.initial_eod_peak_cents
    path_peak = recovery_peak = equity
    underwater = 0
    floor = rule.initial_floor_cents
    result = PathResult(equity, floor, account_failed=equity <= floor)
    tick_cost = rule.contracts * tick_cents
    entry_fee = rule.contracts * rule.entry_fee_cents_per_contract
    exit_fee = rule.contracts * rule.exit_fee_cents_per_contract

    def observe(value):
        nonlocal path_peak
        path_peak = max(path_peak, value)
        result.max_drawdown_cents = max(result.max_drawdown_cents, path_peak - value)
        result.account_failed |= value <= floor
        result.daily_limit_touched |= value <= daily_floor
        return result.account_failed or value <= daily_floor

    for session in sessions:
        if result.account_failed:
            break
        result.sessions_seen += 1
        daily_floor = equity - rule.daily_loss_cents
        day_halted = False
        personal_remaining = rule.personal_daily_budget_cents
        opened = 0
        for trade in session:
            planned_loss = (trade.stop_ticks + rule.planned_slippage_ticks) * tick_cost + entry_fee + exit_fee
            available = min(rule.per_trade_ceiling_cents, personal_remaining, equity - daily_floor - 1,
                            equity - floor - max(rule.reserve_cents, 1))
            if day_halted or opened >= rule.max_trades_per_day or planned_loss > available:
                result.proposals_skipped += 1
                continue
            opened += 1
            result.trades_opened += 1
            before_entry = equity
            equity -= entry_fee
            # The last mark is the gross exit fill. Earlier marks can force an exit.
            forced_exit = observe(equity)
            marked_equity = equity
            for ticks in trade.marks_ticks[:-1]:
                if forced_exit:
                    break
                marked_equity = equity + ticks * tick_cost
                forced_exit = observe(marked_equity)
            if forced_exit:
                closing_equity = marked_equity
                extra_ticks = shock.forced_exit_ticks
            else:
                closing_equity = equity + trade.marks_ticks[-1] * tick_cost
                extra_ticks = shock.extra_stop_ticks if trade.exits_on_stop else 0
            equity = closing_equity - exit_fee - (shock.extra_exit_ticks + extra_ticks) * tick_cost
            personal_remaining -= max(0, before_entry - equity)
            day_halted = observe(equity) or forced_exit
            if result.account_failed:
                break
        if not result.account_failed:
            eod_peak = max(eod_peak, equity)
            floor = rule.floor(eod_peak)
            recovery_peak = max(recovery_peak, equity)
            underwater = underwater + 1 if equity < recovery_peak else 0
            result.longest_underwater_eod_sessions = max(result.longest_underwater_eod_sessions, underwater)
    result.ending_equity_cents = equity
    result.final_floor_cents = floor
    return result


def session_blocks(sessions, block, rng):
    """Sample contiguous, non-wrapping blocks, truncating the last to the source horizon."""
    sampled = []
    while len(sampled) < len(sessions):
        start = rng.randrange(len(sessions) - block + 1)
        sampled.extend(sessions[start:start + block])
    return sampled[:len(sessions)]


def mc_estimate(count, n):
    # Two-sided 95% Wilson score interval for independent simulator draws.
    z = 1.959963984540054
    p = count / n
    den = 1 + z*z/n
    center = (p + z*z/(2*n)) / den
    width = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / den
    return {"count": count, "fraction": p,
            "mc_interval_95": [0.0 if count == 0 else max(0., center-width),
                               1.0 if count == n else min(1., center+width)]}


def run_stress(spec, *, cutoff=None):
    fields(spec, "model rules_source data_kind source instrument contract path_basis rules "
                 "sessions scenarios simulation", "stress specification")
    if spec["model"] != "eod_trail_daily_halt_v1" or spec["path_basis"] != "ordered_flat_intraday_marks":
        raise StressInputError("Unsupported account rule or mark path basis")
    if spec["data_kind"] not in ("synthetic", "historical_replay"):
        raise StressInputError("Specify synthetic or historical_replay provenance")
    for key in ("source", "rules_source"):
        nonblank(spec[key], key)
    symbol = spec["instrument"]
    if symbol not in ("MNQ", "NQ") or not re.fullmatch(
            symbol + r"[HMUZ][0-9]{4}", nonblank(spec["contract"], "contract")):
        raise StressInputError("Specify MNQ or NQ and its exact quarterly contract (e.g. MNQH2025)")
    tick_cents = 50 if symbol == "MNQ" else 500
    rule = Rules.parse(spec["rules"])
    sessions = read_sessions(spec["sessions"], cutoff or date.today())
    shocks = [Shock.parse(s) for s in array(spec["scenarios"], "scenarios")]
    if len({s.name for s in shocks}) != len(shocks):
        raise StressInputError("Scenario names must be distinct")
    sim = spec["simulation"]
    fields(sim, "seed replicates block_sessions large_drawdown_cents prolonged_sessions "
                "account_failure_appetite", "simulation")
    seed = integer(sim["seed"], "seed", 0)
    n = integer(sim["replicates"], "replicates", 2)
    block = integer(sim["block_sessions"], "block_sessions", 2)
    if block >= len(sessions):
        raise StressInputError("Need more chronological sessions than the multi-session block length")
    large = integer(sim["large_drawdown_cents"], "large_drawdown_cents", 1)
    prolonged = integer(sim["prolonged_sessions"], "prolonged_sessions", 1)
    if prolonged > len(sessions):
        raise StressInputError("Recovery threshold exceeds the simulated horizon")
    appetite = sim["account_failure_appetite"]
    if type(appetite) not in (float, int) or not 0 <= appetite <= 1:
        raise StressInputError("Specify a finite account failure appetite between zero and one")

    results = []
    for shock in shocks:
        rng = random.Random(seed)  # Pair scenarios on identical resampled paths.
        counts = dict.fromkeys(("account_failure", "daily_limit", "large_drawdown",
                                "prolonged_underwater_or_failure"), 0)
        for _ in range(n):
            path = replay(session_blocks(sessions, block, rng), rule, tick_cents, shock)
            counts["account_failure"] += path.account_failed
            counts["daily_limit"] += path.daily_limit_touched
            counts["large_drawdown"] += path.max_drawdown_cents >= large
            counts["prolonged_underwater_or_failure"] += (
                path.account_failed or path.longest_underwater_eod_sessions >= prolonged)
        estimates = {key: mc_estimate(count, n) for key, count in counts.items()}
        results.append({
            "assumptions": asdict(shock),
            "chronological_replay": asdict(replay(sessions, rule, tick_cents, shock)),
            "simulated_paths": estimates,
            "mc_upper_bound_within_selected_appetite":
                estimates["account_failure"]["mc_interval_95"][1] <= appetite,
        })
    return {
        "verdict": "RESEARCH_REVIEW_ONLY", "data_kind": spec["data_kind"], "source": spec["source"],
        "rules_source": spec["rules_source"], "model": spec["model"], "contract": spec["contract"],
        "spec_sha256": hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":"),
                                                 allow_nan=False).encode()).hexdigest(),
        "horizon_sessions": len(sessions), "simulation": sim, "scenarios": results,
        "uncertainty": "Intervals cover Monte Carlo sampling conditional on these sessions, block "
                       "length, rules and shocks. Source, fill assumptions and future risk are unverified.",
    }


def unique_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise StressInputError(f"Duplicate JSON key: {key}")
        obj[key] = value
    return obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="JSON replay specification")
    args = parser.parse_args()
    try:
        spec = json.loads(args.spec.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
        report = run_stress(spec)
    except (OSError, ValueError) as exc:
        parser.exit(2, json.dumps({"verdict": "DATA_UNVERIFIED", "reason": str(exc)}) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
