"""Real tick-path and adversarial tests, using clearly synthetic samples."""
import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from company import market_profile as mp
from company.databento_trade_csv import convert, parse_event_ns

ROOT = Path(__file__).resolve().parents[1]


def make_csv(sessions, contract="NQH5"):
    """sessions: list of list[(price, size, side, seconds_from_NY_open)]"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(mp.COLUMNS)
    first = datetime(2025, 2, 3, 14, 30, tzinfo=timezone.utc)
    for day_index, session in enumerate(sessions):
        base = first + timedelta(days=day_index)
        for index, (price, size, side, seconds) in enumerate(session):
            ns = int((base + timedelta(seconds=seconds)).timestamp()) * 1_000_000_000
            writer.writerow([ns, contract, f"{price:.2f}", size, side, index + 1])
    return buffer.getvalue().encode()


def protocol(raw, contract="NQH5", **updates):
    item = {
        "id": "nq-profile-study",
        "question": "Does price reject or cross prior-day POC, VAH, VAL, HVNs and LVNs?",
        "falsifier": "Prior-profile touch outcomes no different from an appropriate baseline.",
        "data_source": "SYNTHETIC TEST TRADES, NOT MARKET DATA",
        "data_sha256": hashlib.sha256(raw).hexdigest(),
        "data_kind": "synthetic",
        "contract": contract,
        "rth_start": "09:30",
        "rth_end": "16:00",
        "value_area_fraction": 0.7,
        "touch_tolerance_ticks": 0,
        "excursion_ticks": 2,
        "horizon_seconds": 120,
        "min_profile_trades": 3,
        "min_eval_trades": 3,
        "min_session_pairs": 1,
        "max_gap_calendar_days": 4,
        "seed": 13,
        "max_trades": 1000,
    }
    return {**item, **updates}


BASE = [(100.0, 5, "B", 0), (100.25, 10, "A", 1), (100.5, 5, "N", 2)]
REJECT = [(100.75, 2, "N", 0), (100.25, 1, "N", 1), (100.75, 3, "N", 2)]
CROSS = [(100.75, 2, "N", 0), (100.25, 1, "N", 1), (99.75, 3, "N", 2)]


class ProfileTests(unittest.TestCase):
    def test_precise_volume_profile_and_aggressor_caveats(self):
        raw = make_csv([BASE])
        entries = mp.read_trades(raw, "NQH5", 10)
        profile = mp.volume_profile(entries, 0.70)
        self.assertEqual(profile["poc_ticks"], 401)
        self.assertEqual((profile["val_ticks"], profile["vah_ticks"]), (400, 401))
        self.assertEqual(profile["total_contracts_traded"], 20)
        self.assertEqual(profile["volume_at_price"]["100.25"], 10)
        self.assertEqual(profile["aggressor_buy_volume"], 5)
        self.assertEqual(profile["aggressor_sell_volume"], 10)
        self.assertEqual(profile["aggressor_unknown_volume"], 5)
        self.assertEqual(profile["known_trade_delta"], -5)
        self.assertFalse(profile["delta_covers_all_volume"])
        self.assertEqual(profile["volume_at_price_aggressor"]["100.25"]["known_delta"], -10)
        self.assertTrue(profile["volume_at_price_aggressor"]["100.25"]["complete_aggressor_coverage"])
        self.assertFalse(profile["volume_at_price_aggressor"]["100.5"]["complete_aggressor_coverage"])
        one_minute = list(profile["one_minute_trade_delta"].values())
        self.assertEqual(len(one_minute), 1)
        self.assertEqual(one_minute[0]["known_delta"], -5)
        self.assertEqual(one_minute[0]["running_known_delta"], -5)
        self.assertFalse(one_minute[0]["complete_side_coverage_through_minute"])
        self.assertIn(401, profile["hvn_ticks"])
        self.assertEqual(profile["lvn_ticks"], [])

    def test_nq_and_mnq_must_be_separate(self):
        for contract in ("NQH5", "MNQH5"):
            raw = make_csv([BASE], contract)
            t = mp.read_trades(raw, contract, 4)
            self.assertEqual(t[0].contract, contract)
        with self.assertRaisesRegex(ValueError, "mixed"):
            mp.read_trades(make_csv([BASE], "MNQH5"), "NQH5", 10)

    def test_hvn_lvn_are_local_extrema_and_zero_gap_distinct(self):
        session = [(100.0, 10, "N", 0), (100.25, 2, "N", 1),
                   (100.5, 10, "N", 2), (100.75, 2, "N", 3), (101.0, 9, "N", 4)]
        p = mp.volume_profile(mp.read_trades(make_csv([session]), "NQH5", 20), .70)
        self.assertIn(401, p["lvn_ticks"])
        self.assertIn(403, p["lvn_ticks"])
        gaps = [(100.0, 10, "N", 0), (100.5, 10, "N", 1)]
        p2 = mp.volume_profile(mp.read_trades(make_csv([gaps]), "NQH5", 20), .70)
        self.assertEqual(p2["untraded_price_bins"], 1)
        self.assertNotIn(401, p2["lvn_ticks"])

    def test_coincident_levels_are_one_physical_touch(self):
        profile = {
            "poc_ticks": 400, "vah_ticks": 400, "val_ticks": 400,
            "hvn_ticks": [400, 401], "lvn_ticks": [399, 399],
        }
        levels = mp.profile_levels(profile)
        self.assertEqual(levels, [("POC", 400), ("HVN", 401), ("LVN", 399)])

    def test_first_passage_exposes_count_and_timing(self):
        raw = make_csv([BASE, REJECT])
        r = mp.research(protocol(raw), raw)
        first = next(e for e in r["events"] if e["kind"] == "POC")
        self.assertEqual(first["followup_trades"], 1)
        self.assertEqual(first["first_passage_seconds"], 1)
        self.assertEqual(first["max_rejection_excursion_ticks"], 2)
        self.assertEqual(first["max_cross_excursion_ticks"], 0)

    def test_native_full_research_matches_python_when_built(self):
        import importlib.util
        if importlib.util.find_spec("company._nq_cpp") is None:
            self.skipTest("optional C++ kernel built by native workflow")
        for second in (REJECT, CROSS):
            raw = make_csv([BASE, second])
            cfg = protocol(raw)
            py_run = mp.research(cfg, raw, profile_backend="python")
            cpp_run = mp.research(cfg, raw, profile_backend="cpp")
            self.assertEqual(cpp_run["requested_aggregation_backend"], "cpp")
            self.assertEqual(cpp_run["actual_aggregation_backends"], ["cpp"])
            self.assertEqual(py_run["actual_aggregation_backends"], ["python"])
            for result in (py_run, cpp_run):
                result.pop("requested_aggregation_backend")
                result.pop("actual_aggregation_backends")
                for pair in result["session_pairs"]:
                    pair.pop("aggregation_backend_used")
            self.assertEqual(cpp_run, py_run)

    def test_cpp_cli_writes_binary_checksum_when_built(self):
        import importlib.util
        if importlib.util.find_spec("company._nq_cpp") is None:
            self.skipTest("native extension optional; C++ workflow compiles it")
        raw = make_csv([BASE, REJECT])
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            config = directory / "protocol.json"
            data = directory / "trades.csv"
            config.write_text(json.dumps(protocol(raw)))
            data.write_bytes(raw)
            cmd = [
                sys.executable, "-m", "company.market_profile",
                "--spec", str(config), "--trades", str(data),
                "--out-root", str(directory / "runs"),
                "--profile-backend", "cpp",
            ]
            run = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(run.returncode, 0, run.stderr)
            artifact = json.loads(
                (directory / "runs" / "nq-profile-study" / "result.json").read_text()
            )
            self.assertEqual(artifact["requested_aggregation_backend"], "cpp")
            self.assertEqual(artifact["actual_aggregation_backends"], ["cpp"])
            self.assertEqual(len(artifact["cpp_binary_sha256"]), 64)
            self.assertEqual(len(artifact["cpp_source_sha256"]), 64)

    def test_profile_backend_validation(self):
        raw = make_csv([BASE, REJECT])
        with self.assertRaises(ValueError):
            mp.research(protocol(raw), raw, profile_backend="invalid")

    def test_past_profile_rejection_first(self):
        raw = make_csv([BASE, REJECT])
        r = mp.research(protocol(raw), raw)
        self.assertEqual(r["status"], "descriptive_only")
        self.assertFalse(r["tradable_edge_validated"])
        previous = r["prior_session_profiles"]["2025-02-03"]
        self.assertEqual(previous["poc_ticks"], 401)
        self.assertEqual(len(r["session_pairs"]), 1)
        self.assertLess(r["session_pairs"][0]["profile_last_event_ns"],
                        r["session_pairs"][0]["evaluation_first_event_ns"])
        poc = [e for e in r["events"] if e["kind"] == "POC"]
        self.assertEqual(len(poc), 1)
        self.assertEqual(poc[0]["outcome"], "rejection_first")
        self.assertEqual(poc[0]["approach_from"], "above")

    def test_cross_first_not_confused_with_rejection(self):
        raw = make_csv([BASE, CROSS])
        r = mp.research(protocol(raw), raw)
        poc = [e for e in r["events"] if e["kind"] == "POC"]
        self.assertEqual(len(poc), 1)
        self.assertEqual(poc[0]["outcome"], "cross_first")

    def test_gap_across_level_is_not_a_printed_touch(self):
        raw = make_csv([BASE, [(100.75, 1, "N", 0), (99.75, 1, "N", 1),
                                   (99.5, 1, "N", 2)]])
        r = mp.research(protocol(raw), raw)
        self.assertFalse(any(e["kind"] == "POC" for e in r["events"]))

    def test_no_future_record_is_censored(self):
        raw = make_csv([BASE, [(100.75, 1, "N", 0), (100.25, 1, "N", 1),
                                   (100.75, 1, "N", 300)]])
        r = mp.research(protocol(raw), raw)
        poc = next(e for e in r["events"] if e["kind"] == "POC")
        self.assertEqual(poc["outcome"], "censored_no_future_trade")

    def test_input_checksum_and_ordering_fail_closed(self):
        raw = make_csv([BASE, REJECT])
        spec = protocol(raw)
        with self.assertRaisesRegex(ValueError, "checksum"):
            mp.research(spec, raw + b"corrupted")
        rows = raw.decode().splitlines()
        bad = ("\n".join(rows[:3] + [rows[2]] + rows[3:]) + "\n").encode()
        with self.assertRaisesRegex(ValueError, "increasing"):
            mp.read_trades(bad, "NQH5", 20)

    def test_bad_specs_rejected(self):
        raw = make_csv([BASE, REJECT])
        for delta in [
            {"value_area_fraction": 1.5},
            {"excursion_ticks": 0},
            {"touch_tolerance_ticks": 4, "excursion_ticks": 2},
            {"rth_start": "16:00", "rth_end": "09:30"},
            {"contract": "NQH25-MNQH25"},
            {"max_trades": -1},
        ]:
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                mp.research(protocol(raw, **delta), raw)

    def test_small_sample_not_promoted(self):
        raw = make_csv([BASE, REJECT])
        r = mp.research(protocol(raw, min_session_pairs=3), raw)
        self.assertEqual(r["status"], "insufficient_session_pairs")
        self.assertFalse(r["tradable_edge_validated"])

    def test_reproducible_run_and_immutable_artifacts(self):
        raw = make_csv([BASE, CROSS])
        spec = protocol(raw)
        self.assertEqual(mp.research(spec, raw), mp.research(spec, raw))
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            config = directory / "protocol.json"
            source = directory / "ticks.csv"
            config.write_text(json.dumps(spec))
            source.write_bytes(raw)
            target = mp.run(config, source, directory / "runs")
            self.assertTrue((target / "research_note.md").exists())
            self.assertIn("event_summary", json.loads((target / "result.json").read_text()))
            with self.assertRaises(FileExistsError):
                mp.run(config, source, directory / "runs")

    def test_cli_smoke(self):
        raw = make_csv([BASE, REJECT])
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "spec.json").write_text(json.dumps(protocol(raw)))
            (directory / "trades.csv").write_bytes(raw)
            r = subprocess.run(
                [sys.executable, "-m", "company.market_profile",
                 "--spec", str(directory / "spec.json"),
                 "--trades", str(directory / "trades.csv"),
                 "--out-root", str(directory / "runs")],
                capture_output=True, text=True, cwd=ROOT,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((directory / "runs" / "nq-profile-study" / "result.json").exists())


class DatabentoAdapterTests(unittest.TestCase):
    def test_ns_timestamp_and_vendor_conversion(self):
        self.assertEqual(parse_event_ns("2025-02-03 14:30:00.123456789+00:00") % 1_000_000_000,
                         123456789)
        vendor = (
            "ts_event,sequence,symbol,price,size,side,action\n"
            "2025-02-03 14:30:00.123456789+00:00,1,NQH5,21000.25,4,B,T\n"
            "2025-02-03 14:30:01.000000001+00:00,2,NQH5,21000.50,2,A,T\n"
        ).encode()
        canonical = convert(vendor, "NQH5")
        trades = mp.read_trades(canonical, "NQH5", 10)
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0].timestamp_ns % 1_000_000_000, 123456789)
        self.assertEqual(trades[0].price_ticks, 84001)
        self.assertEqual(trades[1].size, 2)

    def test_vendor_unknown_symbol_or_price_rejected(self):
        vendor = (
            "ts_event,sequence,symbol,price,size,side,action\n"
            "2025-02-03T14:30:00Z,1,MNQH5,21000.25,1,B,T\n"
        ).encode()
        with self.assertRaisesRegex(ValueError, "mixed"):
            convert(vendor, "NQH5")
        with self.assertRaises(ValueError):
            convert(vendor.replace(b"21000.25", b"21000.10"), "MNQH5")
        with self.assertRaises(ValueError):
            convert(vendor.replace(b",T", b",A"), "MNQH5")


if __name__ == "__main__":
    unittest.main()
