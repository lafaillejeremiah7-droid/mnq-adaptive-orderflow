"""Empirical nonnegative Kelly estimates for the baseline and the locked first candidate."""

import argparse
import json
from pathlib import Path
import numpy as np

from scripts.mnq_shortlist import ROOT, FEATURES, collect, fold


def empirical_kelly(multiples):
    """Maximize mean log(1+fR) for 0<=f<=1 with positive wealth in every sample."""
    x = np.asarray(multiples, dtype=float)
    if x.size == 0 or not np.isfinite(x).all():
        raise ValueError("need finite, nonempty observed returns")
    if x.mean() <= 0:
        return 0.0
    hi = 1.0
    if x.min() <= -1:
        hi = min(hi, (1 - 1e-10) / (-x.min()))

    def slope(f):
        return np.mean(x / (1 + f * x))

    if slope(hi) >= 0:
        return hi
    lo = 0.0
    for _ in range(70):
        mid = (lo + hi) / 2
        if slope(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def stats(tape, risk, cost):
    fills = tape[tape[:, 1] > 0, 0] - cost
    r = fills / risk
    return dict(
        trades=len(fills),
        wins=int(sum(fills > 0)),
        net_usd=float(sum(fills)),
        mean_usd=float(np.mean(fills)),
        planned_unit_usd=risk,
        empirical_f=empirical_kelly(r),
    )


def run(root):
    dates, x, y = collect(root)
    benchmark = {}
    for col, name, stop in ((11, "50/50", 50), (0, "48/50", 48)):
        benchmark[name] = {}
        for cost in (1, 2, 3):
            benchmark[name][cost] = {
                k: stats(y[a:b, col, :], 2 * stop + cost, cost)
                for k, a, b in (
                    ("earlier", 0, 798),
                    ("later", 798, 998),
                    ("all", 0, 998),
                )
            }
    top = (ROOT / "locked-ids.txt").read_text().splitlines()[0]
    n = int(top.split("-")[1]) - 1
    f = FEATURES.index(1 + n // 10)
    action = n % 10 + 1
    tapes = []
    for a, b in [(200, 400), (400, 598), (598, 798), (798, 998)]:
        valid, _, mod, _ = fold(x, y, a, b, f, action)
        tapes.append(mod[valid])
    train = np.vstack(tapes[:3])
    later = tapes[3]
    train_r = stats(train, 98, 2)
    audit = stats(later, 98, 2)
    r = (later[later[:, 1] > 0, 0] - 2) / 98
    fixed = {}
    for share in (1, 0.5, 0.25):
        frac = share * train_r["empirical_f"]
        wealth_factors = 1 + frac * r
        fixed[share] = dict(
            f=frac,
            log_growth_per_trade=float(np.mean(np.log(wealth_factors)))
            if np.all(wealth_factors > 0)
            else None,
        )
    return dict(
        baseline=benchmark,
        selection_leader=top,
        selection=train_r,
        later=audit,
        later_growth_using_selection_fraction=fixed,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    print(json.dumps(run(parser.parse_args().archive), indent=2))
