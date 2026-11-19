"""Event-driven memecoin trading desk with a persistent paper broker."""

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from collections import deque
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal, getcontext
from pathlib import Path

getcontext().prec = 80


def number(value, name, *, zero=False):
    if type(value) not in (str, int):
        raise ValueError(f"{name} needs a decimal string or integer")
    x = Decimal(value)
    if (
        not x.is_finite()
        or x < 0
        or (not zero and not x)
        or x > Decimal("1e15")
        or x.as_tuple().exponent < -40
    ):
        raise ValueError(f"Invalid {name}")
    return x


def validate_config(c):
    fields = {
        "tokens",
        "cash_usd",
        "order_usd",
        "exposure_usd",
        "daily_loss_usd",
        "fee_bps",
        "entry_bps",
        "stop_bps",
        "target_bps",
        "max_spread_bps",
        "max_age_seconds",
        "lookback",
        "max_gap_seconds",
    }
    if set(c) != fields or not isinstance(c["tokens"], dict) or not c["tokens"]:
        raise ValueError("Invalid desk configuration")
    for asset, decimals in c["tokens"].items():
        if not asset.strip() or type(decimals) is not int or not 0 <= decimals <= 18:
            raise ValueError("Invalid token identifier or base-unit precision")
    for k in fields - {"tokens", "lookback", "max_age_seconds", "max_gap_seconds"}:
        x = number(c[k], k, zero=k == "fee_bps")
        if k.endswith("bps") and x >= 10000:
            raise ValueError(f"{k} must be less than 10000")
    for k in ("lookback", "max_age_seconds", "max_gap_seconds"):
        if type(c[k]) is not int or not 1 <= c[k] <= 10000:
            raise ValueError(f"Invalid {k}")


def read_quote(q, c, now):
    if (
        set(q) != {"asset", "ts", "bid", "ask", "bid_size", "ask_size"}
        or q["asset"] not in c["tokens"]
    ):
        raise ValueError("Unexpected fields or unlisted token")
    if (
        type(q["ts"]) is not int
        or not 0 < q["ts"] <= now
        or now - q["ts"] > c["max_age_seconds"]
    ):
        raise ValueError("Stale or future quote")
    bid, ask = (number(q[k], k) for k in ("bid", "ask"))
    if bid > ask:
        raise ValueError("Crossed quote")
    return (
        bid,
        ask,
        number(q["bid_size"], "bid_size", zero=True),
        number(q["ask_size"], "ask_size", zero=True),
    )


def initial(c):
    return {
        "cash": str(c["cash_usd"]),
        "position": None,
        "pending": None,
        "last": {},
        "history": {},
        "day": None,
        "opening_equity": None,
        "halted": False,
        "clock": 0,
    }


def signal_bot(s, q, c, previous, bid, ask):
    """Compare the current mid to the oldest of the preceding lookback quotes."""
    asset, ts = q["asset"], q["ts"]
    hist = deque(s["history"].get(asset, []), maxlen=c["lookback"])
    gap = previous and ts - previous["ts"] > c["max_gap_seconds"]
    if gap:
        hist.clear()
    mid = (bid + ask) / 2
    momentum = len(hist) == hist.maxlen and mid >= Decimal(hist[0]) * (
        1 + Decimal(c["entry_bps"]) / 10000
    )
    hist.append(str(mid))
    s["history"][asset] = list(hist)
    return mid, momentum


def live_signal(s, q, c, previous, bid, ask):
    """Compare fresh quotes to a time-based reference; faster polling must not shorten the horizon."""
    ts, asset = q["ts"], q["asset"]
    cutoff = ts - c.get("signal_horizon_seconds", 900 * c["lookback"])
    history = s.setdefault("timed_history", {}).get(asset, [])
    if previous and ts - previous["ts"] > c["max_gap_seconds"]:
        history = []
    history = [point for point in history if point[0] >= cutoff - 60]
    reference = next(
        (price for when, price in reversed(history) if when <= cutoff), None
    )
    mid = (bid + ask) / 2
    history.append([ts, str(mid)])
    s["timed_history"][asset] = history
    return mid, reference is not None and mid >= Decimal(reference) * (
        1 + Decimal(c["entry_bps"]) / 10000
    )


def risk_bot(c, cash):
    return min(cash, Decimal(c["order_usd"]), Decimal(c["exposure_usd"]))


def process(s, q, c, now, *, live=False):
    bid, ask, bid_size, ask_size = read_quote(q, c, now)
    asset, ts = q["asset"], q["ts"]
    previous = s["last"].get(asset)
    if previous == q:
        return None
    if ts < s["clock"] or (previous and ts <= previous["ts"]):
        raise ValueError("Out-of-order or conflicting quote")
    s["clock"] = ts
    s["last"][asset] = q
    signal = live_signal if live else signal_bot
    if live and not ask_size:
        mid, momentum = bid, False
        s.setdefault("timed_history", {}).pop(asset, None)
    else:
        mid, momentum = signal(s, q, c, previous, bid, ask)
    pos, pending = s["position"], s["pending"]
    record = {
        "ts": ts,
        "asset": asset,
        "action": "observe",
        "bid": str(bid),
        "ask": str(ask) if ask_size else None,
    }
    if pos and pos["asset"] != asset:
        return record
    cash = Decimal(s["cash"])
    qty = Decimal(pos["qty"]) if pos else Decimal(0)
    day = datetime.fromtimestamp(ts, UTC).date().isoformat()
    if day != s["day"]:
        # Carry yesterday's last observed marked equity across the boundary to include gaps.
        s.update(day=day, opening_equity=s.get("last_equity", str(cash)), halted=False)
        if pending and pending["side"] == "buy":
            s["pending"] = pending = None
    fee = Decimal(c["fee_bps"]) / 10000

    def mark(value):
        s["last_equity"] = str(value)
        if Decimal(s["opening_equity"]) - value >= Decimal(c["daily_loss_usd"]):
            s["halted"] = True

    mark(cash + qty * bid * (1 - fee))
    spread_ok = (ask - bid) * 10000 <= mid * Decimal(c["max_spread_bps"])
    if (
        pending
        and ts - pending["ts"] > (60 if live else c["max_gap_seconds"])
        and pending["side"] == "buy"
    ):
        s["pending"] = pending = None
    if pending and pending["asset"] == asset:
        s["pending"] = None
        if pending["side"] == "buy" and not pos and spread_ok and not s["halted"]:
            budget = risk_bot(c, cash)
            unit = Decimal(1).scaleb(-c["tokens"][asset])
            qty = min(ask_size, budget / (ask * (1 + fee))).quantize(
                unit, rounding=ROUND_DOWN
            )
            if qty > 0:
                cash -= qty * ask * (1 + fee)
                pos = {"asset": asset, "qty": str(qty), "entry": str(ask)}
                record.update(action="paper_buy", qty=str(qty), price=str(ask))
        elif pending["side"] == "sell" and pos:
            unit = Decimal(1).scaleb(-c["tokens"][asset])
            sold = min(qty, bid_size).quantize(unit, rounding=ROUND_DOWN)
            if sold > 0:
                cash += sold * bid * (1 - fee)
                qty -= sold
                pos = {**pos, "qty": str(qty)} if qty else None
                record.update(action="paper_sell", qty=str(sold), price=str(bid))
            if pos:
                s["pending"] = {"asset": asset, "ts": ts, "side": "sell"}
    s.update(cash=str(cash), position=pos)
    mark(cash + (qty * bid * (1 - fee) if pos else 0))
    if pos:
        change = (bid / Decimal(pos["entry"]) - 1) * 10000
        if (
            s["halted"]
            or change <= -Decimal(c["stop_bps"])
            or change >= Decimal(c["target_bps"])
        ):
            s["pending"] = {"asset": asset, "ts": ts, "side": "sell"}
    elif (
        record["action"] == "observe"
        and momentum
        and spread_ok
        and not s["halted"]
        and not s["pending"]
    ):
        s["pending"] = {"asset": asset, "ts": ts, "side": "buy"}
    record.update(
        pending=s["pending"],
        cash=s["cash"],
        halted=s["halted"],
        equity=s["last_equity"],
        position=pos,
    )
    return record


def ingest(db, c, digest, quote, now, *, live=False):
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT config,state FROM desk WHERE id=1").fetchone()
        if row and row[0] != digest:
            raise ValueError("Configuration or run mode differs from this ledger")
        state = json.loads(row[1]) if row else initial(c)
        event = process(state, quote, c, now, live=live)
        if event is not None:
            db.execute(
                "INSERT OR REPLACE INTO desk VALUES(1,?,?)", (digest, json.dumps(state))
            )
            db.execute("INSERT INTO journal(event) VALUES(?)", (json.dumps(event),))
        db.commit()
        return event
    except Exception:
        db.rollback()
        raise


def open_ledger(path):
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE IF NOT EXISTS desk(id INTEGER PRIMARY KEY,config TEXT,state TEXT);
                        CREATE TABLE IF NOT EXISTS archived_stats(id INTEGER PRIMARY KEY, stats TEXT);
                        CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY,event TEXT);""")
    return db


def config_digest(c, mode):
    return hashlib.sha256(json.dumps([c, mode], sort_keys=True).encode()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--db", type=Path, required=True)
    p.add_argument(
        "--replay",
        action="store_true",
        help="Use input event time as the paper simulation clock",
    )
    args = p.parse_args()
    c = json.loads(args.config.read_text())
    validate_config(c)
    digest = config_digest(c, "replay" if args.replay else "stdin")
    db = open_ledger(args.db)
    try:
        for line in sys.stdin:
            if line.strip():
                q = json.loads(line)
                event = ingest(
                    db, c, digest, q, q["ts"] if args.replay else int(time.time())
                )
                if event:
                    print(json.dumps(event), flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
