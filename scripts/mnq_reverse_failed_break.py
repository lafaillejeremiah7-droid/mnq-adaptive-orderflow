"""Paired direction reversal on the previously examined unfiltered validation setups."""
import argparse
from collections import Counter
import json
from pathlib import Path

from scripts.mnq_adaptive_failed_break import signal
from scripts.mnq_opening_range import contract_files, eligible_sessions, simulate_exit


def evaluate(root):
    files = [f for f in contract_files(root) if "20231004" <= f[0] <= "20241003"]
    groups = {k: [] for k in ("original", "reverse_long", "reverse_short", "reverse_total")}
    sessions = 0
    skips = Counter()
    for _, _, bars in eligible_sessions(files, skips):
        sessions += 1
        setup = signal(bars)
        if setup is None:
            continue
        minute, original_side, _ = setup
        entry = bars[minute][0]
        for side in (original_side, -original_side):
            gross = .50 * simulate_exit(bars, minute, side, entry, 48, 72, last=minute+30)["gross_ticks"]
            if side == original_side:
                groups["original"].append(gross)
            else:
                groups["reverse_long" if side == 1 else "reverse_short"].append(gross)
                groups["reverse_total"].append(gross)
    report = {k: dict(trades=len(p), gross=sum(p), net=sum(p)-3.50*len(p),
                      stress_net=sum(p)-5.50*len(p), wins=sum(x>3.50 for x in p))
              for k,p in groups.items()}
    if sessions != 200 or report["original"]["trades"] != 187 or report["original"]["net"] != -746.50:
        raise ValueError("Input does not reproduce the published validation benchmark")
    return dict(sessions=sessions, excluded_dates=skips, results=report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    print(json.dumps(evaluate(parser.parse_args().archive), indent=2))
