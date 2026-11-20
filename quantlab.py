"""An auditable, one-contract NQ/MNQ one-minute research runner."""
import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

TICK_CENTS = {"NQ": 500, "MNQ": 50}
MINUTE = timedelta(minutes=1)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:00Z", value):
        raise ValueError("expected a UTC minute in YYYY-MM-DDTHH:MM:00Z form")
    return datetime.fromisoformat(value[:-1]).replace(tzinfo=timezone.utc)


def check_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} needs text")


def check_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", value):
        raise ValueError("invalid experiment id")
    return value


def validate(s):
    required = """id hypothesis failure_reason data_source data_kind data_sha256 instrument contract
    start end direction min_body_ticks stop_ticks target_ticks fee_cents slippage_ticks_per_side
    min_trades min_net_cents max_drawdown_cents""".split()
    if not isinstance(s, dict) or set(s) != set(required):
        raise ValueError("spec keys must match the example exactly")
    check_id(s["id"])
    for k in ("hypothesis", "failure_reason", "data_source"):
        check_text(s[k], k)
    if s["data_kind"] not in ("synthetic", "historical") or not re.fullmatch("[0-9a-f]{64}", s["data_sha256"]):
        raise ValueError("invalid data provenance")
    if s["instrument"] not in TICK_CENTS or not re.fullmatch(s["instrument"] + r"[HMUZ][0-9]{1,4}", s["contract"]):
        raise ValueError("expected a single outright quarterly contract")
    if timestamp(s["end"]) <= timestamp(s["start"]):
        raise ValueError("invalid evaluation window")
    if s["direction"] not in ("follow", "fade"):
        raise ValueError("direction must be follow or fade")
    for k in required[11:]:
        minimum = 1 if k in ("min_body_ticks", "stop_ticks", "target_ticks", "min_trades") else 0
        if type(s[k]) is not int or s[k] < minimum:
            raise ValueError(f"invalid nonnegative integer or positive threshold for {k}")


def ticks(value):
    price = Decimal(value)
    if not price.is_finite() or price <= 0 or price > 10000000 or price % Decimal(".25"):
        raise ValueError("expected a positive exchange tick price")
    return int(price * 4)


def backtest(s, raw):
    if digest(raw) != s["data_sha256"]:
        raise ValueError("data checksum changed")
    start, end = timestamp(s["start"]), timestamp(s["end"])
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if reader.fieldnames != ["timestamp", "contract", "open", "high", "low", "close"]:
        raise ValueError("unexpected CSV schema")
    trades = []
    bars = gaps = equity = peak = drawdown = 0
    last_time = previous = None
    for row in reader:
        now = timestamp(row["timestamp"])
        if last_time is not None and now <= last_time:
            raise ValueError("bars must be strictly increasing")
        last_time = now
        if row["contract"] != s["contract"] or None in row:
            raise ValueError("unexpected contract or CSV field")
        o, h, l, c = (ticks(row[k]) for k in ("open", "high", "low", "close"))
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError("inconsistent OHLC")
        if not start <= now < end:
            continue
        bars += 1
        if previous:
            prior_time, body = previous
            if now - prior_time != MINUTE:
                gaps += 1
            elif abs(body) >= s["min_body_ticks"]:
                side = (1 if body > 0 else -1) * (1 if s["direction"] == "follow" else -1)
                favorable, adverse = (h-o, o-l) if side == 1 else (o-l, h-o)
                hit_stop = adverse >= s["stop_ticks"]
                hit_target = favorable >= s["target_ticks"]
                if hit_stop:
                    gain, exit_reason = -s["stop_ticks"], "stop"
                elif hit_target:
                    gain, exit_reason = s["target_ticks"], "target"
                else:
                    gain, exit_reason = side * (c-o), "close"
                tick_value = TICK_CENTS[s["instrument"]]
                cost = s["fee_cents"] + 2 * s["slippage_ticks_per_side"] * tick_value
                net = gain * tick_value - cost
                equity += net
                peak = max(peak, equity)
                drawdown = max(drawdown, peak - equity)
                trades.append(dict(signal_time=prior_time.isoformat(), entry_time=row["timestamp"],
                                   side=side, entry_ticks=o, exit_ticks=o+side*gain,
                                   exit_reason=exit_reason, ambiguous=hit_stop and hit_target,
                                   gross_cents=gain*tick_value, cost_cents=cost, net_cents=net))
        previous = now, c-o
    if not bars:
        raise ValueError("no evaluation bars")
    passed = len(trades) >= s["min_trades"] and equity >= s["min_net_cents"] and drawdown <= s["max_drawdown_cents"]
    gross = sum(t["gross_cents"] for t in trades)
    costs = sum(t["cost_cents"] for t in trades)
    tick_value = TICK_CENTS[s["instrument"]]
    ambiguous = sum(t["ambiguous"] for t in trades)
    daily = {}
    for trade in trades:
        day = trade["entry_time"][:10]
        daily[day] = daily.get(day, 0) + trade["net_cents"]
    return dict(bars=bars, gaps=gaps, trades=trades, trade_count=len(trades),
                daily_net_cents_utc=daily, gross_cents=gross, cost_cents=costs,
                flat_cash_benchmark_cents=0,
                extra_tick_each_side_net_cents=equity - 2*tick_value*len(trades),
                target_first_sensitivity_cents=equity + ambiguous*(s["target_ticks"]+s["stop_ticks"])*tick_value,
                ambiguous_bars=ambiguous, net_cents=equity,
                closed_trade_drawdown_cents=drawdown, met_registered_thresholds=passed)


def save(path, obj):
    # Publish a complete file without overwriting an existing event.
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        name = Path(temp.name)
        try:
            temp.write(encoded(obj))
            temp.flush()
            os.fsync(temp.fileno())
        except BaseException:
            name.unlink()
            raise
    try:
        os.link(name, path)
    finally:
        name.unlink()


def read(path):
    return json.loads(path.read_bytes())


def stamp():
    return datetime.now(timezone.utc).isoformat()


def execute(args):
    root = args.ledger
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        engine = digest(Path(__file__).read_bytes())
        if args.action == "register":
            s = read(args.spec)
            validate(s)
            folder = root / s["id"]
            folder.mkdir(exist_ok=True)
            save(folder/"protocol.json", dict(registered=stamp(), engine_sha256=engine, spec=s))
            return {"registered": s["id"]}
        folder = root / check_id(args.id)
        protocol = read(folder/"protocol.json")
        s = protocol["spec"]
        validate(s)
        if args.action == "review":
            result = read(folder/"result.json")
            review = read(args.file)
            if not isinstance(review, dict) or set(review) != {"reviewer","verdict","findings","result_sha256"}:
                raise ValueError("invalid review fields")
            if review["verdict"] not in ("reject","request_changes","retain_for_paper"):
                raise ValueError("invalid verdict")
            for k in ("reviewer","findings"):
                check_text(review[k], k)
            if review["result_sha256"] != digest((folder/"result.json").read_bytes()):
                raise ValueError("review refers to a different result")
            if review["verdict"] == "retain_for_paper" and (not result["met_registered_thresholds"] or s["data_kind"] != "historical"):
                raise ValueError("retention requires historical provenance and passing thresholds")
            save(folder/"review.json", dict(reviewed=stamp(), **review))
            return {"recorded":review["verdict"]}
        if protocol["engine_sha256"] != engine:
            raise ValueError("run with the registered engine revision")
        raw = args.data.read_bytes()
        if args.action == "replay":
            actual = backtest(s,raw)
            if encoded(actual) != (folder/"result.json").read_bytes():
                raise ValueError("replay mismatch")
            return {"verified":digest(encoded(actual))}
        # Reserve before evaluating so even interrupted or invalid runs leave evidence.
        for marker in root.glob("*/started.json"):
            other = read(marker.parent/"protocol.json")["spec"]
            if other["contract"] == s["contract"] and other["start"] < s["end"] and s["start"] < other["end"]:
                raise ValueError(f"evaluation window already used by {other['id']}")
        save(folder/"started.json", {"started":stamp()})
        try:
            result = backtest(s,raw)
            save(folder/"result.json", result)
        except Exception as e:
            save(folder/"failed.json", {"error":str(e)})
            raise
        return {k:v for k,v in result.items() if k != "trades"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=Path("experiments"))
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("register").add_argument("spec", type=Path)
    for action in ("run","replay","review"):
        cmd = commands.add_parser(action)
        cmd.add_argument("id")
        cmd.add_argument("file" if action=="review" else "data", type=Path)
    try:
        print(json.dumps(execute(parser.parse_args()), indent=2))
    except (OSError, ValueError, TypeError, KeyError, InvalidOperation, csv.Error) as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
