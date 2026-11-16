"""Manual chart-observation coach: advisory only, never places orders."""
from __future__ import annotations
import argparse
import json
from datetime import datetime
from .payout_coach import ET, config_read, journal_read, number, risk_check

def checklist(side, bias, level, reaction, absorption, delta5, cvd, trigger):
    # Conservative, UNVALIDATED setup hypothesis. No trading recommendation.
    trend = "up" if side == "long" else "down"
    absorption_direction = "bullish" if side == "long" else "bearish"
    delta_direction = "positive" if side == "long" else "negative"
    cvd_direction = "rising" if side == "long" else "falling"
    failures = []
    if bias != trend:
        failures.append("15m directional bias not aligned")
    if level not in {"poc", "vah", "val"}:
        failures.append("Not near a marked volume-profile reference")
    if reaction not in {"rejection", "reclaim", "acceptance"}:
        failures.append("No level reaction observed")
    if absorption != absorption_direction:
        failures.append("No directionally aligned absorption observation")
    if delta5 != delta_direction:
        failures.append("5m delta not aligned")
    if cvd != cvd_direction:
        failures.append("CVD not aligned")
    if not trigger:
        failures.append("No 1m price-action trigger")
    return {"passed": not failures, "failures": failures,
            "basis": "User-reported chart observations; not independently verified"}

def main():
    p = argparse.ArgumentParser(description="Manual MNQ risk coach (no orders).")
    p.add_argument("--config", default="account.json")
    p.add_argument("--journal", default="trades.jsonl")
    p.add_argument("--side", choices=["long", "short"], required=True)
    p.add_argument("--bias", choices=["up", "down", "neutral"], required=True)
    p.add_argument("--level", choices=["poc", "vah", "val", "other"], required=True)
    p.add_argument("--reaction", choices=["rejection", "reclaim", "acceptance", "none"], required=True)
    p.add_argument("--absorption", choices=["bullish", "bearish", "none"], required=True)
    p.add_argument("--delta-5m", choices=["positive", "negative", "neutral"], required=True)
    p.add_argument("--cvd", choices=["rising", "falling", "flat"], required=True)
    p.add_argument("--trigger-1m", action="store_true")
    p.add_argument("--entry", required=True)
    p.add_argument("--stop", required=True)
    p.add_argument("--contracts", type=int, required=True)
    p.add_argument("--equity", required=True, help="Live broker equity including unrealized P&L")
    p.add_argument("--floor", required=True, help="Current official drawdown floor")
    p.add_argument("--open-contracts", type=int, required=True)
    p.add_argument("--broker-day-net", required=True)
    p.add_argument("--broker-trades", type=int, required=True)
    p.add_argument("--broker-losses", type=int, required=True)
    p.add_argument("--at", help="Optional ISO 8601 timestamp with UTC offset")
    a = p.parse_args()
    try:
        chart = checklist(a.side, a.bias, a.level, a.reaction,
                          a.absorption, a.delta_5m, a.cvd, a.trigger_1m)
        now = datetime.fromisoformat(a.at) if a.at else datetime.now(ET)
        result = risk_check(
            config_read(a.config), journal_read(a.journal),
            side=a.side, entry=number(a.entry), stop=number(a.stop),
            contracts=a.contracts, equity=number(a.equity),
            floor=number(a.floor), open_contracts=a.open_contracts,
            broker_day_net=number(a.broker_day_net),
            broker_trades=a.broker_trades, broker_losses=a.broker_losses,
            at=now, setup=(a.side + "_candidate") if chart["passed"] else "none",
        )
        result["manual_chart_checklist"] = chart
        result["observation_source"] = "USER_REPORTED_ONLY"
        result["requires_discretionary_review"] = True
        print(json.dumps(result, indent=2))
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as error:
        p.error(str(error))

if __name__ == "__main__":
    main()
