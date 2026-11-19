"""Frozen, sequential evaluation of a four-worker failed-break policy."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import random

from scripts.agent_tournament import Event, WORKERS, forecasts_for_event
from scripts.mnq_opening_range import ET, contract_files, eligible_sessions, simulate_exit


THRESHOLD = 29.50 / 60


def signal(bars):
    low = min(bars[i][2] for i in range(30))
    high = max(bars[i][1] for i in range(30))
    for i in range(30, 299):  # 14:28 is minute 298
        _, h, l, close, _ = bars[i]
        if not low < close < high or (l < low) == (h > high):
            continue
        closes = [bars[j][3] for j in range(i-20, i+1)]
        move = closes[-1] - closes[0]
        path = sum(abs(a-b) for a,b in zip(closes, closes[1:]))
        regime = "RANGE"
        if path and 100*abs(move) >= 55*path:
            regime = "TREND_UP" if move > 0 else "TREND_DOWN"
        return i+1, 1 if l < low else -1, regime
    return None


def session(day, symbol, bars, histories):
    found = signal(bars)
    if found is None:
        return None
    entry, side, regime = found
    start = datetime.fromisoformat(day).replace(hour=9, minute=30, tzinfo=ET)
    def stamp(minute):
        return int((start + timedelta(minutes=minute)).timestamp()) * 1000
    direction = "LONG" if side == 1 else "SHORT"
    past = histories[symbol, direction]
    features = dict(detected_at_ms=stamp(entry), regime=regime, direction=direction,
                    target_distance_ticks=72, stop_distance_ticks=48, horizon_bars=30,
                    instrument="MNQ", contract=symbol, setup_id="failed_break_v1")
    # Placeholder is never passed to forecasting workers. Forecasts are computed before replay.
    scores = forecasts_for_event(Event(**features, resolved_at_ms=0, outcome="PENDING"), past) if len(past)>=10 else {}
    adaptive = bool(scores) and sum(scores.values())/len(scores) > THRESHOLD
    baseline = bool(scores) and scores[WORKERS[0].name] > THRESHOLD
    trade = simulate_exit(bars, entry, side, bars[entry][0], 48, 72, last=entry+30)
    reason = trade["exit_reason"]
    outcome = "TARGET_FIRST" if reason.startswith("target") else "TIME_LIMIT" if reason=="time_exit" else "STOP_FIRST"
    release = trade["exit_minute"] + int(reason in ("stop","target","ambiguous_stop"))
    past.append(Event(**features, resolved_at_ms=stamp(release), outcome=outcome))
    return dict(gross=trade["gross_ticks"]*.5, adaptive=adaptive, baseline=baseline, every=True, regime=regime, scores=scores)


def phase(records, histories):
    rows = [(day, session(day,symbol,bars,histories)) for day,symbol,bars in records]
    totals = {}
    daily = {}
    for name in ("adaptive","baseline","every"):
        counts = [int(bool(t and t[name])) for _,t in rows]
        pnl = [(t["gross"]-5.50) if used else 0 for (_,t),used in zip(rows,counts)]
        daily[name] = pnl
        n = sum(counts)
        totals[name] = dict(trades=n, base_net=sum(pnl)+2*n, stressed_net=sum(pnl))
    failures = []
    if totals["adaptive"]["trades"] < 30:
        failures.append("Fewer than 30 adaptive trades")
    if sum(daily["adaptive"]) <= 0:
        failures.append("Stressed P&L did not beat cash")
    for bench in ("baseline","every"):
        if sum(daily["adaptive"]) <= sum(daily[bench]):
            failures.append("Stressed P&L did not beat " + bench)
    scored = [t for _, t in rows if t and t["scores"]]
    adaptation = dict(scored_setups=len(scored),
                      regimes=dict(Counter(t["regime"] for t in scored)),
                      adaptive_only=sum(t["adaptive"] and not t["baseline"] for t in scored),
                      baseline_only=sum(t["baseline"] and not t["adaptive"] for t in scored))
    summary = dict(adaptation=adaptation, sessions=len(rows), start=rows[0][0] if rows else None, end=rows[-1][0] if rows else None,
                   policies=totals, failed_gates=failures)
    return summary, daily, [int(bool(t and t["adaptive"])) for _,t in rows]


def lower_limits(daily, trades):
    n = len(trades)
    rng = random.Random(247)
    samples = [[], [], []]
    for _ in range(19999):
        indices = []
        while len(indices) < n:
            start = rng.randrange(n)
            indices.extend((start+j)%n for j in range(min(3,n-len(indices))))
        pnl = sum(daily["adaptive"][i] for i in indices)
        count = sum(trades[i] for i in indices)
        if not count:
            return None
        samples[0].append(pnl/count)
        for k,bench in enumerate(("baseline","every"),1):
            samples[k].append((pnl-sum(daily[bench][i] for i in indices))/n)
    return [sorted(s)[int(len(s)*.05/9)-1] for s in samples]


def evaluate(archive, fresh=None):
    histories = defaultdict(list)
    files = contract_files(archive)
    # Known boundaries of the documented archive. Reject incomplete phase coverage.
    windows = [("development","20201012","20231003",598),("validation","20231004","20241003",200),
               ("reused_latest","20241007","20251008",200)]
    report = {"status":"EDGE_NOT_ESTABLISHED","phases":{}}
    for name, first, last, expected in windows:
        eligible = eligible_sessions([f for f in files if first <= f[0] <= last], Counter())
        stats, _, _ = phase(eligible, histories)
        if stats["sessions"] != expected:
            raise ValueError(f"{name} coverage mismatch, expected {expected} sessions")
        report["phases"][name] = stats
        if name != "development" and stats["failed_gates"]:
            report["stop"] = name
            return report
    if fresh is None:
        report["stop"] = "Fresh data required"
        return report
    files = contract_files(fresh)
    if any(f[0] <= "20251009" for f in files):
        raise ValueError("Fresh sample must be entirely after October 9, 2025")
    stats, daily, trades = phase(eligible_sessions(files, Counter()), histories)
    report["phases"]["fresh"] = stats
    if stats["sessions"] < 100:
        stats["failed_gates"].append("Fewer than 100 fresh sessions")
    if not stats["failed_gates"]:
        limits = lower_limits(daily,trades)
        stats["adjusted_lower_bounds"] = limits
        if limits and min(limits)>0:
            report["status"] = "CANDIDATE_FOR_INDEPENDENT_REVIEW"
        else:
            stats["failed_gates"].append("Inconclusive adjusted lower bounds")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--fresh", type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.archive,args.fresh), indent=2))
