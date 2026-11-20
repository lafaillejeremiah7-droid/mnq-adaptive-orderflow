"""Replay the fixed 50/50 MNQ exits with a $1 fee and separate slippage scenarios."""
import argparse
from collections import Counter
import json
from pathlib import Path

from scripts.mnq_adaptive_failed_break import signal
from scripts.mnq_opening_range import replay, simulate_exit
from scripts.policy_validation import equity_path


def symmetric_exit(bars):
    setup = signal(bars)
    if setup is None:
        return None
    minute, original_side, _ = setup
    return simulate_exit(bars, minute, -original_side, bars[minute][0],
                         200, 200, last=minute + 30)  # 50 points = 200 ticks


def summarize(rows):
    trades = [trade for _, _, trade in rows if trade is not None]
    gross_cents = sum(t["gross_ticks"] * 50 for t in trades)
    scenarios = []
    for ticks_per_side in (0, 1, 2):
        cost_cents = 100 + 2 * ticks_per_side * 50
        pnl = [t["gross_ticks"] * 50 - cost_cents if t is not None else 0
               for _, _, t in rows]
        _, dd, _, _ = equity_path(1_000_000, pnl)
        scenarios.append(dict(slippage_ticks_per_side=ticks_per_side, net_usd=sum(pnl)/100,
                              winning_trades=sum(x > 0 for x in pnl),
                              max_session_close_drawdown_usd=dd/100))
    return dict(start=rows[0][0], end=rows[-1][0], sessions=len(rows), trades=len(trades),
                gross_usd=gross_cents/100, exits=dict(Counter(t["exit_reason"] for t in trades)),
                scenarios=scenarios)


def evaluate(root):
    rows, skips, files = replay(root, symmetric_exit)
    groups = {"early": [r for r in rows if r[0] < "2023-10-04"],
              "selection": [r for r in rows if "2023-10-04" <= r[0] <= "2024-10-03"],
              "later": [r for r in rows if r[0] > "2024-10-03"], "all": rows}
    report = {name: summarize(group) for name, group in groups.items()}
    for name, trades, gross in (("selection", 187, 1723.5), ("later", 192, 530)):
        if (report[name]["trades"], report[name]["gross_usd"]) != (trades, gross):
            raise ValueError(f"{name} failed to reproduce the original gross result")
    return dict(round_trip_fee_usd=1, eligible_outright_files=files, excluded_dates=skips,
                periods=report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    print(json.dumps(evaluate(parser.parse_args().archive), indent=2))
