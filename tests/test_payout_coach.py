import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from mnq_flow.payout_coach import risk_check, summary, config_read, last_signal

CFG = {
    "stage": "funded", "starting_balance": 50000,
    "risk_per_trade": 125, "personal_daily_stop": 250,
    "max_trades_per_day": 2, "max_mnq_contracts": 2,
    "max_consecutive_losses": 2, "roundtrip_cost_per_contract": 2.5,
    "slippage_ticks_per_contract": 2, "drawdown_reserve_usd": 100,
    "winning_days_required": 5, "winning_day_minimum": 200,
    "minimum_payout": 500, "maximum_payout": 2000,
    "payout_fraction": 0.5, "trader_share": 0.90,
    "evaluation_target": None, "evaluation_consistency": None
}
AT = datetime.fromisoformat("2026-11-12T11:00:00-05:00")

def check(**changes):
    opts = dict(side="long", entry=Decimal("20100"), stop=Decimal("20075"),
                contracts=2, equity=Decimal("50200"), floor=Decimal("48800"),
                open_contracts=0, broker_day_net=Decimal("0"),
                broker_trades=0, broker_losses=0, at=AT, setup="long_candidate")
    opts.update(changes)
    return risk_check(CFG, [], **opts)

class PayoutCoachTests(unittest.TestCase):
    def test_five_winning_days_needed(self):
        rows = [{"date": f"2026-11-{day:02d}", "net_pnl": Decimal("250")}
                for day in (2, 3, 4, 5)]
        self.assertFalse(summary(CFG, rows)["eligible_for_payout"])
        rows.append({"date": "2026-11-06", "net_pnl": Decimal("250")})
        result = summary(CFG, rows)
        self.assertTrue(result["eligible_for_payout"])
        self.assertEqual(result["maximum_theoretical_payout_request"], 625)

    def test_one_big_day_not_five_days(self):
        rows = [{"date": "2026-11-02", "net_pnl": Decimal("1200")}]
        self.assertEqual(summary(CFG, rows)["winning_days_count"], 1)

    def test_evaluation_cannot_payout(self):
        cfg = dict(CFG, stage="evaluation", evaluation_target=3000, evaluation_consistency=0.5)
        result = summary(cfg, [{"date": "2026-11-02", "net_pnl": Decimal("1000")}])
        self.assertFalse(result["eligible_for_payout"])
        self.assertEqual(result["profit_remaining"], 2000)
        self.assertFalse(result["consistency_met"])

    def test_safe_trade_review_only(self):
        self.assertEqual(check()["decision"], "REVIEW_ONLY")

    def test_risk_exceeded_blocks(self):
        self.assertEqual(check(stop=Decimal("20050"))["decision"], "BLOCK")

    def test_near_floor_blocks(self):
        self.assertEqual(check(equity=Decimal("48850"))["decision"], "BLOCK")

    def test_open_contracts_blocks(self):
        self.assertEqual(check(open_contracts=1)["decision"], "BLOCK")

    def test_no_signal_blocks(self):
        self.assertEqual(check(setup="none")["decision"], "BLOCK")

    def test_wrong_direction_blocks(self):
        self.assertEqual(check(side="short")["decision"], "BLOCK")

    def test_friday_blocks(self):
        dt = datetime.fromisoformat("2026-11-13T11:00:00-05:00")
        self.assertEqual(check(at=dt)["decision"], "BLOCK")

    def test_journal_broker_mismatch_blocks(self):
        self.assertEqual(check(broker_day_net=Decimal("-40"))["decision"], "BLOCK")

    def test_bad_stop_blocks(self):
        self.assertEqual(check(stop=Decimal("20110"))["decision"], "BLOCK")

    def test_two_losses_blocks(self):
        self.assertEqual(check(broker_losses=2)["decision"], "BLOCK")

    def test_config_file(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(CFG))
            self.assertEqual(config_read(path)["stage"], "funded")

    def test_stale_signal_not_accepted(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshots.jsonl"
            path.write_text(json.dumps({"asof":"2026-11-12T10:00:00-05:00",
                                        "signal":"long_candidate"}) + "\n")
            self.assertEqual(last_signal(path, AT), "none")

if __name__ == "__main__":
    unittest.main()
