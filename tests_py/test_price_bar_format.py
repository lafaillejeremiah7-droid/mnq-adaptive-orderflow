"""Offline tests for historical OHLC price conversion.

No internet, live subscription, or brokerage account needed.
"""
from types import SimpleNamespace
import unittest

from scripts.price_bar_format import format_ohlcv, NANOS_PER_MINUTE, NANOS_PER_TICK

TICK = int(NANOS_PER_TICK)
MIN = NANOS_PER_MINUTE


def bar(minute=5, opening=80000, high=80010, low=79995, close=80005):
    return SimpleNamespace(
        ts_event=int(minute * MIN),
        open=opening * TICK,
        high=high * TICK,
        low=low * TICK,
        close=close * TICK,
    )


class OfflinePriceBarTests(unittest.TestCase):
    def test_historical_csv_output(self):
        self.assertEqual(
            format_ohlcv(bar()),
            "300000,80000,80010,79995,80005",
        )

    def test_ignore_non_price_bar_records(self):
        self.assertIsNone(format_ohlcv(SimpleNamespace(ts_event=int(5 * MIN))))

    def test_reject_fractional_tick(self):
        record = bar()
        record.close += TICK // 2
        with self.assertRaises(ValueError):
            format_ohlcv(record)

    def test_reject_non_minute_aligned_timestamp(self):
        record = bar()
        record.ts_event += 1
        with self.assertRaises(ValueError):
            format_ohlcv(record)

    def test_reject_invalid_range(self):
        with self.assertRaises(ValueError):
            format_ohlcv(bar(close=80011))

    def test_reject_negative_prices(self):
        with self.assertRaises(ValueError):
            format_ohlcv(bar(opening=-1))

    def test_reject_negative_timestamp(self):
        with self.assertRaises(ValueError):
            format_ohlcv(bar(minute=-1))


if __name__ == "__main__":
    unittest.main()
