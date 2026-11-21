"""Pure Python reference for a narrowly scoped NQ/MNQ aggregation kernel."""
import argparse
import json
from collections import defaultdict
from pathlib import Path

HEADER = "timestamp_ns,price_ticks,size,side,sequence"
NANOS_PER_MINUTE = 60_000_000_000

def aggregate(path):
    vap = defaultdict(int)
    minutes = set()
    rows = total = weighted = buy = sell = unknown = checksum = 0
    last = None
    with Path(path).open(encoding="ascii", newline="") as f:
        if f.readline().rstrip("\r\n") != HEADER:
            raise ValueError("unexpected benchmark input schema")
        for raw in f:
            parts = raw.rstrip("\r\n").split(",")
            if len(parts) != 5:
                raise ValueError("malformed benchmark row")
            ts, px, qty, seq = map(int, (parts[0], parts[1], parts[2], parts[4]))
            side = parts[3]
            if ts <= 0 or px <= 0 or qty <= 0 or seq < 0 or side not in ("B","A","N"):
                raise ValueError("invalid benchmark row")
            key = (ts, seq)
            if last is not None and key <= last:
                raise ValueError("unsorted benchmark input")
            last = key
            rows += 1
            total += qty
            weighted += px * qty
            vap[px] += qty
            minute = ts // NANOS_PER_MINUTE
            minutes.add(minute)
            if side == "B":
                buy += qty
                checksum += minute * qty
            elif side == "A":
                sell += qty
                checksum -= minute * qty
            else:
                unknown += qty
    if not rows:
        raise ValueError("empty benchmark")
    poc = min(vap, key=lambda p: (-vap[p], abs(p*total-weighted), p))
    lo = hi = poc
    covered = vap[poc]
    target = (total*7+9)//10
    lower, upper = min(vap), max(vap)
    while covered < target:
        left = lo-1 if lo>lower else None
        right = hi+1 if hi<upper else None
        if left is None:
            chosen = right
        elif right is None:
            chosen = left
        else:
            lv,rv = vap[left],vap[right]
            chosen = (left if lv>rv else right if rv>lv else
                      left if abs(left*total-weighted)<=abs(right*total-weighted) else right)
        if chosen is None: break
        covered += vap[chosen]
        lo,hi=min(lo,chosen),max(hi,chosen)
    return {
        "rows":rows,"contracts":total,"weighted_price_ticks":weighted,
        "poc_ticks":poc,"vah_ticks":hi,"val_ticks":lo,
        "buy_contracts":buy,"sell_contracts":sell,"unknown_contracts":unknown,
        "unique_prices":len(vap),"unique_minutes":len(minutes),
        "minute_delta_weighted_checksum":checksum,
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("data",type=Path)
    print(json.dumps(aggregate(p.parse_args().data),sort_keys=True))

if __name__ == "__main__":
    main()
