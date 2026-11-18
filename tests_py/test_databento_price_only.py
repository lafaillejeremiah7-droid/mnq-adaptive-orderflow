"""Offline tests: no Databento credentials, network or SDK required."""

import io
from contextlib import redirect_stdout
from types import SimpleNamespace
import unittest

from scripts.databento_price_only import BarPrinter, format_ohlcv

M = 60_000_000_000
T = 250_000_000


def record(minute=5, opening=80000, high=80010, low=79995, close=80005):
    return SimpleNamespace(
        ts_event=minute * M,
        open=opening * T,
        high=high * T,
        low=low * T,
        close=close * T,
    )


class PriceOnlyTests(unittest.TestCase):
    def test_standard_minute(self):
        self.assertEqual(
            format_ohlcv(record()),
            "300000,80000,80010,79995,80005",
        )

    def test_ignore_non_bars(self):
        self.assertIsNone(format_ohlcv(SimpleNamespace(ts_event=5 * M)))

    def test_reject_subtick_price(self):
        candle = record()
        candle.close += T // 2
        with self.assertRaises(ValueError):
            format_ohlcv(candle)

    def test_reject_misaligned_minute(self):
        with self.assertRaises(ValueError):
            format_ohlcv(record(minute=5.5))

    def test_reject_inconsistent_prices(self):
        with self.assertRaises(ValueError):
            format_ohlcv(record(close=80011))

    def test_fail_closed_on_gap_and_duplicate(self):
        printer = BarPrinter()
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            printer(record(minute=5))
            printer(record(minute=6))
            with self.assertRaises(RuntimeError):
                printer(record(minute=8))
            with self.assertRaises(RuntimeError):
                printer(record(minute=6))
        self.assertEqual(buffer.getvalue().count("\n"), 2)


if __name__ == "__main__":
    unittest.main()
