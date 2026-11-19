"""Offline validation of QQQ wall weights, NQ equivalence and timestamps."""
import csv
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.qqq_option_walls import (
    WallDataError, OptionContract, calculate, load_options,
    wall_levels, validate_snapshots, nq_tick_round, parse_utc,
)

ASOF = "2026-11-18T15:00:00Z"
ROWS = [
    {"expiration": "2026-11-20", "option_type": "call", "strike": "610", "open_interest": "500", "gamma": "0.05"},
    {"expiration": "2026-11-20", "option_type": "call", "strike": "615", "open_interest": "600", "gamma": "0.01"},
    {"expiration": "2026-11-20", "option_type": "put", "strike": "590", "open_interest": "300", "gamma": "0.20"},
    {"expiration": "2026-11-20", "option_type": "put", "strike": "585", "open_interest": "900", "gamma": "0.01"},
    {"expiration": "2026-11-27", "option_type": "call", "strike": "610", "open_interest": "200", "gamma": "0.01"},
    {"expiration": "2026-11-27", "option_type": "put", "strike": "590", "open_interest": "100", "gamma": "0.01"},
]


def make_csv(path, rows=ROWS):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["expiration", "option_type", "strike", "open_interest", "gamma"]
        )
        writer.writeheader()
        writer.writerows(rows)


class WallTests(unittest.TestCase):
    def compute(self, path, metric="gex", expiration="2026-11-20"):
        return calculate(
            path, metric=metric, expiration=expiration, qqq_price="600",
            nq_price="24000", chain_asof=ASOF, qqq_asof=ASOF, nq_asof=ASOF
        )

    def test_gamma_and_oi_walls_are_not_equivalent(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "qqq.csv"
            make_csv(path)
            gamma = self.compute(path)
            self.assertEqual(gamma["call_wall"]["qqq_strike"], "610")
            self.assertEqual(gamma["put_wall"]["qqq_strike"], "590")
            self.assertEqual(gamma["call_wall"]["nq_equivalent_points"], "24400.00")
            self.assertEqual(gamma["put_wall"]["nq_equivalent_points"], "23600.00")
            oi = self.compute(path, metric="oi")
            self.assertEqual(oi["call_wall"]["qqq_strike"], "615")
            self.assertEqual(oi["put_wall"]["qqq_strike"], "585")
            self.assertIn("NOT gamma", oi["interpretation"])

    def test_aggregate_multiple_expirations(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "qqq.csv"
            make_csv(path)
            combined = self.compute(path, expiration=None)
            self.assertEqual(combined["options_contract_count"], 6)
            self.assertEqual(combined["call_wall"]["qqq_strike"], "610")

    def test_rounding_to_nq_tick(self):
        self.assertEqual(nq_tick_round(Decimal("25000.13")), Decimal("25000.25"))
        self.assertEqual(nq_tick_round(Decimal("25000.12")), Decimal("25000.00"))
        wall = wall_levels(
            [OptionContract("2026-11-20", "call", Decimal("610"), 3, Decimal(".1")),
             OptionContract("2026-11-20", "put", Decimal("590"), 2, Decimal(".1"))],
            metric="gex", qqq_reference=Decimal("600"), nq_reference=Decimal("25000.13")
        )
        for side in ("call", "put"):
            points = Decimal(wall[f"{side}_wall"]["nq_equivalent_points"])
            self.assertEqual(points % Decimal(".25"), 0)

    def test_duplicate_option_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "qqq.csv"
            make_csv(path, [ROWS[0], ROWS[0]])
            with self.assertRaisesRegex(WallDataError, "Duplicate"):
                load_options(path)

    def test_missing_gamma_does_not_fall_back_silently(self):
        entries = [
            OptionContract("2026-11-20", "call", Decimal("610"), 100, None),
            OptionContract("2026-11-20", "put", Decimal("590"), 100, Decimal(".1"))
        ]
        with self.assertRaisesRegex(WallDataError, "Missing gamma"):
            wall_levels(entries, metric="gex", qqq_reference=Decimal("600"), nq_reference=Decimal("24000"))

    def test_stale_and_lookahead_snapshots_rejected(self):
        with self.assertRaisesRegex(WallDataError, "apart"):
            validate_snapshots(parse_utc(ASOF), parse_utc(ASOF), parse_utc("2026-11-18T15:07:00Z"))
        with self.assertRaisesRegex(WallDataError, "after options"):
            validate_snapshots(parse_utc("2026-11-18T16:00:00Z"), parse_utc(ASOF), parse_utc(ASOF))
        with self.assertRaisesRegex(WallDataError, "after options"):
            validate_snapshots(parse_utc(ASOF), parse_utc("2026-11-18T16:00:00Z"), parse_utc("2026-11-18T16:00:00Z"))

    def test_nonstandard_multiplier_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "qqq.csv"
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "expiration", "option_type", "strike", "open_interest", "gamma", "multiplier"
                ])
                writer.writeheader()
                writer.writerow({**ROWS[0], "multiplier": "10"})
            with self.assertRaisesRegex(WallDataError, "Non-standard"):
                load_options(path)

    def test_empty_strike_exposure_rejected(self):
        with self.assertRaisesRegex(WallDataError, "No positive"):
            wall_levels(
                [OptionContract("2026-11-20", "call", Decimal("600"), 0, Decimal(".1"))],
                metric="gex", qqq_reference=Decimal("600"), nq_reference=Decimal("24000")
            )

    def test_timestamp_must_be_utc(self):
        with self.assertRaises(WallDataError):
            parse_utc("2026-11-18T15:00:00")
        with self.assertRaises(WallDataError):
            parse_utc("2026-11-18T15:00:00-06:00")


if __name__ == "__main__":
    unittest.main()
