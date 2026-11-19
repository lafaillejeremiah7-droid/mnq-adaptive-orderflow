import unittest
from collections import defaultdict
from scripts.mnq_adaptive_failed_break import signal, session


class AdaptiveStudy(unittest.TestCase):
    def test_single_sweep_and_release(self):
        bars = [(100,105,95,100,1)]*330
        bars[30] = (100,106,94,99,1)
        self.assertIsNone(signal(bars))
        bars[31] = (98,104,93,99,1)
        self.assertEqual(signal(bars)[:2],(32,1))
        past = defaultdict(list)
        row = session("2024-06-03","MNQM4",bars,past)
        event = past["MNQM4","LONG"][0]
        self.assertEqual(event.outcome,"TIME_LIMIT")
        self.assertEqual(event.resolved_at_ms-event.detected_at_ms,1800000)
        self.assertTrue(row["every"])
        self.assertFalse(row["adaptive"])

    def test_skipped_labels_train_only_matching_contract(self):
        bars = [(100,105,95,100,1)]*330
        bars[30] = (100,104,94,99,1)
        bars[31] = (100,173,99,101,1)
        past = defaultdict(list)
        for i in range(1,12):
            r = session(f"2024-06-{i:02}","MNQM4",bars,past)
            self.assertEqual(r["adaptive"],i>10)
        self.assertFalse(session("2024-06-12","MNQU4",bars,past)["adaptive"])
