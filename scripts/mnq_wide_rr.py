"""Replay the wider MNQ reward/risk study and write comparison rows as CSV."""
import argparse
import csv
from pathlib import Path

from scripts.mnq_opening_range import contract_files
from scripts.mnq_reverse_exit_grid import score_period

EXAMPLES = ((25, 50), (35, 75), (50, 100))  # (stop, target)
CONTROL = (12, 18)


def rr_group(row):
    delta = row["target_points"] - row["stop_points"]
    if delta == 0:
        return "equal"
    return "reward_gt_risk" if delta > 0 else "reward_lt_risk"


def replay(archive):
    files = contract_files(archive)
    negative = [(wide, narrow) for narrow in range(25, 51) for wide in range(50, 101)]
    pairs = list(dict.fromkeys(negative + [(t, s) for s, t in negative]))
    if len(pairs) != 2651:
        raise RuntimeError("unexpected grid size")
    grid, _, _ = score_period(files, [*pairs, CONTROL], "20231004", "20241003")
    control = grid["rows"].pop()
    if (grid["sessions"], grid["trades"], control["net"]) != (200, 187, -778):
        raise ValueError("archive does not reproduce the control")
    leaders = []
    for group in ("reward_lt_risk", "reward_gt_risk"):
        best = min((r for r in grid["rows"] if rr_group(r) == group),
                   key=lambda r: (-r["stress_net"], r["stop_points"], r["target_points"]))
        leaders.append((best["stop_points"], best["target_points"]))
    selected = list(dict.fromkeys([*((t,s) for s,t in EXAMPLES), *EXAMPLES, *leaders]))
    # Additional user-requested comparison after the original eight were reported.
    selected.append((50, 50))
    later, _, _ = score_period(files, selected, "20241007", "20251008")
    if later["sessions"] != 200:
        raise ValueError("archive follow-up session count mismatch")
    for window, period in (("selection", grid), ("followup", later)):
        for row in period["rows"]:
            yield dict(window=window, group=rr_group(row), sessions=period["sessions"],
                       trades=period["trades"], **row)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = list(replay(args.archive))
    with args.output.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
