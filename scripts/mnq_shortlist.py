"""Screen a fixed catalog of MNQ rules against a paired, costed benchmark."""

import argparse
from collections import Counter
import csv
from pathlib import Path
import json
import numpy as np

from scripts.mnq_adaptive_failed_break import signal
from scripts.mnq_opening_range import contract_files, eligible_sessions, simulate_exit

FEATURES = [*range(1, 51), 91, 99, 100]
ROOT = Path(__file__).resolve().parents[1] / "docs/shortlist"


def ratio(a, b):
    return a / b if b else np.nan


def correlation(a, b):
    return np.corrcoef(a, b)[0, 1] if np.ptp(a) and np.ptp(b) else np.nan


def features(bars, i, side, history):
    """Only bars through i inclusive, with integer tick prices and actual volume."""
    o, h, l, c, v = np.array([bars[j] for j in range(i + 1)], dtype=float).T
    top, bot = max(h[:30]), min(l[:30])
    width = top - bot
    edge = top if side == 1 else bot
    extreme = h[-1] if side == 1 else l[-1]
    wick = h[-1] - max(o[-1], c[-1]) if side == 1 else min(o[-1], c[-1]) - l[-1]
    ran = h - l
    changes = np.diff(c)
    prev = changes[:-1]
    signed = side * prev
    streak = 0
    for val in signed[::-1]:
        if val <= 0:
            break
        streak += 1
    edge_hits = h[30:-1] >= top if side == 1 else l[30:-1] <= bot
    mid = (top + bot) / 2
    midpoint_hits = np.where((h[:-1] >= mid) & (l[:-1] <= mid))[0]
    approach = side * c[-12:-1]
    signs = np.sign(prev[-10:])
    signs = signs[signs != 0]
    extremes = h[:30] if side == 1 else l[:30]
    mid_signs = np.sign(c[:30] - mid)
    mid_signs = mid_signs[mid_signs != 0]
    first_close_changes = np.diff(np.r_[o[0], c[:30]])
    valid_range = ran[:30] > 0
    r = np.diff(np.log(c))[-20:]
    adverse = r * side < 0
    last15 = c[-15:]
    trend = np.polyfit(np.arange(15), last15, 1)[0]
    nonflat = changes[changes != 0][-20:]
    prob = ratio(np.count_nonzero(nonflat > 0), len(nonflat))
    entropy = (
        -sum(p * np.log2(p) for p in (prob, 1 - prob) if p > 0)
        if len(nonflat)
        else np.nan
    )
    typ = (h + l + c) / 3
    vw = ratio(v @ typ, sum(v))
    prev_vw = ratio(v[:-10] @ typ[:-10], sum(v[:-10]))
    ix = len(v) - 10 + int(np.argmax(v[-10:]))
    data = [
        ratio(abs(extreme - edge), width),
        ratio(abs(c[-1] - edge), width),
        ratio(wick, ran[-1]),
        ratio(side * (c[-1] - o[-1]), ran[-1]),
        ratio(v[-1], np.median(v[-21:-1])),
        ratio(ran[-1], np.median(ran[-21:-1])),
        ratio(side * (o[-1] - edge), width),
        ratio(max(0, min(h[-1], h[-2]) - max(l[-1], l[-2])), ran[-1]),
        ratio(np.median(ran[-4:-1]), np.median(ran[-24:-4])),
        side * (o[-1] - c[-2]),
        ratio(sum(signed[-5:]), width),
        ratio(abs(sum(signed[-5:])), sum(abs(signed[-5:]))),
        sum(signed[-3:]) - sum(signed[-6:-3]),
        streak,
        np.mean(np.diff(abs(c[-12:-1] - edge)) < 0),
        np.mean(
            (side * (edge - c[-11:-1]) >= 0)
            & (side * (edge - c[-11:-1]) <= 0.1 * width)
        ),
        np.sum(edge_hits),
        i - midpoint_hits[-1] if len(midpoint_hits) else np.nan,
        np.sum(np.diff(signs) != 0),
        max(np.maximum.accumulate(approach) - approach),
        ratio(width, o[0]),
        ratio(side * (c[29] - o[0]), width),
        np.flatnonzero(extremes == edge)[0],
        ratio(max(v[:30]), sum(v[:30])),
        ratio(sum(v[20:30]), sum(v[:30])),
        ratio(abs(c[29] - o[0]), sum(abs(first_close_changes))),
        np.sum(np.diff(mid_signs) != 0),
        ratio(width, max(h[:15]) - min(l[:15])),
        np.mean(
            1 - abs(c[:30][valid_range] - o[:30][valid_range]) / ran[:30][valid_range]
        )
        if any(valid_range)
        else np.nan,
        np.sum(abs(extremes - edge) <= 1),
        np.sqrt(r @ r),
        ratio(sum(r[adverse] ** 2), r @ r),
        ratio(max(r**2), r @ r),
        ratio(np.mean(ran[-5:]), np.mean(ran[-20:-5])),
        ratio(side * trend, np.mean(ran[-15:])),
        correlation(np.arange(15), last15) ** 2,
        ratio(max(h) - c[-1] if side == 1 else c[-1] - min(l), width),
        correlation(r[:-1], r[1:]),
        entropy,
        sum(side * (c[-1] - c[-1 - lag]) > 0 for lag in (1, 5, 15)),
        ratio(side * (c[-1] - vw), width),
        side * (vw - prev_vw),
        ratio(np.sqrt(ratio(v @ ((typ - vw) ** 2), sum(v))), width),
        side * (c[ix] - o[ix]),
        ratio(sum(v[-5:]), sum(ran[-5:])),
        ratio(sum(v[-10:][side * (c[-10:] - o[-10:]) < 0]), sum(v[-10:])),
        correlation(abs(c[-20:] - o[-20:]), v[-20:]),
        np.sum(v[-5:] > np.median(v[-20:-5])),
        ratio(signed[-10:] @ v[-11:-1], sum(v[-11:-1])),
        ratio(np.arange(10) @ v[-10:], sum(v[-10:])),
        i + 1,
        sum(x != 0 for x in history) if len(history) == 20 else np.nan,
        ratio(history.count(side), sum(x != 0 for x in history))
        if len(history) == 20
        else np.nan,
    ]
    return data


def payoffs(bars, minute, side):
    """Return gross dollars and fill flags, including foregone signals at zero."""
    deadline = minute + 30

    def fill(at=minute, direction=side, stop=192, target=200, last=deadline):
        return simulate_exit(bars, at, direction, bars[at][0], stop, target, last=last)[
            "gross_ticks"
        ] * 0.5, 1

    baseline = fill()
    hi = max(bars[j][1] for j in range(30))
    lo = min(bars[j][2] for j in range(30))
    edge = hi if side == 1 else lo

    def delay(fade):
        for j in range(minute, minute + 3):
            change = side * (bars[j][3] - (bars[minute - 1][3] if fade else edge))
            if change < 0 if fade else change > 0:
                return fill(j + 1, -side if fade else side)
        return 0, 0

    stalled = side * (bars[minute + 4][3] - bars[minute][0]) <= 0
    return [
        baseline,
        (0, 0),
        (0, 0),
        (0, 0),
        fill(direction=-side),
        delay(False),
        delay(True),
        fill(last=minute + 5) if stalled else baseline,
        fill(target=100),
        fill(stop=140),
        fill(last=minute + 15),
        fill(stop=200),
    ]


def collect(root):
    dates = []
    xs = []
    executions = []
    history = []
    skipped = Counter()
    for day, _, bars in eligible_sessions(contract_files(root), skipped):
        event = signal(bars)
        side = 0
        if event:
            minute, original_side, _ = event
            side = -original_side
            xs.append(features(bars, minute - 1, side, history[-20:]))
            executions.append(payoffs(bars, minute, side))
        else:
            xs.append([np.nan] * len(FEATURES))
            executions.append([(0, 0)] * 12)
        dates.append(day)
        history.append(side)
    y = np.array(executions)
    if len(dates) != 998 or sum(y[:, 0, 1]) != 923 or y[:, 11, 0].sum() != 278.5:
        raise ValueError("original 50/50 control or sample mismatch")
    return dates, np.asarray(xs), y


def fold(x, y, train, end, f, action):
    q1, median, q3 = np.nanpercentile(x[:train, f], (25, 50, 75))
    v = x[train:end, f]
    valid = np.isfinite(v) | (y[train:end, 0, 1] == 0)
    triggers = [
        v > q3,
        v < q1,
        ~((v < q1) | (v > q3)),
        v > q3,
        v > median,
        v < median,
        v > median,
        v < median,
        v > median,
        v < median,
    ]
    base = y[train:end, 0, :]
    modified = np.where(triggers[action - 1][:, None], y[train:end, action, :], base)
    return valid, base, modified, triggers[action - 1] & np.isfinite(v)


def metrics(parts):
    valid, base, mod, trigger = [np.concatenate(items) for items in zip(*parts)]

    def net(arr, cost):
        return np.where(valid, arr[:, 0] - cost * arr[:, 1], 0)

    pnl = net(mod, 2)
    stress = net(mod, 3)
    delta = pnl - net(base, 2)
    equity = np.r_[0, np.cumsum(pnl)]
    n = int(sum(valid))
    eligible_signals = sum(base[:, 1])
    covered = int(sum(valid * base[:, 1]))
    result = dict(
        coverage=covered / eligible_signals,
        sessions=n,
        triggered=int(sum(trigger)),
        trades=int(sum(valid * mod[:, 1])),
        net=float(sum(pnl)),
        stress=float(sum(stress)),
        delta=float(sum(delta)),
        stress_delta=float(sum(stress - net(base, 3))),
        drawdown=float(max(np.maximum.accumulate(equity) - equity)),
    )
    # Duplicates must share both coverage and realized base-cost paths.
    return result, delta, valid, (valid.tobytes(), pnl.tobytes())


def run(root, out):
    out.mkdir(parents=True, exist_ok=True)
    with (ROOT / "ideas.csv").open() as stream:
        catalog = list(csv.DictReader(stream))
    dates, x, y = collect(root)
    blocks = [(200, 400), (400, 598), (598, 798)]
    decisions = {}
    candidates = []
    signatures = {}
    for ix, item in enumerate(catalog):
        feature, action = ix // 10 + 1, ix % 10 + 1
        if feature not in FEATURES:
            reason = (
                "Requires full prior/overnight session reconstruction"
                if feature < 61
                else "Requires aligned external markets"
                if feature < 71
                else "Requires signed trades"
                if feature < 81
                else "Requires sequenced depth"
                if feature < 91
                else "Requires additional verified calendar, feed or broader history"
            )
            decisions[item["ID"]] = dict(reason=reason)
            continue
        f = FEATURES.index(feature)
        parts = [fold(x, y, a, b, f, action) for a, b in blocks]
        stats, _, _, signature = metrics(parts)
        per_fold = [metrics([p])[0] for p in parts]
        score = float(np.median([v["stress_delta"] / v["sessions"] for v in per_fold]))
        row = dict(id=item["ID"], feature=feature, action=action, score=score, **stats)
        decisions[row["id"]] = row
        if stats["coverage"] < 0.9 or stats["triggered"] < 20:
            row["reason"] = "Insufficient selection coverage or triggered decisions"
            continue
        signatures[row["id"]] = signature
        candidates.append(row)
    ranked = sorted(
        candidates, key=lambda r: (-r["score"], -r["stress"] / r["sessions"], r["id"])
    )
    selected = []
    seen = set()
    feature_count = Counter()
    action_count = Counter()
    for row in ranked:
        sig = signatures[row["id"]]
        if sig in seen:
            reason = "Duplicate selected payoff and coverage path"
        elif feature_count[row["feature"]] >= 4:
            reason = "Four-per-feature diversity cap"
        elif action_count[row["action"]] >= 24:
            reason = "24-per-action diversity cap"
        elif len(selected) == 100:
            reason = "Below shortlist cutoff"
        else:
            selected.append(row)
            seen.add(sig)
            feature_count[row["feature"]] += 1
            action_count[row["action"]] += 1
            reason = "Retained"
        row["reason"] = reason
    assert len(selected) == 100
    (out / "locked-ids.txt").write_text("\n".join(r["id"] for r in selected) + "\n")
    audits = []
    diff = []
    mask = []
    for row in selected:
        part = fold(
            x, y, 798, len(dates), FEATURES.index(row["feature"]), row["action"]
        )
        a, d, v, _ = metrics([part])
        audits.append(a)
        diff.append(d)
        mask.append(v)
    d = np.asarray(diff)
    valid = np.asarray(mask)
    means = d.sum(axis=1) / valid.sum(axis=1)
    rng = np.random.default_rng(247)
    n = d.shape[1]
    errors = []
    for _ in range(4999):
        starts = rng.integers(n, size=(n + 4) // 5)
        indices = ((starts[:, None] + np.arange(5)) % n).ravel()[:n]
        errors.append(
            max(d[:, indices].sum(axis=1) / valid[:, indices].sum(axis=1) - means)
        )
    critical = np.quantile(errors, 0.95)
    for rank, (row, a, mean) in enumerate(zip(selected, audits, means), 1):
        row.update(rank=rank, audit=a, lower=float(mean - critical))
    result = dict(
        dates=[
            [dates[a], dates[b - 1]] for a, b in [(0, 200), *blocks, (798, len(dates))]
        ],
        baseline=[
            {
                "trades": int(y[a:b, 0, 1].sum()),
                "net": float(sum(y[a:b, 0, 0] - 2 * y[a:b, 0, 1])),
            }
            for a, b in [(0, 200), *blocks, (798, len(dates))]
        ],
        all=decisions,
    )
    (out / "screen.json").write_text(json.dumps(result, indent=1, allow_nan=False))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.archive, args.output)
