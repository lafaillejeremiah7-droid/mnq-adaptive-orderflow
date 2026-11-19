"""Replay the frozen MNQ opening-range protocol on dated Databento-format CSVs."""
import argparse
import csv
from collections import Counter, defaultdict
from datetime import date, datetime, time, timezone
from decimal import Decimal
from itertools import groupby
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from scripts.policy_validation import equity_path, lower_bounds


ET = ZoneInfo("America/New_York")
FILE = re.compile(r"glbx-mdp3-(\d{8})\.ohlcv-1m\.(MNQ[HMUZ][0-9])\.csv")
MINUTES = 330  # 09:30 through 14:59 Eastern, inclusive


def load_contract(path, day, symbol):
    start = datetime.combine(day, time(9, 30), ET).astimezone(timezone.utc)
    offset = start.hour * 60 + start.minute
    bars = {}
    instrument = None
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            stamp = r["ts_event"]
            if stamp[:10] != day.isoformat() or stamp[16:] != ":00.000000000Z":
                raise ValueError("Unexpected bar date or timestamp")
            i = int(stamp[11:13])*60 + int(stamp[14:16]) - offset
            if not 0 <= i < MINUTES:
                continue
            if (i in bars or r["symbol"] != symbol or r["rtype"] != "33"
                    or r["publisher_id"] != "1" or int(r["instrument_id"]) <= 0):
                raise ValueError("Duplicate bar or inconsistent instrument metadata")
            if instrument is not None and r["instrument_id"] != instrument:
                raise ValueError("Contract identity changed")
            instrument = r["instrument_id"]
            prices = [Decimal(r[k])*4 for k in ("open","high","low","close")]
            if any(p <= 0 or p != int(p) for p in prices):
                raise ValueError("Invalid quarter-point prices")
            o,h,l,c = map(int, prices)
            v = int(r["volume"])
            if not (l <= o <= h and l <= c <= h and v >= 0):
                raise ValueError("Invalid OHLCV")
            bars[i] = (o,h,l,c,v)
    return bars


def simulate(bars):
    hi = max(bars[i][1] for i in range(30))
    lo = min(bars[i][2] for i in range(30))
    for i in range(30, 325):
        close = bars[i][3]
        if lo <= close <= hi:
            continue
        side = 1 if close > hi else -1
        entry = bars[i+1][0]
        for j in range(i+1, MINUTES):
            o,h,l,_,_ = bars[j]
            gap = side*(o-entry)
            adverse, favorable = sorted((side*(l-entry), side*(h-entry)))
            if gap <= -80:
                ticks, reason = gap, "stop_at_open"
            elif gap >= 160:
                ticks, reason = 160, "target_at_open"
            elif j == MINUTES-1:
                ticks, reason = gap, "time_exit"
            elif adverse <= -80:
                ticks, reason = -80, "ambiguous_stop" if favorable >= 160 else "stop"
            elif favorable >= 160:
                ticks, reason = 160, "target"
            else:
                continue
            return {"direction": side, "entry_minute": i+1, "exit_minute": j,
                    "gross_ticks": ticks, "exit_reason": reason}
    return None


def replay(root):
    files = sorted((m[1], m[2], p) for p in root.glob("*.csv") if (m := FILE.fullmatch(p.name)))
    if not files:
        raise ValueError("No dated MNQ outright CSVs found")
    sessions, skips = [], Counter()
    for day_text, group in groupby(files, key=lambda row: row[0]):
        day = date.fromisoformat(day_text)
        if day.weekday() >= 4:
            continue
        choices = []
        try:
            for _, symbol, path in group:
                bars = load_contract(path, day, symbol)
                if all(i in bars for i in range(30)):
                    choices.append((sum(bars[i][4] for i in range(30)), symbol, bars))
        except (ValueError, ArithmeticError, KeyError):
            skips["invalid_session"] += 1
            continue
        if not choices:
            skips["incomplete_opening_range"] += 1
            continue
        _, symbol, bars = min(choices, key=lambda x: (-x[0], x[1]))
        if len(bars) != MINUTES:
            skips["incomplete_selected_session"] += 1
            continue
        sessions.append((day.isoformat(), symbol, simulate(bars)))
    return sessions, skips, len(files)


def summarize(rows):
    if not rows:
        raise ValueError("Empty evaluation segment")
    trades = [t for _,_,t in rows if t is not None]
    # MNQ tick = 50 cents. Base costs = 250 cents fees + 100 cents slippage.
    cents = [t["gross_ticks"]*50-350 if t else 0 for _,_,t in rows]
    n = len(trades)
    counts = [int(t is not None) for _,_,t in rows]
    # A fixed illustrative research portfolio is used only for return diagnostics.
    returns, dd, _, _ = equity_path(1_000_000, cents)
    bounds = lower_bounds(cents, counts, returns, family=1, block=3, seed=247, draws=3999)
    return dict(start=rows[0][0], end=rows[-1][0], sessions=len(rows), trades=n,
                winners=sum(v > 0 for v in cents), net_dollars=sum(cents)/100,
                expectancy_dollars=sum(cents)/100/n if n else None,
                stressed_net_dollars=(sum(cents)-200*n)/100, max_close_drawdown_dollars=dd/100,
                exits=dict(Counter(t["exit_reason"] for t in trades)), uncertainty=bounds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_directory", type=Path)
    args = parser.parse_args()
    rows, skips, count = replay(args.csv_directory)
    a,b = len(rows)*3//5, len(rows)*4//5
    report = {k:summarize(v) for k,v in (("development",rows[:a]),("validation",rows[a:b]),
                                          ("holdout",rows[b:]),("all",rows))}
    print(json.dumps(dict(files=count, excluded_observed_dates=skips, results=report), indent=2))


if __name__ == "__main__":
    main()
