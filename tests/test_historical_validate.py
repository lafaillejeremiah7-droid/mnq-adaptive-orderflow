"""Tests use SMALL SYNTHETIC FIXTURES to verify the engine, not profitability."""
import csv
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from mnq_flow.engine import ET, Trade
from mnq_flow.historical_validate import (
    Session, audit, iter_prints, replay, source_files,
)


def one_print(year, minute, *, contract="MNQM26"):
    ts = datetime(year, 6, 14, 9, 30, tzinfo=ET) + timedelta(minutes=minute)
    return Trade(ts, 80000, 1, "B", contract)


class HistoricalAuditTests(unittest.TestCase):
    def test_ohlcv_rejected_not_interpreted_as_signed_flow(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "ohlcv.csv"
            file.write_text("timestamp,open,high,low,close,volume\n"
                            "2023-06-14T09:30:00-04:00,1,2,1,2,10\n")
            with self.assertRaisesRegex(ValueError, "OHLCV"):
                list(iter_prints([file]))

    def test_bid_ask_quotes_without_executed_aggressor_side_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "quotes.csv"
            file.write_text("timestamp,price,size,side,contract\n"
                            "2023-06-14T09:30:00-04:00,20000,1,UNKNOWN,MNQM23\n")
            with self.assertRaisesRegex(ValueError, "aggressor side"):
                list(iter_prints([file]))

    def test_non_utc_timestamps_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "naive.csv"
            file.write_text("timestamp,price,size,side,contract\n"
                            "2023-06-14T09:30:00,20000,1,B,MNQM23\n")
            with self.assertRaisesRegex(ValueError, "UTC offset"):
                list(iter_prints([file]))

    def test_mixed_contract_in_session_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "mixed.csv"
            file.write_text("timestamp,price,size,side,contract\n"
                            "2023-06-14T09:30:00-04:00,20000,1,B,MNQM23\n"
                            "2023-06-14T09:31:00-04:00,20000,1,S,MNQU23\n")
            with self.assertRaisesRegex(ValueError, "Mixed contract"):
                list(iter_prints([file]))

    def test_gapped_rth_session_not_complete(self):
        row = Session()
        for minute in range(390):
            if minute != 35:
                row.add(one_print(2023, minute))
        self.assertFalse(row.complete)

    def test_full_rth_session_complete(self):
        row = Session()
        for minute in range(386):
            row.add(one_print(2023, minute))
        self.assertTrue(row.complete)

    def test_consecutive_three_year_requirement(self):
        rows = [one_print(y, m, contract=f"MNQM{y % 100:02d}")
                for y in (2021, 2022, 2023) for m in range(386)]
        with patch("mnq_flow.historical_validate.iter_prints", return_value=iter(rows)):
            with patch("mnq_flow.historical_validate.MIN_SESSIONS_YEAR", 1):
                info, selected = audit([Path("simulated_never_report_as_real.csv")], 3)
        self.assertEqual(info["status"], "COVERAGE_VERIFIED_SCHEMA_ONLY")
        self.assertEqual(info["selected_years"], [2021, 2022, 2023])
        self.assertEqual(len(selected), 3)

    def test_gap_in_calendar_year_blocks(self):
        rows = [one_print(y, m, contract=f"MNQM{y % 100:02d}")
                for y in (2021, 2023, 2025) for m in range(386)]
        with patch("mnq_flow.historical_validate.iter_prints", return_value=iter(rows)):
            with patch("mnq_flow.historical_validate.MIN_SESSIONS_YEAR", 1):
                info, selected = audit([Path("synthetic.csv")], 3)
        self.assertEqual(info["status"], "BLOCKED_HISTORY_INCOMPLETE")
        self.assertFalse(selected)

    def test_no_archive_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "No genuine"):
                source_files(Path(temp))

    def test_no_backtest_without_valid_years(self):
        with self.assertRaisesRegex(ValueError, "coverage gate"):
            replay([], set(), commission=__import__("decimal").Decimal("2.5"),
                   slippage=1, reward_multiple=__import__("decimal").Decimal("2"))


if __name__ == "__main__":
    unittest.main()
