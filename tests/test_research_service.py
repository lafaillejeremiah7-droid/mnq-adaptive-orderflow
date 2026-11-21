"""Durable offline research job-runner tests, using synthetic source rows."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from company import research_service as service
from tests.test_institutional_lab import dataset, registered


class ResearchServiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.db = self.root / "db" / "jobs.sqlite3"
        self.raw = dataset()
        self.protocol = registered(self.raw)
        self.p = self.root / "experiment.json"
        self.data = self.root / "input.csv"
        self.p.write_text(json.dumps(self.protocol))
        self.data.write_bytes(self.raw)
        self.output = self.root / "runs"

    def test_enqueue_one_worker_and_review_and_numeric_audit(self):
        study = service.enqueue(self.db, self.p, self.data, self.output)
        self.assertEqual(study, self.protocol["id"])
        self.assertEqual(service.get_jobs(self.db)[0]["state"], "queued")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            service.enqueue(self.db, self.p, self.data, self.output)
        job = service.worker_once(self.db)
        self.assertEqual(job["state"], "completed")
        self.assertFalse(job["production_ready"])
        artifacts = Path(job["artifact_path"])
        self.assertTrue((artifacts / "numeric_validation.json").exists())
        self.assertTrue((artifacts / "adversarial_review.json").exists())
        self.assertTrue((artifacts / "pipeline_receipt.json").exists())
        self.assertFalse(json.loads((artifacts / "adversarial_review.json").read_text())["screen_passed"])
        self.assertEqual(service.get_jobs(self.db, study)[0]["state"], "completed")
        self.assertIsNone(service.worker_once(self.db))

    def test_changed_input_after_queue_fails_and_can_retry_after_repair(self):
        study = service.enqueue(self.db, self.p, self.data, self.output)
        self.data.write_bytes(self.raw + b"CORRUPTED")
        result = service.worker_once(self.db)
        self.assertEqual(result["state"], "failed")
        self.assertIn("changed after registration", result["error"])
        self.assertFalse((self.output / study).exists())
        self.data.write_bytes(self.raw)
        service.retry(self.db, study)
        self.assertEqual(service.worker_once(self.db)["state"], "completed")
        with self.assertRaisesRegex(ValueError, "failed/interrupted"):
            service.retry(self.db, study)

    def test_stale_running_state_requires_explicit_recovery(self):
        study = service.enqueue(self.db, self.p, self.data, self.output)
        with service.open_store(self.db) as conn:
            conn.execute("UPDATE jobs SET state='running' WHERE id=?", (study,))
        self.assertIsNone(service.worker_once(self.db))
        self.assertEqual(service.recover_interrupted(self.db), 1)
        self.assertEqual(service.get_jobs(self.db, study)[0]["state"], "interrupted")
        service.retry(self.db, study)
        self.assertEqual(service.worker_once(self.db)["state"], "completed")

    def test_retry_rejects_immutable_partial_output(self):
        study = service.enqueue(self.db, self.p, self.data, self.output)
        with service.open_store(self.db) as conn:
            conn.execute("UPDATE jobs SET state='failed' WHERE id=?", (study,))
        (self.output / study).mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "partial immutable"):
            service.retry(self.db, study)

    def test_wrong_source_hash_blocked_at_enqueue(self):
        self.data.write_bytes(self.raw + b"tampered")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            service.enqueue(self.db, self.p, self.data, self.output)
        self.assertEqual(service.get_jobs(self.db), [])

    def test_sqlite_queue_status_is_persistent(self):
        study = service.enqueue(self.db, self.p, self.data, self.output)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute(
                "SELECT state FROM jobs WHERE id=?", (study,)
            ).fetchone()[0], "queued")
