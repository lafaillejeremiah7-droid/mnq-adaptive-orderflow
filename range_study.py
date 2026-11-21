"""Compare opening and midday MNQ ranges on matched dates."""
import argparse
import csv
import hashlib
import io
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

from quantlab import ticks, timestamp

ROOT = Path(__file__).resolve().parent
EASTERN = ZoneInfo("America/New_York")
STARTS = (570, 720)
LENGTH = 30


def compare(rows):
    dates = defaultdict(lambda: [[], []])
    last = None
    for row in rows:
        now = timestamp(row["timestamp"])
        if row["contract"] != "MNQH5" or (last is not None and now <= last):
            raise ValueError("expected ordered, unique MNQH5 bars")
        last = now
        local = now.astimezone(EASTERN)
        day = local.date().isoformat()
        if not day.startswith("2025-02-") or local.weekday() >= 5:
            continue
        windows = dates[day]
        minute = local.hour * 60 + local.minute
        for i, start in enumerate(STARTS):
            if start <= minute < start + LENGTH:
                spread = ticks(row["high"]) - ticks(row["low"])
                if spread < 0:
                    raise ValueError("negative range")
                windows[i].append(spread / 4)
    pairs, excluded = {}, []
    for day, (opening, midday) in sorted(dates.items()):
        if len(opening) != LENGTH or len(midday) != LENGTH:
            excluded.append(day)
            continue
        pairs[day] = {"opening": mean(opening), "midday": mean(midday),
                      "difference": (sum(opening) - sum(midday)) / LENGTH}
    if not pairs:
        raise ValueError("no observed dates with both windows complete")
    differences = [p["difference"] for p in pairs.values()]
    return {"units":"index points per one-minute bar", "eligible_dates":len(pairs),
            "excluded_observed_dates":excluded, "opening_larger":sum(x > 0 for x in differences),
            "ties":differences.count(0), "median_paired_difference":median(differences),
            "daily_pairs":pairs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bars", type=Path)
    raw = parser.parse_args().bars.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != json.loads((ROOT/"examples/mnqh5-feb.json").read_text())["data_sha256"]:
        parser.error("input differs from the registered February dataset")
    result = compare(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    print(json.dumps({"data_sha256":sha, **result}, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
