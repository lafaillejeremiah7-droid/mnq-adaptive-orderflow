import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from mnq_flow.coach_ui import PAGE, check_payload, record_payload
from mnq_flow.payout_coach import config_read

CFG = Path(__file__).resolve().parents[1] / "sample" / "evaluation_25k_example.json"
AT = datetime.fromisoformat("2026-11-12T11:00:00-05:00")

def valid_input():
    return {
        "side":"long", "bias":"up", "level":"val", "reaction":"rejection",
        "absorption":"bullish", "delta5":"positive", "cvd":"rising",
        "trigger":True, "entry":"20100", "stop":"20080",
        "contracts":"1", "equity":"25000", "floor":"24000",
        "open_contracts":"0", "broker_day_net":"0",
        "broker_trades":"0", "broker_losses":"0",
    }

class UIUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = config_read(CFG)

    def test_page_contains_local_manual_controls(self):
        self.assertIn("Review a proposed setup", PAGE)
        self.assertIn("Record a completed trade", PAGE)
        self.assertNotIn("https://", PAGE)

    def test_manual_check_passes_only_for_review(self):
        result = check_payload(valid_input(), self.config, [], AT)
        self.assertTrue(result["manual_chart_checklist"]["passed"])
        self.assertEqual(result["decision"], "REVIEW_ONLY")

    def test_broken_orderflow_alignment_blocks(self):
        payload = valid_input()
        payload["delta5"] = "negative"
        result = check_payload(payload, self.config, [], AT)
        self.assertEqual(result["decision"], "BLOCK")

    def test_stop_risk_blocks(self):
        payload = valid_input()
        payload["stop"] = "20050"
        result = check_payload(payload, self.config, [], AT)
        self.assertEqual(result["decision"], "BLOCK")

    def test_invalid_side_rejected(self):
        payload = valid_input()
        payload["side"] = "both"
        with self.assertRaisesRegex(ValueError, "Invalid side"):
            check_payload(payload, self.config, [], AT)

    def test_record_then_status_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "trades.jsonl"
            result = record_payload({
                "date":"2026-11-12", "net":"75.50", "setup":"VAL rejection"
            }, journal, self.config)
            self.assertEqual(result["recorded"]["net_pnl"], 75.50)
            self.assertEqual(result["status"]["profit_remaining"], 1424.50)
            self.assertFalse(result["status"]["eligible_for_payout"])

if __name__ == "__main__":
    unittest.main()
