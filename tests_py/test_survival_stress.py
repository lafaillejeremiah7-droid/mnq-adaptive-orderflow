import copy
from datetime import date
import json
from pathlib import Path
import random
import subprocess
import sys
import unittest

from scripts import survival_stress as stress


FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "ILLUSTRATIVE_survival.json"
AS_OF = date(2025, 2, 15)


class SurvivalStressTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads(FIXTURE.read_text())
        self.spec["simulation"]["replicates"] = 10
        self.spec["rules"].update(
            initial_equity_cents=100_000, initial_eod_peak_cents=100_000,
            initial_floor_cents=90_000, daily_loss_cents=15_000,
            entry_fee_cents_per_contract=0, exit_fee_cents_per_contract=0,
            planned_slippage_ticks=0, reserve_cents=0,
        )

    def replay(self, days, **shock):
        # Each helper constructs disjoint ordered trades, one tuple of marks per trade.
        sessions = []
        for trades in days:
            sessions.append([stress.Trade(10, True, tuple(marks)) for marks in trades])
        scenario = stress.Shock.parse(dict(self.spec["scenarios"][0], **shock))
        return stress.replay(sessions, stress.Rules.parse(self.spec["rules"]), 50, scenario)

    def test_terminal_floor_touch_discards_later_recovery(self):
        result = self.replay([[[-200, 1_000], [40]], [[50]]])
        self.assertTrue(result.account_failed)
        self.assertFalse(result.daily_limit_touched)
        self.assertEqual((result.ending_equity_cents, result.sessions_seen, result.trades_opened),
                         (90_000, 1, 1))

    def test_intraday_high_does_not_ratchet_eod_floor(self):
        result = self.replay([[[400, -80, 0]]])
        self.assertFalse(result.account_failed)
        self.assertEqual((result.final_floor_cents, result.max_drawdown_cents), (90_000, 24_000))

    def test_eod_lock_and_exact_daily_floor(self):
        self.spec["rules"].update(floor_cap_cents=91_000, daily_loss_cents=4_000)
        result = self.replay([[[100]], [[-80, 1_000], [100]], [[20]]], forced_exit_ticks=2)
        self.assertTrue(result.daily_limit_touched)
        self.assertFalse(result.account_failed)
        self.assertEqual((result.proposals_skipped, result.trades_opened), (1, 3))
        self.assertEqual((result.ending_equity_cents, result.final_floor_cents), (101_900, 91_000))

    def test_forced_fill_can_convert_daily_stop_to_terminal_failure(self):
        self.spec["rules"]["daily_loss_cents"] = 3_000
        result = self.replay([[[-60, 400]], [[100]]], forced_exit_ticks=140)
        self.assertTrue(result.daily_limit_touched and result.account_failed)
        self.assertEqual((result.sessions_seen, result.ending_equity_cents), (1, 90_000))

    def test_two_trade_cap_and_loss_only_personal_budget(self):
        result = self.replay([[[1], [1], [100]]])
        self.assertEqual((result.trades_opened, result.proposals_skipped), (2, 1))
        self.spec["rules"]["personal_daily_budget_cents"] = 500
        result = self.replay([[[-1], [2]], [[1]]])
        self.assertEqual((result.trades_opened, result.proposals_skipped), (2, 1))
        self.assertEqual(result.ending_equity_cents, 100_000)

    def test_path_fee_and_stressed_stop_at_fixed_whole_size(self):
        self.spec["rules"].update(contracts=2, max_contracts=2, entry_fee_cents_per_contract=111,
                                  exit_fee_cents_per_contract=93)
        result = self.replay([[[-10]]], extra_exit_ticks=1, extra_stop_ticks=2)
        self.assertEqual(result.ending_equity_cents, 100_000 - 2 * (111 + 93 + 13 * 50))

    def test_entry_skips_threshold_equality_and_excessive_fees(self):
        self.spec["rules"]["daily_loss_cents"] = 500
        self.assertEqual(self.replay([[[50]]]).trades_opened, 0)
        self.spec["rules"].update(daily_loss_cents=15_000, entry_fee_cents_per_contract=7_501)
        self.assertEqual(self.replay([[[50]]]).trades_opened, 0)

    def test_start_at_floor_is_already_terminal(self):
        self.spec["rules"]["initial_equity_cents"] = 90_000
        result = self.replay([[[30]]])
        self.assertTrue(result.account_failed)
        self.assertEqual(result.sessions_seen, 0)

    def test_reject_partial_or_contradictory_rules(self):
        for key, value in (("contracts", 0.2), ("max_contracts", 0), ("max_trades_per_day", 3),
                           ("initial_floor_cents", 55), ("planned_slippage_ticks", True),
                           ("initial_equity_cents", None)):
            spec = copy.deepcopy(self.spec)
            spec["rules"][key] = value
            with self.subTest(key=key), self.assertRaises(stress.StressInputError):
                stress.run_stress(spec, cutoff=AS_OF)

    def test_refuse_disordered_rows_unknown_model_and_unobserved_paths(self):
        for key, value in (("model", "intraday_watermark"), ("data_kind", "live_performance"),
                           ("path_basis", "unordered_bar_high_low"), ("sessions", []),
                           ("sessions", self.spec["sessions"][::-1]), ("contract", "NQH2025")):
            with self.subTest(key=key), self.assertRaises(stress.StressInputError):
                stress.run_stress(dict(self.spec, **{key: value}), cutoff=AS_OF)
        self.spec["sessions"][0]["trades"] *= 2
        with self.assertRaisesRegex(stress.StressInputError, "overlap"):
            stress.run_stress(self.spec, cutoff=AS_OF)

    def test_reject_future_and_zero_or_iid_sample(self):
        with self.assertRaisesRegex(stress.StressInputError, "future"):
            stress.run_stress(self.spec, cutoff=date(2025, 2, 2))
        for block in (0, 1, 4):
            self.spec["simulation"]["block_sessions"] = block
            with self.assertRaises(stress.StressInputError):
                stress.run_stress(self.spec, cutoff=AS_OF)

    def test_contiguous_nonwrapping_blocks_and_original_horizon(self):
        sessions = list(range(9))
        draws = stress.session_blocks(sessions, 4, random.Random(90))
        self.assertEqual(len(draws), 9)
        for i in (0, 4):
            self.assertEqual(draws[i:i+4], list(range(draws[i], draws[i]+4)))
            self.assertLess(draws[i+3], 9)

    def test_interval_keeps_nonzero_uncertainty_and_seeded_results(self):
        self.assertGreater(stress.mc_estimate(0, 20)["mc_interval_95"][1], 0.1)
        self.assertLess(stress.mc_estimate(20, 20)["mc_interval_95"][0], 0.9)
        first = stress.run_stress(self.spec, cutoff=AS_OF)
        self.assertEqual(first, stress.run_stress(self.spec, cutoff=AS_OF))
        self.assertEqual(first["data_kind"], "synthetic")
        self.assertEqual(first["verdict"], "RESEARCH_REVIEW_ONLY")

    def test_cli_reports_synthetic_fixture_with_scenario_sensitivity(self):
        proc = subprocess.run([sys.executable, "-m", "scripts.survival_stress", str(FIXTURE)],
                              check=True, text=True, capture_output=True,
                              cwd=FIXTURE.parents[1])
        result = json.loads(proc.stdout)
        base, shock = result["scenarios"]
        self.assertFalse(base["chronological_replay"]["account_failed"])
        self.assertTrue(shock["chronological_replay"]["account_failed"])
        self.assertLess(base["simulated_paths"]["account_failure"]["fraction"],
                        shock["simulated_paths"]["account_failure"]["fraction"])


if __name__ == "__main__":
    unittest.main()
