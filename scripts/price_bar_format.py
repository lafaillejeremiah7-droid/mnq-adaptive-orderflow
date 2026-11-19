"""Pure, offline CME OHLC record-to-price-ticks conversion for historical replay.

No network calls, subscriptions, keys, or live streaming in this module.
"""
from decimal import Decimal

NANOS_PER_TICK = Decimal(250_000_000)
NANOS_PER_MINUTE = 60_000_000_000


def format_ohlcv(record) -> str | None:
    """Convert a historical Databento 1-minute bar to timestamp/OHLC tick CSV.

    Returns None for non-OHLCV metadata records. Databento prices use
    fixed-point integers with 1e-9 precision.
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
            raise ValueError(f"Invalid non-quarter-point {field} price")
        prices.append(int(ticks))
    o, h, l, c = prices
    if not (l <= o <= h and l <= c <= h):
        raise ValueError("Inconsistent historical OHLC prices")
    return ",".join(str(x) for x in (timestamp_ns // 1_000_000, *prices))
