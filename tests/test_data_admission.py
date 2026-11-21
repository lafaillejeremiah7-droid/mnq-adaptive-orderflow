"""Synthetic admission fixtures; no authentic exchange or licensed data claims."""
import csv
import hashlib
import io
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from company.data_admission import admit_trades
from company import market_profile as mp

NY = ZoneInfo("America/New_York")


def sample(dates=("2026-03-06", "2026-03-09")):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(mp.COLUMNS)
    for day in dates:
        opening = datetime.combine(date.fromisoformat(day), datetime.min.time(), NY)
        opening = opening.replace(hour=9, minute=30).astimezone(timezone.utc)
        for index, seconds in enumerate((0, 60, 119)):
            stamp = int((opening + timedelta(seconds=seconds)).timestamp()) * 1_000_000_000
            writer.writerow((stamp, "NQH6", "21000.25", 2, "N", index + 1))
    return out.getvalue().encode()


def manifest(raw, dates=("2026-03-06", "2026-03-09"), **changes):
    base = {
        "version": 1, "dataset_id": "fixture-q1", "provider": "SYNTHETIC TEST DATA",
        "venue": "SIMULATED", "schema": "canonical_trades_v1",
        "contract": "NQH6", "data_sha256": hashlib.sha256(raw).hexdigest(),
        "source_kind": "synthetic", "rights_status": "unverified",
        "rights_reference": "", "session_start": "09:30", "session_end": "09:32",
        "session_dates": list(dates), "opening_tolerance_seconds": 2,
        "closing_tolerance_seconds": 2, "max_intertrade_gap_seconds": 60,
        "max_trades": 1000,
    }
    return {**base, **changes}


class AdmissionTests(unittest.TestCase):
    def test_dst_change_preserves_local_session_boundaries(self):
        raw = sample()
        result = admit_trades(manifest(raw), raw)
        self.assertEqual(len(result["sessions"]), 2)
        self.assertNotEqual(
            result["sessions"][0]["first_event_ns"] // 1_000_000_000 % 86400,
            result["sessions"][1]["first_event_ns"] // 1_000_000_000 % 86400,
        )
        self.assertEqual(result["trade_records"], 6)
        self.assertFalse(result["independent_exchange_calendar_verification"])

    def test_checksum_tampering_rejected(self):
        raw = sample()
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            admit_trades(manifest(raw), raw + b"\n")

    def test_missing_and_unexpected_session_rejected(self):
        raw = sample(("2026-03-06",))
        with self.assertRaisesRegex(ValueError, "missing"):
            admit_trades(manifest(raw), raw)
        with self.assertRaisesRegex(ValueError, "unexpected"):
            admit_trades(manifest(raw, dates=("2026-03-09",)), raw)

    def test_gap_and_boundary_fail_closed(self):
        raw = sample()
        with self.assertRaisesRegex(ValueError, "gap"):
            admit_trades(manifest(raw, max_intertrade_gap_seconds=59), raw)
        with self.assertRaisesRegex(ValueError, "close"):
            admit_trades(manifest(raw, closing_tolerance_seconds=0), raw)
        rows = list(csv.reader(io.StringIO(raw.decode())))
        rows[1][0] = str(int(rows[1][0]) + 1_000_000_000)
        out = io.StringIO()
        csv.writer(out, lineterminator="\n").writerows(rows)
        shifted = out.getvalue().encode()
        with self.assertRaisesRegex(ValueError, "open"):
            admit_trades(manifest(shifted, opening_tolerance_seconds=0), shifted)

    def test_schema_contract_venue_and_rights_fail_closed(self):
        raw = sample()
        cases = (
            {"schema": "ohlcv-1m"},
            {"source_kind": "historical"},
            {"rights_status": "documented"},
            {"session_dates": ["2026-03-09", "2026-03-06"]},
            {"session_dates": ["2026-03-07"]},
            {"venue": "CME_GLOBEX"},
            {"contract": "MNQH6"},
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                admit_trades(manifest(raw, **case), raw)

    def test_documents_are_declarations_not_license_proof(self):
        raw = sample()
        result = admit_trades(manifest(
            raw, source_kind="historical", venue="CME_GLOBEX",
            rights_status="documented", rights_reference="Unverified vendor statement",
        ), raw)
        self.assertFalse(result["independent_license_verification"])
        self.assertFalse(result["independent_exchange_authentication"])


if __name__ == "__main__":
    unittest.main()
