"""Independent numerical cross-checks using synthetic experiments only."""
import unittest
from copy import deepcopy

from company import independent_validation as iv
from company import research_lab as lab
from tests.test_institutional_lab import dataset, registered


class IndependentNumericTests(unittest.TestCase):
    def setUp(self):
        self.raw = dataset()
        self.protocol = registered(self.raw)
        self.result = lab.experiment(self.protocol, self.raw)

    def test_recomputes_model_and_baseline_statistics_from_raw_labels(self):
        report = iv.audit(self.protocol, self.result, self.raw)
        self.assertTrue(report["raw_label_reconciliation"])
        self.assertTrue(report["independent_formula_reconciliation"])
        self.assertEqual(report["observations"], 250)
        self.assertFalse(report["independent_human_validation"])

    def test_fails_on_forged_reported_metric(self):
        changed = deepcopy(self.result)
        changed["out_of_sample"]["model_RMSE_bps"] += 1.
        with self.assertRaisesRegex(ValueError, "independent recomputation"):
            iv.audit(self.protocol, changed, self.raw)

    def test_fails_on_forged_prediction_even_if_score_unmodified(self):
        changed = deepcopy(self.result)
        changed["evaluation_events"][0]["model_prediction_bps"] += 1
        with self.assertRaisesRegex(ValueError, "independent recomputation"):
            iv.audit(self.protocol, changed, self.raw)

    def test_fails_on_forged_label_and_wrong_fold_count(self):
        changed = deepcopy(self.result)
        changed["evaluation_events"][0]["actual_bps"] += 1
        with self.assertRaisesRegex(ValueError, "raw source"):
            iv.audit(self.protocol, changed, self.raw)
        changed = deepcopy(self.result)
        changed["folds"][0]["test_events"] += 1
        with self.assertRaisesRegex(ValueError, "fold event counts"):
            iv.audit(self.protocol, changed, self.raw)

    def test_fails_on_duplicate_prediction_or_invalid_time(self):
        changed = deepcopy(self.result)
        changed["evaluation_events"][1]["decision_at_utc"] = changed["evaluation_events"][0]["decision_at_utc"]
        with self.assertRaises(ValueError):
            iv.audit(self.protocol, changed, self.raw)
        changed = deepcopy(self.result)
        changed["evaluation_events"][0]["label_end_at_utc"] = "2025-02-01T10:00:00+00:00"
        with self.assertRaises(ValueError):
            iv.audit(self.protocol, changed, self.raw)

    def test_source_checksum_mandatory(self):
        with self.assertRaisesRegex(ValueError, "checksum"):
            iv.audit(self.protocol, self.result, self.raw + b"bad")
