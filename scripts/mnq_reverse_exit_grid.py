"""Replay paired MNQ stop/target distances on identical reversed failed-break signals."""
import argparse
from collections import Counter
from itertools import product
import json
from pathlib import Path

from scripts.mnq_adaptive_failed_break import signal
from scripts.mnq_opening_range import contract_files, eligible_sessions, simulate_exit
from scripts.policy_validation import equity_path, lower_bounds


GRID = tuple(product((6, 12, 18, 24), (6, 12, 18, 24, 36)))


def score_period(files, pairs, first, last):
    paths = {pair: [] for pair in pairs}
    counts = []
    skips = Counter()
    for _, _, bars in eligible_sessions([f for f in files if first <= f[0] <= last], skips):
        setup = signal(bars)
        counts.append(int(setup is not None))
        for stop, target in pairs:
            gross = 0
            if setup is not None:
                minute, side, _ = setup
                fill = simulate_exit(bars, minute, -side, bars[minute][0],
                                     4*stop, 4*target, last=minute+30)
                gross = 50 * fill["gross_ticks"]  # cents
            paths[stop,target].append(gross)
    trades = sum(counts)
    rows = []
    for (stop,target), gross in paths.items():
        base_net = [v-350*n for v,n in zip(gross,counts)]
        _, drawdown, _, _ = equity_path(1_000_000,base_net)
        rows.append(dict(stop_points=stop,target_points=target,gross=sum(gross)/100,
                         net=sum(base_net)/100,stress_net=(sum(gross)-550*trades)/100,
                         wins=sum(v>0 for v in base_net),close_drawdown=drawdown/100))
    return dict(sessions=len(counts), trades=trades, exclusions=dict(skips), rows=rows), paths, counts


def evaluate(root):
    files = contract_files(root)
    grid, paths, counts = score_period(files, GRID, "20231004", "20241003")
    control = next(r for r in grid["rows"] if (r["stop_points"],r["target_points"]) == (12,18))
    if (grid["sessions"],grid["trades"],control["net"]) != (200,187,-778.0):
        raise ValueError("Validation sample differs from the prior reversed-entry backtest")
    top = max(grid["rows"], key=lambda r:r["stress_net"])  # GRID order resolves ties
    report = dict(grid=grid,leader=top,followup=None)
    if top["stress_net"] > 0:
        pair = (top["stop_points"],top["target_points"])
        nets = [v-550*n for v,n in zip(paths[pair],counts)]
        returns, *_ = equity_path(1_000_000,nets)
        bounds = lower_bounds(nets, counts, returns, family=24, block=3, seed=247, draws=19999)
        report["adjusted_bounds"] = bounds
        if (bounds.get("expectancy_lower_cents_per_trade",0)>0 and
                bounds.get("mean_paired_session_return_improvement_lower",0)>0):
            followup, _, _ = score_period(files,[pair],"20241007","20251008")
            if followup["sessions"] != 200:
                raise ValueError("Incomplete follow-up sample")
            report["followup"] = followup
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    print(json.dumps(evaluate(parser.parse_args().archive), indent=2))
