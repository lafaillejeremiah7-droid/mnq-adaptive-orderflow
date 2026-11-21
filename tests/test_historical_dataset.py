"""Synthetic multi-partition registry tests; no licensed CME files used."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from company import historical_dataset as hd
from tests.test_data_admission import manifest, sample


def fixture(folder, expected=("2026-03-06", "2026-03-09"), target="NQH6"):
    root = Path(folder)
    dates = list(expected)
    calendar = ("session_date,contract\n" +
                "".join(f"{day},{target}\n" for day in dates)).encode()
    (root / "calendar.csv").write_bytes(calendar)
    parts = []
    for idx, day in enumerate(dates):
        raw = sample((day,))
        name = f"part{idx}.csv"
        man = f"manifest{idx}.json"
        (root / name).write_bytes(raw)
        (root / man).write_text(json.dumps(manifest(raw, dates=(day,))))
        parts.append({"file": name, "manifest": man})
    return {
        "version": 1, "dataset_id": "test-two-sessions",
        "dataset": "GLBX.MDP3", "contract_root": "NQ",
        "source_kind": "synthetic", "rights_status": "unverified",
        "rights_reference": "", "calendar_file": "calendar.csv",
        "calendar_sha256": hashlib.sha256(calendar).hexdigest(),
        "partitions": parts,
    }


class HistoricalRegistryTests(unittest.TestCase):
    def test_two_partitions_after_dst_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            r = fixture(directory)
            result = hd.check_registry(r, directory)
            self.assertEqual(result["observed_sessions"], 2)
            self.assertEqual(result["total_trade_records"], 6)
            self.assertFalse(result["independent_contract_roll_verified"])
            self.assertFalse(result["independent_exchange_data_authentication"])

    def test_tampered_file_hash_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            r = fixture(directory)
            (Path(directory) / "part1.csv").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                hd.check_registry(r, directory)

    def test_missing_partition_fails_calendar_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            r = fixture(directory)
            r["partitions"] = r["partitions"][:1]
            with self.assertRaisesRegex(ValueError, "missing"):
                hd.check_registry(r, directory)

    def test_duplicate_partitions_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            r = fixture(directory)
            r["partitions"].append(dict(r["partitions"][0]))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                hd.check_registry(r, directory)

    def test_wrong_roll_assignment_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            r = fixture(directory)
            calendar = b"session_date,contract\n2026-03-06,NQH6\n2026-03-09,NQM6\n"
            (Path(directory) / "calendar.csv").write_bytes(calendar)
            r["calendar_sha256"] = hashlib.sha256(calendar).hexdigest()
            with self.assertRaisesRegex(ValueError, "rollover"):
                hd.check_registry(r, directory)

    def test_malicious_path_and_calendar_tampering_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            r = fixture(directory)
            r["partitions"][0]["file"] = "../outside.csv"
            with self.assertRaisesRegex(ValueError, "escapes"):
                hd.check_registry(r, directory)
            r = fixture(directory)
            (Path(directory) / "calendar.csv").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                hd.check_registry(r, directory)

    def test_unverified_rights_cannot_be_upgraded_implicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            r = fixture(directory)
            r["rights_status"] = "documented"
            r["rights_reference"] = "Source not independently verified"
            with self.assertRaisesRegex(ValueError, "rights mismatch"):
                hd.check_registry(r, directory)
