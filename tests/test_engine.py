import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from mnq_flow import Bar, Trade, absorption_proxy, analyze, load_trades, volume_profile

def trade(day, minute, tick, size, side):
    ts = datetime.fromisoformat(day + "T14:30:00+00:00") + timedelta(minutes=minute)
    return Trade(ts, tick, size, side)

class EngineTests(unittest.TestCase):
    def test_poc_value_area(self):
        p = volume_profile({400: 10, 401: 50, 402: 20, 403: 20})
        self.assertEqual((p["poc"], p["val"], p["vah"]), (100.25, 100.25, 100.5))
        self.assertGreaterEqual(p["value_area_fraction"], 0.70)

    def test_tie_breaks_lower(self):
        self.assertEqual(volume_profile({400: 10, 404: 10})["poc"], 100.0)

    def test_csv_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prints.csv"
            for price, side in (("20100.10", "B"), ("20100.25", "?")):
                path.write_text("timestamp,price,size,side\n" +
                                "2026-11-12T14:30:00Z," + price + ",2," + side + "\n")
                with self.assertRaises(ValueError):
                    load_trades(path)

    def test_mixed_expiries_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prints.csv"
            path.write_text("timestamp,price,size,side,contract\n"
                            "2026-11-12T14:30:00Z,20100.00,2,B,MNQZ26\n"
                            "2026-11-12T14:31:00Z,20100.25,2,S,MNQH27\n")
            with self.assertRaisesRegex(ValueError, "mixed contracts"):
                load_trades(path)

    def test_cvd_and_closed_timeframes(self):
        trades = [trade("2026-11-12", i, 80000 + i, 2, "B") for i in range(35)]
        snapshots = analyze(trades)
        self.assertEqual(snapshots[0]["rth_cvd"], 2)
        self.assertIsNone(snapshots[0]["five_minute_closed"])
        self.assertIsNone(snapshots[0]["fifteen_minute_closed"])
        at_15 = next(s for s in snapshots if s["asof"].endswith("09:45:00-05:00"))
        self.assertEqual(at_15["rth_cvd"], 30)
        self.assertIsNotNone(at_15["fifteen_minute_closed"])
        self.assertEqual(snapshots[-1]["asof"][-14:], "10:04:00-05:00")

    def test_cvd_resets_next_day(self):
        snapshots = analyze([
            trade("2026-11-12", 0, 80000, 3, "B"),
            trade("2026-11-12", 1, 80001, 1, "B"),
            trade("2026-11-13", 0, 80000, 4, "S"),
            trade("2026-11-13", 1, 80000, 1, "S"),
        ])
        self.assertEqual([s["rth_cvd"] for s in snapshots], [3, -4])

    def test_no_future_leak(self):
        base = [trade("2026-11-12", i, 80000 + i, 2, "B") for i in range(35)]
        before = analyze(base)
        after = analyze(base + [
            trade("2026-11-12", 35+i, 90000, 500, "S") for i in range(12)
        ])
        self.assertEqual(before, after[:len(before)])

    def test_absorption_uses_prior_baseline(self):
        day = datetime.fromisoformat("2026-11-12T09:30:00-05:00")
        hist = []
        for i in range(10):
            b = Bar(day + timedelta(minutes=i), 1, 100, 104, 100, 102)
            b.levels = {100: [0, 2], 104: [2, 0]}
            b.buy = b.sell = 2
            hist.append(b)
        b = Bar(day + timedelta(minutes=10), 1, 100, 104, 100, 104)
        b.levels = {100: [0, 20], 104: [2, 0]}
        b.buy, b.sell = 2, 20
        self.assertTrue(absorption_proxy(b, hist)["bullish"])
        self.assertFalse(absorption_proxy(b, hist[:5])["ready"])

if __name__ == "__main__":
    unittest.main()
