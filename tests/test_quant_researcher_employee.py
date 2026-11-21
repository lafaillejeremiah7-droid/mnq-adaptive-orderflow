"""Synthetic data tests for the MNQ Quant Researcher employee."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from company.quant_researcher import analyze, run

ROOT = Path(__file__).resolve().parents[1]


def bars(n=4, inverted=False, missing=False):
    output = ["timestamp,contract,open,high,low,close"]
    for d in range(n):
        day = (date(2025, 2, 3) + timedelta(days=d)).isoformat()
        for hour, width in [("14:30", 8), ("14:31", 6), ("17:00", 2), ("17:01", 4)]:
            if missing and d == 1 and hour == "17:01":
                continue
            if inverted:
                width = 10 - width
            output.append(f"{day}T{hour}:00Z,MNQH5,21000,{21000+width/2:.2f},{21000-width/2:.2f},21000")
    return ("\n".join(output) + "\n").encode()


def spec(raw, **updates):
    item = {
        "id": "test-employee", "question": "Is opening MNQ intraminute range larger?",
        "hypothesis": "Opening exceeds midday", "falsifier": "Median difference <= 0",
        "data_source": "SYNTHETIC UNIT TEST DATA, NOT MARKET DATA",
        "data_kind": "synthetic", "data_sha256": hashlib.sha256(raw).hexdigest(),
        "contract": "MNQH5",
        "start": "2025-02-03T00:00:00Z", "end": "2025-02-08T00:00:00Z",
        "window_a": {"label": "open", "start": "09:30", "end": "09:32"},
        "window_b": {"label": "midday", "start": "12:00", "end": "12:02"},
        "min_dates": 3, "seed": 42,
    }
    return {**item, **updates}


class QuantResearchEmployeeTests(unittest.TestCase):
    def test_positive_descriptive_not_trade_edge(self):
        raw = bars()
        result = analyze(spec(raw), raw)
        self.assertEqual(result["n_complete_dates"], 4)
        self.assertEqual(result["median_paired_difference_points"], 4)
        self.assertEqual(result["sign_test_p_if_dates_independent"], 0.125)
        self.assertEqual(result["status"], "descriptive_only")
        self.assertFalse(result["tradable_edge_validated"])

    def test_negative_result(self):
        raw = bars(inverted=True)
        self.assertFalse(analyze(spec(raw), raw)["hypothesis_supported_in_sample"])

    def test_missing_data_is_excluded(self):
        raw = bars(missing=True)
        result = analyze(spec(raw), raw)
        self.assertEqual(result["n_complete_dates"], 3)
        self.assertIn("2025-02-04", result["excluded_dates"])

    def test_short_sample_is_inconclusive(self):
        raw = bars(n=2)
        result = analyze(spec(raw), raw)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["hypothesis_supported_in_sample"])

    def test_checksum_mismatch(self):
        raw = bars()
        with self.assertRaisesRegex(ValueError, "checksum"):
            analyze(spec(raw), raw + b"tamper")

    def test_wrong_contract(self):
        raw = bars().replace(b"MNQH5", b"MNQM5")
        with self.assertRaisesRegex(ValueError, "contract"):
            analyze(spec(raw), raw)

    def test_duplicate_utc_timestamp(self):
        rows = bars().decode().splitlines()
        raw = ("\n".join(rows[:3] + [rows[2]] + rows[3:]) + "\n").encode()
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            analyze(spec(raw), raw)

    def test_invalid_specs(self):
        raw = bars()
        for change in [
            {"contract": "NQH5"}, {"min_dates": 1}, {"seed": -1},
            {"window_a": {"label": "x", "start": "12:00", "end": "12:02"}},
            {"window_a": {"label": "x", "start": "10:00", "end": "09:30"}},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                analyze(spec(raw, **change), raw)

    def test_immutable_reproducible_output(self):
        raw = bars()
        s = spec(raw)
        self.assertEqual(analyze(s, raw), analyze(s, raw))
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "spec.json").write_text(json.dumps(s))
            (base / "bars.csv").write_bytes(raw)
            path = run(base / "spec.json", base / "bars.csv", base / "runs")
            for filename in ("protocol.json", "result.json", "research_note.md"):
                self.assertTrue((path / filename).is_file())
            with self.assertRaises(FileExistsError):
                run(base / "spec.json", base / "bars.csv", base / "runs")

    def test_runnable_python_module(self):
        raw = bars()
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "spec.json").write_text(json.dumps(spec(raw)))
            (base / "bars.csv").write_bytes(raw)
            result = subprocess.run(
                [sys.executable, "-m", "company.quant_researcher",
                 "--spec", str(base / "spec.json"), "--data", str(base / "bars.csv"),
                 "--out-root", str(base / "runs")], capture_output=True, text=True, cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((base / "runs" / "test-employee" / "result.json").exists())
