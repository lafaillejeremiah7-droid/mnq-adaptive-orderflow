"""Live NQ futures LAST PRICE only (independent of Tradovate).

Uses licensed Databento CME 1-second OHLCV. Only the close price is used:
no delta, volume profile, aggressor side, or buying/selling pressure.
Writes UTC end-of-bar timestamp and 0.25-point price ticks to stdout.

This tracks NQ futures, NOT the NDX cash index. The latest update is no
more frequent than once per second. Requires your own entitled API key.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

TICK_NANOS = Decimal(250_000_000)
SECOND_NS = 1_000_000_000


def format_quote(record) -> str | None:
    if not (hasattr(record, "close") and hasattr(record, "ts_event")):
        return None
    stamp_ns = int(record.ts_event)
    if stamp_ns < 0 or stamp_ns % SECOND_NS != 0:
        raise ValueError("Invalid, non-second-aligned CME quote timestamp")
    value = Decimal(int(record.close)) / TICK_NANOS
    if not value.is_finite() or value <= 0 or value != value.to_integral_value():
        raise ValueError("Invalid NQ price or CME quarter-point tick alignment")
    price_ticks = int(value)
    if price_ticks > 1_000_000:
        raise ValueError("Price out of supported range")
    # Databento timestamps an OHLCV record at the START of its interval.
    # The close price was established at the END of this one-second bar.
    return f"{(stamp_ns + SECOND_NS) // 1_000_000},{price_ticks}"


class LatestNQQuote:
    def __init__(self):
        self.last_ms = None
        self.halted = False

    def __call__(self, record):
        if self.halted:
            raise RuntimeError("NQ quote feed halted; restart the feed")
        try:
            if hasattr(record, "err"):
                raise RuntimeError(f"CME market-data provider error: {record.err}")
            result = format_quote(record)
            if result is None:
                return
            as_of_ms = int(result.split(",", 1)[0])
            if self.last_ms is not None and as_of_ms <= self.last_ms:
                raise RuntimeError("Duplicate or out-of-order NQ price update")
            self.last_ms = as_of_ms
            print(result, flush=True)
        except Exception:
            self.halted = True
            raise


def main() -> int:
    key = os.environ.get("DATABENTO_API_KEY", "").strip()
    if not key:
        print(
            "NOT CONNECTED: DATABENTO_API_KEY is missing. "
            "Real-time CME data entitlement is also required.",
            file=sys.stderr,
        )
        return 2
    try:
        import databento as db
    except ImportError:
        print("Install the provider SDK: python3 -m pip install databento", file=sys.stderr)
        return 2

    client = db.Live(key=key)
    client.subscribe(
        dataset="GLBX.MDP3",
        schema="ohlcv-1s",
        stype_in="continuous",
        symbols="NQ.c.0",
    )
    client.add_callback(LatestNQQuote())
    print(
        "NQ FUTURES price-only feed subscribed. Price updates at most once "
        "per second; closed/quiet sessions may have no prints. "
        "Continuous symbols do not auto-remap mid-subscription on rollover.",
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
        print(f"FEED STOPPED: {exc}", file=sys.stderr)
        sys.exit(1)
