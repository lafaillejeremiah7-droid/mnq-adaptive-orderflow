"""Databento GLBX.MDP3 price-only bridge for the MNQ quant research agent.

Writes one CSV row per completed, 1-minute OHLC bar:
timestamp_ms,open_ticks,high_ticks,low_ticks,close_ticks

Does NOT request aggressor delta, volume profiles, book depth or order flow.
Requires a paid/authorized Databento CME live entitlement and an API key.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
import os
import sys

NANOS_PER_TICK = Decimal(250_000_000)  # 0.25 index points, DBN fixed 1e-9
NANOS_PER_MINUTE = 60_000_000_000


def format_ohlcv(record) -> str | None:
    """Convert one Databento OHLCV record to price-only tick CSV.

    Returns None for symbol mappings and other non-OHLCV records.
    The SDK stores prices as fixed-point integers in 1e-9 units.
    """
    fields = ("ts_event", "open", "high", "low", "close")
    if any(not hasattr(record, field) for field in fields):
        return None

    timestamp_ns = int(record.ts_event)
    if timestamp_ns < 0 or timestamp_ns % NANOS_PER_MINUTE:
        raise ValueError("Bar event timestamp must be aligned to one minute")

    prices = []
    for field in ("open", "high", "low", "close"):
        raw = int(getattr(record, field))
        ticks = Decimal(raw) / NANOS_PER_TICK
        if not ticks.is_finite() or ticks <= 0 or ticks != ticks.to_integral_value():
            raise ValueError(f"Invalid or non-MNQ-tick-aligned {field} price")
        prices.append(int(ticks))

    o, h, l, c = prices
    if not (l <= o <= h and l <= c <= h):
        raise ValueError("Inconsistent OHLC prices")

    return ",".join(str(x) for x in (timestamp_ns // 1_000_000, *prices))


class BarPrinter:
    """Fail closed on nonconsecutive or duplicate bars, including roll breaks."""

    def __init__(self) -> None:
        self.last_start_ms: int | None = None
        self.halted = False

    def __call__(self, record) -> None:
        if self.halted:
            raise RuntimeError("Price feed is halted; restart and backfill")
        try:
            if hasattr(record, "err"):
                raise RuntimeError("Provider data error: " + str(record.err))
            # Code 2 is a slow-reader warning: don't risk losing price bars.
            if hasattr(record, "msg") and getattr(record, "code", None) == 2:
                raise RuntimeError("Provider reports a slow reader; data unsafe")
            line = format_ohlcv(record)
            if line is None:
                return
            ts_ms = int(line.split(",", 1)[0])
            if self.last_start_ms is not None and ts_ms != self.last_start_ms + 60_000:
                raise RuntimeError(
                    "Missing, duplicate or out-of-order minute: stop and backfill; "
                    "do not reuse stale quantitative state"
                )
            self.last_start_ms = ts_ms
            print(line, flush=True)
        except Exception:
            # An SDK callback exception must never allow a later bar through.
            self.halted = True
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent MNQ price-only live bar bridge")
    parser.add_argument(
        "--symbol",
        default="MNQ.c.0",
        help="One continuous futures instrument, e.g. MNQ.c.0 or NQ.c.0",
    )
    args = parser.parse_args()

    if args.symbol not in {"MNQ.c.0", "NQ.c.0"}:
        parser.error("Only one MNQ.c.0 or NQ.c.0 futures price stream is supported")

    api_key = os.environ.get("DATABENTO_API_KEY", "").strip()
    if not api_key:
        print("Missing DATABENTO_API_KEY; no live prices available", file=sys.stderr)
        return 2

    try:
        import databento as db
    except ImportError:
        print("Install with: python3 -m pip install databento", file=sys.stderr)
        return 2

    client = db.Live(key=api_key)
    client.subscribe(
        dataset="GLBX.MDP3",
        schema="ohlcv-1m",
        stype_in="continuous",
        symbols=args.symbol,
    )
    client.add_callback(BarPrinter())
    print(
        f"Subscribed to {args.symbol} CME 1-minute PRICE bars; "
        "continuous mappings do not automatically roll while connected. "
        "Restart/re-warm after rollover, network loss or market-data gaps.",
        file=sys.stderr,
        flush=True,
    )
    client.start()
    client.block_for_close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"STOP: live data unavailable/invalid: {exc}", file=sys.stderr)
        sys.exit(1)
