"""Offline Nasdaq research projects. Run from the repository root with -m."""

import argparse
import csv
from collections import defaultdict
from datetime import date
import json
import math
from pathlib import Path
import re


def finite(x):
    if isinstance(x, bool):
        raise ValueError("expected a finite number")
    value = float(x)
    if not math.isfinite(value):
        raise ValueError("expected a finite number")
    return value


def dcf(s):
    """Two-stage equity DCF using a cash-flow-to-equity proxy, USD millions."""
    base = (
        finite(s["operating_cash"])
        - finite(s["cash_capex"])
        + finite(s["net_borrowing"])
    )
    shares = finite(s["shares_millions"])
    k, g = finite(s["cost_of_equity"]), finite(s["terminal_growth"])
    growth = [finite(rate) for rate in s["annual_growth"]]
    if (
        finite(s["cash_capex"]) < 0
        or shares <= 0
        or base <= 0
        or not growth
        or not -1 < g < k
        or min(growth) <= -1
    ):
        raise ValueError(
            "positive cash and shares, valid growth and discount > terminal growth required"
        )
    cf, pv = base, 0.0
    for year, rate in enumerate(growth, 1):
        cf *= 1 + rate
        pv += cf / (1 + k) ** year
    terminal = cf * (1 + g) / (k - g) / (1 + k) ** len(growth)
    return {
        "base_fcfe_usd_millions": base,
        "value_per_share": round((pv + terminal) / shares, 2),
        "terminal_pct_of_value": round(100 * terminal / (terminal + pv), 2),
    }


def basis(s):
    spot, future = finite(s["spot"]), finite(s["future"])
    r, q = finite(s["rate"]), finite(s["dividend_yield"])
    days = (date.fromisoformat(s["expiry"]) - date.fromisoformat(s["as_of"])).days
    if days < 0 or min(spot, future) <= 0:
        raise ValueError("invalid dates or prices")
    fair = spot * math.exp((r - q) * days / 365)
    return {
        "days": days,
        "model_futures": round(fair, 4),
        "quoted_minus_model_points": round(future - fair, 4),
        "nq_usd_per_contract_difference": round(20 * (future - fair), 2),
    }


def positioning(rows):
    previous = None
    result = []
    for row in rows:
        day = date.fromisoformat(row["date"])
        oi = int(row["open_interest"])
        if row["market_code"] != "209742" or oi <= 0 or (previous and day <= previous):
            raise ValueError(
                "expected ascending distinct NQ mini reports with positive open interest"
            )
        out = {"as_of": str(day)}
        for group in ("asset_manager", "leveraged_fund"):
            long, short = (int(row[group + field]) for field in ("_long", "_short"))
            if not (0 <= long <= oi and 0 <= short <= oi):
                raise ValueError("invalid reported position")
            out[group + "_net_contracts"] = long - short
            out[group + "_net_pct_oi"] = round(100 * (long - short) / oi, 2)
        result.append(out)
        previous = day
    if not result:
        raise ValueError("no reports")
    return result


def auction(s):
    """Classify one completed minute against an independently supplied prior value area."""
    minute, ref = s["minute_start_ms"], s["profile_known_ms"]
    if any(type(t) is not int for t in (minute, ref, s["complete_through_ms"])):
        raise ValueError("timestamps must be integer milliseconds")
    lo, hi = s["val_ticks"], s["vah_ticks"]
    if (
        not re.fullmatch(r"M?NQ[HMUZ][0-9]{1,2}", s["contract"])
        or s["profile_contract"] != s["contract"]
        or minute % 60000
        or not 0 < ref <= minute
        or type(lo) is not int
        or type(hi) is not int
        or not 0 < lo < hi
        or not s["prints"]
        or s["complete_through_ms"] < minute + 60000
    ):
        raise ValueError(
            "need a completed minute and previously known same-contract profile"
        )
    above = below = False
    outside_delta = 0
    previous = minute
    for stamp, price, side, qty in s["prints"]:
        if (
            type(stamp) is not int
            or not previous <= stamp < minute + 60000
            or type(price) is not int
            or price <= 0
            or type(qty) is not int
            or qty <= 0
            or side not in ("B", "S")
        ):
            raise ValueError("expected ordered aggressor-tagged prints in tick units")
        previous = stamp
        above |= price > hi
        below |= price < lo
        if price > hi or price < lo:
            outside_delta += qty if side == "B" else -qty
    label = "none"
    if lo < price < hi and above != below:
        if above and outside_delta > 0:
            label = "failed_high"
        if below and outside_delta < 0:
            label = "failed_low"
    return {
        "observation": label,
        "outside_aggressor_delta": outside_delta,
        "last_price_ticks": price,
    }


def calibration(rows):
    """Expanding walk-forward, next observed close up after an up/down/flat close."""
    prior_date = last = sign = None
    counts = defaultdict(lambda: [0, 0])
    up = n = 0
    folds = defaultdict(lambda: [0, 0.0, 0.0])
    bins = defaultdict(lambda: [0, 0.0, 0])
    for row in rows:
        day = date.fromisoformat(row["observation_date"])
        if prior_date and day <= prior_date:
            raise ValueError("duplicate or unordered date")
        prior_date = day
        if row["NASDAQ100"] in ("", "."):
            continue
        price = finite(row["NASDAQ100"])
        if price <= 0:
            raise ValueError("nonpositive index close")
        if last is not None:
            y = int(price > last)
            if sign is not None:
                wins, seen = counts[sign]
                if n >= 252:
                    p, base = (wins + 1) / (seen + 2), (up + 1) / (n + 2)
                    fold = folds[day.year]
                    fold[0] += 1
                    fold[1] += (p - y) ** 2
                    fold[2] += (base - y) ** 2
                    b = bins[int(10 * p)]
                    b[0] += 1
                    b[1] += p
                    b[2] += y
                counts[sign] = [wins + y, seen + 1]
                up += y
                n += 1
            sign = (price > last) - (price < last)
        last = price
    if not folds:
        raise ValueError("insufficient history for walk-forward scoring")

    def score(v):
        n, a, b = v
        return {"n": n, "brier": round(a / n, 6), "baseline_brier": round(b / n, 6)}

    return {
        "all": score([sum(v[i] for v in folds.values()) for i in range(3)]),
        "by_year": {k: score(v) for k, v in folds.items()},
        "reliability": {
            f"{k * 10}-{(k + 1) * 10}%": {
                "n": n,
                "mean_p": round(p / n, 4),
                "observed_up": round(y / n, 4),
            }
            for k, (n, p, y) in sorted(bins.items())
        },
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "project", choices=["dcf", "auction", "basis", "positioning", "calibration"]
    )
    cli.add_argument("file", type=Path)
    args = cli.parse_args()
    functions = {
        "dcf": dcf,
        "auction": auction,
        "basis": basis,
        "positioning": positioning,
        "calibration": calibration,
    }
    with args.file.open(newline="") as file:
        data = (
            csv.DictReader(file)
            if args.project in ("positioning", "calibration")
            else json.load(file)
        )
        print(json.dumps(functions[args.project](data), indent=2))
