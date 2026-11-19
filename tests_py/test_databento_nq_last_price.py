"""Offline, read-only tests for NQ futures last-price adapter."""

from contextlib import redirect_stdout
import io
from types import SimpleNamespace
import unittest

from scripts.databento_nq_last_price import (
    LatestNQQuote,
    SECOND_NS,
    TICK_NANOS,
    format_quote,
)


def bar(second=10, close_ticks=100000):
    return SimpleNamespace(
        ts_event=second * SECOND_NS,
        close=close_ticks * int(TICK_NANOS),
    )


class LatestNQQuoteTests(unittest.TestCase):
    def test_price_and_end_of_second_timestamp(self):
        self.assertEqual(format_quote(bar()), "11000,100000")

    def test_discard_non_ohlcv_records(self):
        self.assertIsNone(format_quote(SimpleNamespace(message="system")))

    def test_non_tick_price_rejected(self):
        record = bar()
        record.close += int(TICK_NANOS // 2)
        with self.assertRaises(ValueError):
            format_quote(record)

    def test_bad_timestamp_rejected(self):
        record = bar()
        record.ts_event += 1
        with self.assertRaises(ValueError):
            format_quote(record)

    def test_monotonic_updates_and_halt(self):
        writer = LatestNQQuote()
        output = io.StringIO()
        with redirect_stdout(output):
            writer(bar(10))
            writer(bar(11, 100001))
            with self.assertRaises(RuntimeError):
                writer(bar(11))
            with self.assertRaises(RuntimeError):
                writer(bar(12))
        self.assertTrue(writer.halted)
        self.assertEqual(output.getvalue().splitlines(), [
            "11000,100000", "12000,100001"
        ])

    def test_provider_error_halts(self):
        writer = LatestNQQuote()
        with self.assertRaises(RuntimeError):
            writer(SimpleNamespace(err="entitlement not available"))
        self.assertTrue(writer.halted)


if __name__ == "__main__":
    unittest.main()
