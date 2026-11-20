"""Adversarial offline tests for the institutional quantitative research lab.

Fixtures explicitly synthetic, unrelated to market data or claimed alpha.
"""
import csv
import hashlib
import io
import json
import math
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from company import research_lab as lab
from company import research_gate as gate

ROOT = Path(__file__).resolve().parents[1]
TRAIN_DAYS = ("2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09", "2025-01-10")
TEST_DAYS = ("2025-01-13", "2025-01-14", "2025-01-15", "2025-01-16",
             "2025-01-17", "2025-01-20", "2025-01-21", "2025-01-22",
             "2025-01-23", "2025-01-24")


def timestamp(value):
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def dataset(overlap=False, bad_feature=False, bad_contract=False):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([*lab.BASE_COLS, "x_delta_proxy", "x_volatility_proxy"])
    for day_index, day in enumerate((*TRAIN_DAYS, *TEST_DAYS)):
        base = datetime.fromisoformat(day + "T09:30:00+00:00")
        for i in range(25):
            decision = base + timedelta(minutes=5*i)
            available = decision - timedelta(seconds=1)
            if bad_feature and day_index == 0 and i == 0:
                available = decision + timedelta(seconds=1)
            end = decision + timedelta(seconds=(420 if overlap else 60))
            feature = (i % 11 - 5)*0.6 + day_index*0.03
            noise = 0.1 if i % 2 else -0.1
            outcome = 2.1*feature + 0.03*(i % 4) + noise
            writer.writerow([
                timestamp(decision), timestamp(available), timestamp(end),
                "MNQH5" if (bad_contract and day_index == 0 and i == 0) else "NQH5",
                "{:.8f}".format(outcome),
                "{:.8f}".format(feature),
                "{:.8f}".format(feature**2),
            ])
    return out.getvalue().encode()


def registered(raw, **updates):
    spec = {
        "id": "research-qualification-001",
        "researcher": "quant-researcher-001",
        "question": "Does declared past information forecast next-event NQ returns?",
        "hypothesis": "Training-only ridge improves squared error against train-only mean.",
        "falsifier": "On untouched chronological test dates, model MSE does not beat baseline.",
        "data_source": "SYNTHETIC FIXTURE; NOT A REAL EXCHANGE FEED",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_kind": "synthetic",
        "source_rights": "unverified",
        "contract": "NQH5",
        "features": ["x_delta_proxy", "x_volatility_proxy"],
        "train_end_utc": "2025-01-11T00:00:00Z",
        "test_start_utc": "2025-01-13T00:00:00Z",
        "test_end_utc": "2025-01-25T00:00:00Z",
        "embargo_seconds": 60,
        "max_label_horizon_seconds": 600,
        "test_folds": 3,
        "retraining": "frozen",
        "min_train_dates": 4,
        "min_test_dates": 8,
        "min_test_events": 100,
        "ridge_lambda": 10.0,
        "decision_threshold_bps": 0.5,
        "cost_per_side_bps": 0.3,
        "hypotheses_in_family": 12,
        "seed": 123,
        "max_records": 1000,
        "data_previously_examined": True,
    }
    return {**spec, **updates}


class InstitutionalLabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = dataset()
        cls.protocol = registered(cls.raw)
        cls.result = lab.experiment(cls.protocol, cls.raw)

    def test_frozen_out_of_sample_training_is_constant(self):
        folds = self.result["folds"]
        self.assertEqual(len(folds), 3)
        self.assertEqual(len({f["train_events"] for f in folds}), 1)
        self.assertTrue(all(
            f["training_last_label_end_utc"] < f["test_first_decision_utc"] for f in folds
        ))
        self.assertEqual(self.result["out_of_sample"]["events"], 250)
        self.assertFalse(self.result["production_ready"])

    def test_model_must_beat_baseline_on_heldout_synthetic_data(self):
        stat = self.result["out_of_sample"]
        self.assertLess(stat["model_RMSE_bps"], stat["baseline_train_mean_RMSE_bps"])
        self.assertGreater(stat["OOS_MSE_improvement_over_baseline_bps2"], 0)
        self.assertEqual(stat["day_block_MSE_improvement"]["number_of_days"], 10)
        self.assertLessEqual(stat["bonferroni_p_for_registered_family"], 1)

    def test_deterministic_no_hidden_randomness(self):
        self.assertEqual(self.result, lab.experiment(self.protocol, self.raw))

    def test_expanding_walk_forward_uses_only_completed_labels(self):
        result = lab.experiment(registered(self.raw, retraining="expanding"), self.raw)
        folds = result["folds"]
        self.assertLess(folds[0]["train_events"], folds[1]["train_events"])
        self.assertLess(folds[1]["train_events"], folds[2]["train_events"])
        self.assertTrue(all(
            f["training_last_label_end_utc"] < f["test_first_decision_utc"] for f in folds
        ))

    def test_frozen_cutoff_purges_labels_unavailable_at_train_end(self):
        # A label from a pre-cutoff decision that ends after train_end may
        # not enter a model frozen on train_end, even if test begins later.
        raw = dataset()
        original = lab.experiment(registered(raw), raw)
        protocol = registered(raw, train_end_utc="2025-01-10T10:00:00Z",
                              min_train_dates=4)
        adjusted = lab.experiment(protocol, raw)
        self.assertLess(adjusted["folds"][0]["train_events"],
                        original["folds"][0]["train_events"])
        self.assertLessEqual(adjusted["folds"][0]["training_last_label_end_utc"],
                             "2025-01-10T10:00:00+00:00")

    def test_future_feature_is_hard_failure(self):
        raw = dataset(bad_feature=True)
        with self.assertRaisesRegex(ValueError, "lookahead"):
            lab.experiment(registered(raw), raw)

    def test_mixed_contract_is_hard_failure(self):
        raw = dataset(bad_contract=True)
        with self.assertRaisesRegex(ValueError, "mixed"):
            lab.experiment(registered(raw), raw)

    def test_overlapping_returns_disable_trading_diagnostics(self):
        raw = dataset(overlap=True)
        result = lab.experiment(registered(raw), raw)
        self.assertEqual(result["cost_sensitivity"]["status"], "unavailable_overlapping_labels")

    def test_source_checksum_is_mandatory(self):
        with self.assertRaisesRegex(ValueError, "checksum"):
            lab.experiment(self.protocol, self.raw + b"BAD")

    def test_missing_feature_or_target_rejected(self):
        raw = self.raw.replace(b"x_delta_proxy,x_volatility_proxy", b"x_wrong,x_volatility_proxy", 1)
        with self.assertRaisesRegex(ValueError, "columns"):
            lab.experiment(registered(raw), raw)

    def test_unsupported_protocol_and_date_configuration_rejected(self):
        for change in (
            {"train_end_utc": "2025-01-21T00:00:00Z"},
            {"cost_per_side_bps": -1},
            {"hypotheses_in_family": 0},
            {"features": ["x_delta_proxy", "x_delta_proxy"]},
            {"features": ["target_return"]},
            {"retraining": "auto"},
            {"source_rights": "trust_me"},
            {"max_records": 30},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                lab.experiment(registered(self.raw, **change), self.raw)

    def test_naive_and_non_UTC_timestamps_rejected(self):
        for text in ("2025-01-01T09:00:00", "2025-01-01T09:00:00-05:00", "bad"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                lab.utc_timestamp(text)

    def test_cost_round_trip_and_day_reset(self):
        base = datetime.fromisoformat("2025-02-03T09:00:00+00:00")
        events = [
            {"date": "2025-02-03", "decision": base,
             "end": base + timedelta(minutes=1), "pred": 5.0, "y": 10.0},
            {"date": "2025-02-04", "decision": base + timedelta(days=1),
             "end": base + timedelta(days=1, minutes=1), "pred": -5.0, "y": -10.0},
        ]
        out = lab.trading_diagnostics(events, threshold=0, cost=2.0, seed=1)
        self.assertEqual(out["turnover_one_side_units"], 4)
        self.assertEqual(out["charged_friction_bps"], 8.0)
        self.assertEqual(out["indicative_net_cumulative_bps"], 12.0)
        self.assertFalse(out["independent_executability_or_exchange_queues_verified"])

    def test_singularity_handling(self):
        self.assertEqual(lab.solve_linear([[2, 0], [0, 3]], [4, 9]), [2, 3])
        with self.assertRaises(ValueError):
            lab.solve_linear([[0, 0], [0, 0]], [1, 1])
        x = [{"x": [1.0, 1.0], "y": 3.0}] * 20
        self.assertTrue(math.isfinite(lab.predict(lab.fit_ridge(x, 10), [1.0, 1.0])))

    def test_uncertainty_and_test_multiplicity(self):
        self.assertEqual(lab.exact_sign_p([0, 0]), None)
        self.assertEqual(lab.exact_sign_p([1, 1, 1]), 0.25)
        out = lab.score_predictions(
            [{"date": "2025-01-01", "y": 3, "pred": 3, "baseline": 0}],
            seed=7, hypothesis_family=30
        )
        self.assertEqual(out["bonferroni_p_for_registered_family"], 1.0)

    def test_immutable_cli_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            protocol_path, source_path = path/"protocol.json", path/"source.csv"
            protocol_path.write_text(json.dumps(self.protocol, sort_keys=True))
            source_path.write_bytes(self.raw)
            folder = lab.run(protocol_path, source_path, path/"runs")
            self.assertTrue((folder/"research_note.md").exists())
            self.assertEqual(json.loads((folder/"result.json").read_text())["protocol_sha256"],
                             hashlib.sha256(protocol_path.read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):
                lab.run(protocol_path, source_path, path/"runs")
            cli = subprocess.run([sys.executable, "-m", "company.research_gate",
                                  "--study", str(folder)], cwd=ROOT,
                                 text=True, capture_output=True)
            self.assertEqual(cli.returncode, 0, cli.stderr)
            self.assertTrue((folder/"adversarial_review.json").exists())


class AdversarialGateTests(unittest.TestCase):
    def setUp(self):
        self.raw = dataset()
        self.spec = registered(self.raw)
        self.bytes = json.dumps(self.spec, sort_keys=True).encode()
        self.result = lab.experiment(self.spec, self.raw)
        self.result["protocol_sha256"] = hashlib.sha256(self.bytes).hexdigest()
        self.result["engine_sha256"] = hashlib.sha256(b"synthetic code").hexdigest()

    def test_no_self_approval_even_on_positive_backtest(self):
        audit = gate.audit(self.bytes, self.result)
        self.assertFalse(audit["screen_passed"])
        self.assertFalse(audit["production_ready"])
        self.assertFalse(audit["authorization_to_trade"])
        failures = {x["code"] for x in audit["blockers"]}
        self.assertIn("SYNTHETIC_ONLY", failures)
        self.assertIn("NO_INDEPENDENT_VALIDATOR", failures)
        self.assertIn("RAW_FEATURE_LINEAGE_UNVERIFIED", failures)

    def test_reviewer_source_and_engine_reverification(self):
        raw = self.raw
        engine = b"synthetic code"
        check = gate.audit(self.bytes, self.result,
                           source_bytes=raw, engine_bytes=engine)
        self.assertTrue(check["reviewer_independently_rechecked_raw_bytes"])
        self.assertTrue(check["reviewer_independently_rechecked_engine_bytes"])
        self.assertFalse(check["production_ready"])
        with self.assertRaisesRegex(ValueError, "independent source"):
            gate.audit(self.bytes, self.result, source_bytes=raw+b"tampered")
        with self.assertRaisesRegex(ValueError, "independent engine"):
            gate.audit(self.bytes, self.result, source_bytes=raw, engine_bytes=b"wrong")

    def test_protocol_tampering_rejected(self):
        changed = self.bytes.replace(b"research-qualification-001", b"research-qualification-002")
        with self.assertRaisesRegex(ValueError, "checksum"):
            gate.audit(changed, self.result)

    def test_unverified_metric_rejected(self):
        damaged = dict(self.result)
        damaged["out_of_sample"] = {**damaged["out_of_sample"], "model_RMSE_bps": float("nan")}
        with self.assertRaisesRegex(ValueError, "holdout score"):
            gate.audit(self.bytes, damaged)

    def test_folds_or_embargo_tampering_rejected(self):
        damaged = dict(self.result)
        damaged["folds"] = [{**self.result["folds"][0], "embargo_seconds": 0}, *self.result["folds"][1:]]
        with self.assertRaisesRegex(ValueError, "embargo"):
            gate.audit(self.bytes, damaged)


if __name__ == "__main__":
    unittest.main()
