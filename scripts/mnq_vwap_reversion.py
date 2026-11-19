"""Offline replay of the frozen bar-VWAP reversal policy."""
import argparse
import json
from pathlib import Path

from scripts.mnq_opening_range import replay, simulate_exit, summarize


def simulate(bars):
    weighted = volume3 = 0
    for minute in range(210):  # final signal bar starts 12:59 Eastern
        _, high, low, close, volume = bars[minute]
        if minute >= 30 and volume3:
            # Distances in ticks times the denominator of prior VWAP.
            prior = bars[minute-1][3]*volume3 - weighted
            current = close*volume3 - weighted
            width = 80*volume3
            long = prior <= -width and -width < current < 0
            short = prior >= width and 0 < current < width
            if long or short:
                side = 1 if long else -1
                entry = bars[minute+1][0]
                distance = side*(weighted - entry*volume3)
                reward = distance // volume3  # round target toward entry
                if reward > 0 and distance <= width:
                    return simulate_exit(bars, minute+1, side, entry, 60, reward)
        weighted += (high+low+close)*volume
        volume3 += 3*volume
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_directory", type=Path)
    rows, skips, count = replay(parser.parse_args().csv_directory, simulate)
    old = [row for row in rows if row[0] <= "2025-10-09"]
    fresh = [row for row in rows if row[0] > "2025-10-09"]
    a, b = len(old)*3//5, len(old)*4//5
    periods = {"early":old[:a], "middle":old[a:b], "latest_reused":old[b:], "all_reused":old,
               "fresh":fresh}
    print(json.dumps({"files":count, "excluded_observed_dates":skips, "results":{
        name:summarize(segment, family=2) if segment else None for name,segment in periods.items()
    }}, indent=2))


if __name__ == "__main__":
    main()
