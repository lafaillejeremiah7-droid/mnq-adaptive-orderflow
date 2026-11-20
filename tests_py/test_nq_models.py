import json
from datetime import date, timedelta
from pathlib import Path
import unittest

from projects.nq.models import auction, basis, calibration, dcf, positioning

DATA = Path(__file__).resolve().parents[1] / "projects/nq"


class ResearchProjects(unittest.TestCase):
    def test_dcf_constant_cash_and_sensitivity(self):
        s = dict(
            operating_cash=10,
            cash_capex=0,
            net_borrowing=0,
            shares_millions=1,
            annual_growth=[0, 0],
            terminal_growth=0,
            cost_of_equity=0.1,
        )
        self.assertEqual(dcf(s)["value_per_share"], 100)
        self.assertEqual(dcf(dict(s, cost_of_equity=0.2))["value_per_share"], 50)
        with self.assertRaises(ValueError):
            dcf(dict(s, terminal_growth=0.1))

    def test_basis_expiry(self):
        s = json.loads((DATA / "illustrative-basis.json").read_text())
        self.assertEqual(basis(dict(s, as_of=s["expiry"]))["model_futures"], s["spot"])
        with self.assertRaises(ValueError):
            basis(dict(s, spot=float("nan")))

    def test_auction_direction_and_timing(self):
        s = json.loads((DATA / "illustrative-auction.json").read_text())
        self.assertEqual(auction(s)["observation"], "failed_high")
        reflected = [
            [t, s["val_ticks"] + s["vah_ticks"] - p, "S" if side == "B" else "B", v]
            for t, p, side, v in s["prints"]
        ]
        self.assertEqual(
            auction(dict(s, prints=reflected))["observation"], "failed_low"
        )
        with self.assertRaises(ValueError):
            auction(dict(s, profile_known_ms=s["minute_start_ms"] + 1))
        with self.assertRaises(ValueError):
            auction(dict(s, profile_contract="NQH27"))

    def test_market_code(self):
        with self.assertRaises(ValueError):
            positioning(
                [
                    {
                        "date": "2026-11-10",
                        "market_code": "209747",
                        "open_interest": "100",
                    }
                ]
            )

    def test_score_first_forecast_before_outcome(self):
        start = date(2020, 1, 1)

        def rows(last):
            return [
                dict(observation_date=str(start + timedelta(days=i)), NASDAQ100=str(v))
                for i, v in enumerate([100 + i for i in range(254)] + [last])
            ]

        p = 253 / 254
        self.assertAlmostEqual(
            calibration(rows(1000))["all"]["brier"], (1 - p) ** 2, places=6
        )
        self.assertAlmostEqual(calibration(rows(1))["all"]["brier"], p * p, places=6)
