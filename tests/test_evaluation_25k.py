"""25K evaluation rules derived from user-provided plan screenshot."""
import json
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from mnq_flow.manual_coach import checklist
from mnq_flow.payout_coach import config_read, risk_check, summary

CONFIG_PATH = Path(__file__).resolve().parents[1] / "sample" / "evaluation_25k_example.json"
TIME = datetime.fromisoformat("2026-11-12T11:00:00-05:00")

def candidate(config, rows=None, **override):
    values = {
        "side":"long", "entry":Decimal("20100"), "stop":Decimal("20090"),
        "contracts":1, "equity":Decimal("25000"), "floor":Decimal("24000"),
        "open_contracts":0, "broker_day_net":Decimal("0"), "broker_trades":0,
        "broker_losses":0, "at":TIME, "setup":"long_candidate",
    }
    values.update(override)
    return risk_check(config, rows or [], **values)

class Plan25KTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = config_read(CONFIG_PATH)

    def test_correct_target_and_no_consistency(self):
        self.assertEqual(self.config["starting_balance"], 25000)
        self.assertEqual(self.config["evaluation_target"], 1500)
        self.assertIsNone(self.config["evaluation_consistency"])
        self.assertEqual(self.config["firm_daily_loss_limit"], 600)
        self.assertEqual(self.config["firm_max_mnq_contracts"], 10)

    def test_progress_no_consistency_hurdle(self):
        rows = [
            {"date":"2026-11-02", "net_pnl":Decimal("1400")},
            {"date":"2026-11-03", "net_pnl":Decimal("100")},
        ]
        result = summary(self.config, rows)
        self.assertEqual(result["profit_remaining"], 0)
        self.assertIsNone(result["consistency_met"])
        self.assertFalse(result["eligible_for_payout"])

    def test_default_manual_one_mnq_can_pass_risk_gate(self):
        result = candidate(self.config)
        self.assertEqual(result["decision"], "REVIEW_ONLY")
        self.assertEqual(result["personal_max_mnq_contracts"], 1)
        self.assertEqual(result["firm_max_mnq_contracts"], 10)

    def test_two_mnq_blocked_by_personal_rule(self):
        self.assertEqual(candidate(self.config, contracts=2)["decision"], "BLOCK")

    def test_11_mnq_blocked_even_if_personal_limit_raised(self):
        changed = dict(self.config, max_mnq_contracts=10)
        self.assertEqual(candidate(changed, contracts=11)["decision"], "BLOCK")

    def test_daily_loss_limit_blocks_even_if_personal_limit_raised(self):
        changed = dict(self.config, personal_daily_stop=900)
        rows = [{"date":"2026-11-12", "net_pnl":Decimal("-590")}]
        result = candidate(
            changed, rows=rows, broker_day_net=Decimal("-590"),
            broker_trades=1, broker_losses=1, stop=Decimal("20080"),
        )
        self.assertEqual(result["decision"], "BLOCK")
        self.assertLessEqual(result["available_risk_budget_usd"], 10)

    def test_breached_firm_daily_limit(self):
        changed = dict(self.config, personal_daily_stop=900)
        rows = [{"date":"2026-11-12", "net_pnl":Decimal("-605")}]
        result = candidate(changed, rows=rows,
                           broker_day_net=Decimal("-605"), broker_trades=1)
        self.assertIn("Firm daily loss limit reached", result["reasons"])

    def test_approaching_eod_floor_blocks(self):
        result = candidate(self.config, equity=Decimal("24100"))
        self.assertEqual(result["decision"], "BLOCK")

    def test_target_reached_blocks_new_trades(self):
        rows = [{"date":"2026-11-10", "net_pnl":Decimal("1500")}]
        result = candidate(self.config, rows=rows)
        self.assertIn(
            "Recorded evaluation target reached; stop and verify firm results",
            result["reasons"],
        )

    def test_manual_chart_input_rejects_conflict(self):
        good = checklist(
            "long", "up", "val", "rejection", "bullish", "positive", "rising", True
        )
        self.assertTrue(good["passed"])
        self.assertFalse(
            checklist("long", "up", "val", "rejection", "bullish", "negative", "rising", True)["passed"]
        )

if __name__ == "__main__":
    unittest.main()
