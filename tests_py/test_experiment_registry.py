from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import experiment_registry as registry


class RegistryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.db = self.root / "research.sqlite"
        registry.initialize(self.db)
        self.data = self.root / "experiment-input"
        self.data.write_bytes(b"deterministic fixture")
        self.spec = {
            "experiment_id": "drift-1", "question": "Does decay improve Brier score?",
            "model_version": "recency-v1", "git_commit": "1" * 40, "seed": 19,
            "dataset": {"id": "test", "source": "generated unit-test fixture", "kind": "synthetic",
                        "sha256": hashlib.sha256(self.data.read_bytes()).hexdigest()},
            "data_period": [1, 200], "windows": {
                "training": [1, 40], "validation": [45, 100], "holdout": [100, 200]},
            "features": {"age": "elapsed milliseconds since label resolution"},
            "parameters": {"half_life": 24}, "hypotheses": ["24h decay"],
            "baseline": "geometry", "acceptance_rule": "held-out improvement",
            "cost_assumptions": "probability scoring only", "drawdown_assumptions": "zero exposure",
        }
        self.rejected = {
            "status": "REJECTED", "hypotheses_tested": 1, "holdout_used": True,
            "reviewer": "test", "findings": "Larger Brier loss", "metrics": {"brier_gain": -0.05},
            "rejection_reasons": ["Failed prespecified score"],
        }
        self.retained = dict(self.rejected, status="RETAINED_FOR_RESEARCH", rejection_reasons=[])
        self.forward_data = self.root / "next.csv"
        self.forward_data.write_bytes(b"forward fixture")
        self.observation = {
            "kind": "synthetic", "source": "subsequent independent fixture",
            "period": [1100, 1200], "sample_size": 1, "metrics": {"brier": 0.81},
            "findings": "Calibration worsened",
            "sha256": hashlib.sha256(self.forward_data.read_bytes()).hexdigest(),
        }

    def register(self):
        return registry.register(self.db, self.spec, self.data)

    def test_failure_and_forward_history_survives_retries_and_alias_changes(self):
        with patch.object(registry, "now_ms", return_value=1000):
            self.register()
            registry.decide(self.db, "drift-1", self.rejected)
            with self.assertRaisesRegex(registry.RegistryError, "already recorded"):
                registry.decide(self.db, "drift-1", self.retained)
        old = registry.history(self.db, "drift-1")
        with patch.object(registry, "now_ms", return_value=1300):
            digest = registry.observe(self.db, "drift-1", self.observation, self.forward_data)
        state = registry.history(self.db, "drift-1", digest)
        self.assertEqual(state["decision"], old["decision"])
        self.assertEqual(state["decision"]["status"], "REJECTED")
        self.assertEqual(state["decision"]["rejection_reasons"], self.rejected["rejection_reasons"])
        self.assertEqual(state["spec"]["parameters"], {"half_life": 24})
        self.assertEqual(state["observations"][0]["recorded_at"], 1300)
        with self.assertRaisesRegex(registry.RegistryError, "checkpoint"):
            registry.history(self.db, "drift-1", old["head_sha256"])
        self.assertEqual(registry.list_experiments(self.db)[0]["hypotheses_tested"], 1)

    def test_missing_history_does_not_create_a_replacement(self):
        missing = self.root / "missing.sqlite"
        for operation in (lambda: registry.history(missing, "drift-1"),
                          lambda: registry.register(missing, self.spec, self.data)):
            with self.assertRaises(registry.RegistryError):
                operation()
            self.assertFalse(missing.exists())
        with self.assertRaisesRegex(registry.RegistryError, "No experiment"):
            registry.decide(self.db, "unknown", self.rejected)
        with self.assertRaisesRegex(registry.RegistryError, "already exists"):
            registry.initialize(self.db)

    def test_immutable_spec_and_hash_verification(self):
        original = self.register()
        self.spec["seed"] += 1
        with self.assertRaises(registry.RegistryError):
            self.register()
        self.assertEqual(registry.history(self.db, "drift-1")["head_sha256"], original)
        self.data.write_bytes(b"revised data")
        with self.assertRaisesRegex(registry.RegistryError, "SHA-256"):
            self.register()

    def test_mutation_blocked_and_out_of_band_rewrite_detected(self):
        self.register()
        with sqlite3.connect(self.db) as db:
            for sql in ["UPDATE events SET payload='{}'", "DELETE FROM events"]:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql)
            db.execute("DROP TRIGGER prevent_update")
            db.execute("UPDATE events SET payload='{}'")
        with self.assertRaisesRegex(registry.RegistryError, "fingerprint"):
            registry.history(self.db, "drift-1")

    def test_conflicting_concurrent_decisions_are_serialized(self):
        self.register()
        def try_decision(value):
            try:
                return registry.decide(self.db, "drift-1", value)
            except registry.RegistryError:
                return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = list(executor.map(try_decision, [self.rejected, self.retained]))
        self.assertEqual(sum(digest is not None for digest in result), 1)
        self.assertIn(registry.history(self.db, "drift-1")["head_sha256"], result)

    def test_reused_holdout_after_failure_records_rejection(self):
        self.register()
        registry.decide(self.db, "drift-1", self.rejected)
        self.spec["experiment_id"] = "retry"
        self.spec["dataset"]["id"] = "renamed artifact"
        self.spec["windows"] = {"training": [1, 30], "validation": [30, 45], "holdout": [45, 100]}
        self.register()
        registry.decide(self.db, "retry", self.retained)
        result = registry.history(self.db, "retry")["decision"]
        self.assertEqual(result["prior_holdout_exposures"], [
            {"experiment_id": "drift-1", "window": "validation"}])
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["submitted_status"], "RETAINED_FOR_RESEARCH")
        self.assertEqual(len(registry.list_experiments(self.db)), 2)

    def test_malformed_spec_does_not_change_history(self):
        for key, value in [("windows", {"training": [1, 100], "validation": [99, 120],
                                        "holdout": [120, 140]}),
                           ("git_commit", "main"), ("seed", True), ("hypotheses", ["x", "x"]),
                           ("features", {"delta": ""}), ("parameters", {"z": float("inf")})]:
            with self.subTest(key=key), self.assertRaises(registry.RegistryError):
                registry.register(self.db, {**self.spec, key: value}, self.data)
        self.assertEqual(registry.list_experiments(self.db), [])

    def test_cannot_relabel_illustrative_bytes_even_if_renamed(self):
        fixture = Path(__file__).resolve().parents[1] / "examples/ILLUSTRATIVE_mnq_labeled_setups.csv"
        self.data.write_bytes(fixture.read_bytes())
        self.spec["dataset"].update(kind="historical", sha256=hashlib.sha256(self.data.read_bytes()).hexdigest())
        with self.assertRaisesRegex(registry.RegistryError, "synthetic"):
            self.register()

    def test_fabricated_metrics_or_status_rejected(self):
        self.register()
        for candidate in [dict(self.retained, status="LIVE_VERIFIED"),
                          dict(self.retained, hypotheses_tested=2),
                          dict(self.rejected, rejection_reasons=[]),
                          dict(self.rejected, metrics={"net": float("nan")}),
                          dict(self.rejected, holdout_used=1)]:
            with self.subTest(candidate=candidate), self.assertRaises(registry.RegistryError):
                registry.decide(self.db, "drift-1", candidate)
        self.assertIsNone(registry.history(self.db, "drift-1")["decision"])

    def test_future_out_of_order_and_recycled_observations_fail(self):
        with patch.object(registry, "now_ms", return_value=1000):
            self.register()
            with self.assertRaisesRegex(registry.RegistryError, "prior decision"):
                registry.observe(self.db, "drift-1", self.observation, self.forward_data)
            registry.decide(self.db, "drift-1", self.rejected)
        with patch.object(registry, "now_ms", return_value=1300):
            for period in [[1000, 1200], [1100, 1400]]:
                with self.assertRaisesRegex(registry.RegistryError, "subsequent"):
                    registry.observe(self.db, "drift-1", dict(self.observation, period=period),
                                     self.forward_data)
            recycled = dict(self.observation, sha256=self.spec["dataset"]["sha256"])
            with self.assertRaisesRegex(registry.RegistryError, "reused"):
                registry.observe(self.db, "drift-1", recycled, self.data)
            registry.observe(self.db, "drift-1", self.observation, self.forward_data)
            with self.assertRaisesRegex(registry.RegistryError, "reused"):
                registry.observe(self.db, "drift-1", dict(self.observation, period=[1200, 1250]),
                                 self.forward_data)

    def test_command_line_from_registration_to_readback(self):
        spec_file = self.root / "spec.json"
        spec_file.write_text(json.dumps(self.spec))
        command = [sys.executable, "-m", "scripts.experiment_registry", str(self.db)]
        result = subprocess.run([*command, "register", str(spec_file), str(self.data)],
                                capture_output=True, text=True, check=True)
        digest = json.loads(result.stdout)
        result = subprocess.run([*command, "show", "drift-1", "--expected-head", digest],
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["spec"], self.spec)
        spec_file.write_text('{"seed":1,"seed":2}')
        result = subprocess.run([*command, "register", str(spec_file), str(self.data)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Duplicate JSON key", result.stderr)
