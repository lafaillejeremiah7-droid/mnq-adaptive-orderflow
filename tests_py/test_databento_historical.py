"""Offline tests for historical price-only importer. No paid calls."""

import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from scripts.databento_historical_prices import parse_dates, write_price_rows

TICK = 250_000_000
MINUTE_NS = 60_000_000_000


def bar(minute, price=80000):
    return SimpleNamespace(
        ts_event=minute * MINUTE_NS,
        open=price * TICK,
        high=(price + 3) * TICK,
        low=(price - 3) * TICK,
        close=(price + 1) * TICK,
    )


class HistoryTests(unittest.TestCase):
    def test_dates_and_cost_window(self):
        first, last = parse_dates("2026-10-01", "2026-10-08")
        self.assertEqual((last - first).days, 7)
        for a, b in (
            ("2026-10-01", "2026-10-10"),
            ("2026-10-08", "2026-10-01"),
            ("2026-10-01", "2026-10-01"),
            ("2026-13-01", "2026-13-02"),
            ("2030-01-01", "2030-01-02"),
        ):
            with self.subTest(a=a, b=b), self.assertRaises(ValueError):
                parse_dates(a, b)

    def test_writes_genuine_gaps_without_filling(self):
        with tempfile.TemporaryDirectory() as root:
            dst = Path(root) / "mnq.csv"
            count = write_price_rows([bar(10), bar(11), bar(20)], dst)
            self.assertEqual(count, 3)
            rows = dst.read_text(encoding="utf-8").splitlines()
            self.assertEqual([int(x.split(",")[0]) for x in rows], [
                600000, 660000, 1200000
            ])
            with self.assertRaises(FileExistsError):
                write_price_rows([bar(21)], dst)
            self.assertEqual(len(dst.read_text().splitlines()), 3)

    def test_out_of_order_not_published(self):
        with tempfile.TemporaryDirectory() as root:
            dst = Path(root) / "invalid.csv"
            with self.assertRaises(ValueError):
                write_price_rows([bar(20), bar(19)], dst)
            self.assertFalse(dst.exists())
            with self.assertRaises(ValueError):
                write_price_rows([bar(20), bar(20)], dst)
            self.assertFalse(dst.exists())

    def test_empty_historical_response(self):
        with tempfile.TemporaryDirectory() as root:
            dst = Path(root) / "empty.csv"
            with self.assertRaises(ValueError):
                write_price_rows([], dst)
            self.assertFalse(dst.exists())

    def test_invalid_price_rejected_without_file(self):
        with tempfile.TemporaryDirectory() as root:
            dst = Path(root) / "bad.csv"
            bad = bar(40)
            bad.close += TICK // 2
            with self.assertRaises(ValueError):
                write_price_rows([bar(39), bad], dst)
            self.assertFalse(dst.exists())


if __name__ == "__main__":
    unittest.main()
