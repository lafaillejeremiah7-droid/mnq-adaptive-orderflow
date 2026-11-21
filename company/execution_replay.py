"""Conservative OFFLINE NQ/MNQ top-of-book market-order cost scenarios.

Inputs are verified *against declared bytes and ordering*, not authenticated
exchange quotes. A quote known at simulated arrival provides a bounded cost
scenario ONLY, not proof of an executable fill, limit queue, or profitable edge.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from company.market_profile import CONTRACT

NANO = 1_000_000_000
FIRST_NS = 946684800 * NANO
LAST_NS = 4102444800 * NANO
FIELDS = ("ts_event_ns", "ts_recv_ns", "contract", "bid_ticks",
          "bid_size", "ask_ticks", "ask_size", "sequence")
SPEC_FIELDS = frozenset({
    "contract", "source_sha256", "source_kind", "provider",
    "schema", "rights_status", "fees_per_contract_usd",
    "conservative_slippage_ticks", "max_quote_age_ns",
    "max_spread_ticks", "max_records",
})
ORDER_FIELDS = frozenset({"decision_ns", "side", "contracts", "latency_ns"})
TICK_USD = {"NQ": Decimal("5.00"), "MNQ": Decimal("0.50")}


@dataclass(frozen=True)
class Quote:
    event: int
    received: int
    bid: int
    bid_size: int
    ask: int
    ask_size: int
    sequence: int


def _int(value, name, low=0, high=10**20):
    if type(value) is str:
        if re.fullmatch(r"[0-9]+", value) is None:
            raise ValueError("invalid unsigned integer " + name)
        number = int(value)
    elif type(value) is int:
        number = value
    else:
        raise ValueError("invalid integer type for " + name)
    if not low <= number <= high:
        raise ValueError("out-of-range integer " + name)
    return number


def _money(value):
    if type(value) not in (str, int, float):
        raise ValueError("invalid fee")
    try:
        fee = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid fee") from exc
    if not fee.is_finite() or not 0 <= fee <= Decimal("100"):
        raise ValueError("fee out of range")
    return fee


def validate_spec(spec):
    if not isinstance(spec, dict) or set(spec) != SPEC_FIELDS:
        raise ValueError("quote-replay specification missing/extra fields")
    if not isinstance(spec["contract"], str) or CONTRACT.fullmatch(spec["contract"]) is None:
        raise ValueError("invalid quarterly contract")
    if spec["source_kind"] not in ("synthetic", "historical"):
        raise ValueError("invalid source kind")
    if spec["schema"] != "top_of_book_v1":
        raise ValueError("only normalized top-of-book quote schema is supported")
    if not isinstance(spec["provider"], str) or not spec["provider"].strip():
        raise ValueError("source provider required")
    if spec["rights_status"] not in ("unverified", "documented"):
        raise ValueError("invalid declared rights")
    if not isinstance(spec["source_sha256"], str) or re.fullmatch(
        r"[0-9a-f]{64}", spec["source_sha256"]
    ) is None:
        raise ValueError("invalid quote SHA-256")
    _money(spec["fees_per_contract_usd"])
    for field, low, high in (
        ("conservative_slippage_ticks", 0, 100),
        ("max_quote_age_ns", 1, 60 * NANO),
        ("max_spread_ticks", 1, 1000),
        ("max_records", 1, 5_000_000),
    ):
        if type(spec[field]) is not int:
            raise ValueError("invalid configuration integer " + field)
        _int(spec[field], field, low, high)


def read_quotes(raw, spec):
    validate_spec(spec)
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != spec["source_sha256"]:
        raise ValueError("quote source SHA-256 mismatch")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    except UnicodeError as exc:
        raise ValueError("quote CSV must be UTF-8") from exc
    if reader.fieldnames != list(FIELDS):
        raise ValueError("quote CSV columns must match normalized top-of-book schema")
    records = []
    previous = None
    for row in reader:
        if len(records) >= spec["max_records"]:
            raise ValueError("quote row limit exceeded; partition by contract/session")
        if set(row) != set(FIELDS) or any(v is None for v in row.values()):
            raise ValueError("malformed quote row")
        if row["contract"] != spec["contract"]:
            raise ValueError("quote contract mismatch; no mixed NQ/MNQ")
        event = _int(row["ts_event_ns"], "ts_event_ns", FIRST_NS, LAST_NS - 1)
        received = _int(row["ts_recv_ns"], "ts_recv_ns", FIRST_NS, LAST_NS - 1)
        if received < event:
            raise ValueError("quote receive time is earlier than event; invalid clock alignment")
        bid = _int(row["bid_ticks"], "bid_ticks", 1, 100_000_000)
        ask = _int(row["ask_ticks"], "ask_ticks", 1, 100_000_000)
        bs = _int(row["bid_size"], "bid_size", 1, 10_000_000)
        az = _int(row["ask_size"], "ask_size", 1, 10_000_000)
        seq = _int(row["sequence"], "sequence", 0, 2**64 - 1)
        if bid >= ask:
            raise ValueError("locked or crossed top of book")
        key = (received, seq)
        if previous is not None and key <= previous:
            raise ValueError("quote receive times/sequences must strictly increase")
        previous = key
        records.append(Quote(event, received, bid, bs, ask, az, seq))
    if not records:
        raise ValueError("no top-of-book observations")
    return records


def simulate(raw_quotes, spec, intentions):
    """Sample the most recent *received* quote at each delayed arrival.

    No inference of actual fill, queue priority, deeper liquidity, market
    impact, cancels or exchange state from a level-one snapshot.
    """
    quotes = read_quotes(raw_quotes, spec)
    if not isinstance(intentions, list) or not 1 <= len(intentions) <= 100000:
        raise ValueError("expect 1-100000 simulation intentions")
    symbol = "MNQ" if spec["contract"].startswith("MNQ") else "NQ"
    value = TICK_USD[symbol]
    recv_times = [q.received for q in quotes]
    consumed = {}
    events = []
    prior = -1
    for order in intentions:
        if not isinstance(order, dict) or set(order) != ORDER_FIELDS:
            raise ValueError("invalid simulation intention schema")
        decision = _int(order["decision_ns"], "decision_ns", FIRST_NS, LAST_NS - 1)
        if decision < prior:
            raise ValueError("intentions must be ordered by decision time")
        prior = decision
        side = order["side"]
        if side not in ("BUY", "SELL"):
            raise ValueError("only aggressive BUY/SELL scenarios are supported")
        quantity = _int(order["contracts"], "contracts", 1, 1000)
        latency = _int(order["latency_ns"], "latency_ns", 0, 60 * NANO)
        arrival = decision + latency
        ix = bisect.bisect_right(recv_times, arrival) - 1
        base = {
            "decision_ns": decision, "arrival_ns": arrival,
            "side": side, "contracts": quantity,
            "status": "no_simulated_fill", "fill_guaranteed": False,
        }
        if ix < 0:
            base["reason"] = "no_received_quote_by_arrival"
            events.append(base)
            continue
        quote = quotes[ix]
        if arrival - quote.received > spec["max_quote_age_ns"]:
            base["reason"] = "stale_top_of_book"
            events.append(base)
            continue
        spread = quote.ask - quote.bid
        if spread > spec["max_spread_ticks"]:
            base["reason"] = "spread_exceeds_limit"
            events.append(base)
            continue
        displayed = quote.ask_size if side == "BUY" else quote.bid_size
        key = (ix, side)
        remaining = displayed - consumed.get(key, 0)
        if quantity > remaining:
            base["reason"] = "insufficient_unconsumed_displayed_top_size"
            events.append(base)
            continue
        consumed[key] = consumed.get(key, 0) + quantity
        slippage = spec["conservative_slippage_ticks"]
        estimated_tick = quote.ask + slippage if side == "BUY" else quote.bid - slippage
        if estimated_tick <= 0:
            raise ValueError("slippage produces invalid nonpositive execution price")
        half_spread = Decimal(spread) / Decimal(2)
        cost_ticks = half_spread + Decimal(slippage)
        fees = _money(spec["fees_per_contract_usd"]) * quantity
        estimated_cost = Decimal(quantity) * cost_ticks * value + fees
        base.update({
            "status": "hypothetical_market_order_fill",
            "quote_received_ns": quote.received,
            "quote_age_ns": arrival - quote.received,
            "quoted_bid_ticks": quote.bid,
            "quoted_ask_ticks": quote.ask,
            "spread_ticks": spread,
            "displayed_top_size": displayed,
            "assumed_slippage_ticks": slippage,
            "scenario_execution_ticks": estimated_tick,
            "scenario_cost_vs_quoted_mid_usd": str(estimated_cost),
            "scenario_fees_usd": str(fees),
            "reason": "assumed_liquidity_no_queue_or_fill_confirmation",
        })
        events.append(base)
    return {
        "contract": spec["contract"],
        "source_kind": spec["source_kind"],
        "quote_sha256": hashlib.sha256(raw_quotes).hexdigest(),
        "quote_records": len(quotes),
        "simulated_intentions": len(intentions),
        "scenarios_with_assumed_fill": sum(e["status"] == "hypothetical_market_order_fill" for e in events),
        "events": events,
        "model": "latency_delayed_latest_received_bbo_with_explicit_slippage_and_top_size_limit",
        "independent_exchange_authentication": False,
        "actual_exchange_fills_verified": False,
        "resting_limit_order_queue_inferred": False,
        "order_submission_enabled": False,
        "tradable_edge_verified": False,
        "limitations": [
            "A quote snapshot does not guarantee the displayed liquidity survives until an order arrives.",
            "No depth beyond top-of-book, venue acknowledgement, queue, market impact, partial fills or outages.",
            "Constant conservative slippage is a user-specified stress assumption, not a measured bound.",
            "Bid/ask snapshot timestamps and source rights have not been independently authenticated.",
            "This is not a complete execution simulator or a validated estimate of achievable PnL.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--quotes", type=Path, required=True)
    parser.add_argument("--intentions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = simulate(args.quotes.read_bytes(), json.loads(args.spec.read_text()),
                          json.loads(args.intentions.read_text()))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as file:
            json.dump(report, file, indent=2, sort_keys=True)
            file.write("\n")
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, csv.Error) as exc:
        parser.exit(2, "execution scenario rejected: " + str(exc) + "\n")
    print(json.dumps({
        "simulated_intentions": report["simulated_intentions"],
        "scenarios_with_assumed_fill": report["scenarios_with_assumed_fill"],
        "actual_exchange_fills_verified": False,
    }))


if __name__ == "__main__":
    main()
