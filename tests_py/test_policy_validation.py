"""Numerical regression cases and explicitly synthetic ledger fixtures."""
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.policy_validation import (
    LedgerError, equity_path, evaluate, expected_shortfall, iid_sharpe_test,
    lower_bounds, read_ledger, sharpe_diagnostics,
)


AS_OF = 500_000_000


def fixture():
    sessions = [dict(open_ms=i*86_400_000+100, close_ms=i*86_400_000+700, completed_trades=count,
                     benchmark_net_cents=0) for i, count in enumerate([1, 0, 1, 1])]
    trades = [dict(id=str(i), feature_available_ms=sessions[i]['open_ms'], decision_ms=sessions[i]['open_ms']+1,
                   submitted_ms=sessions[i]['open_ms']+2, entry_ms=sessions[i]['open_ms']+5,
                   exit_ms=sessions[i]['close_ms'], gross_cents=gross, fees_cents=20,
                   slippage_cents=5, other_costs_cents=0, initial_risk_cents=100,
                   contracts=1, exit_reason=reason)
              for i, gross, reason in [(0, 100, 'target'), (2, -200, 'stop'), (3, 26, 'timeout')]]
    return dict(policy_id='frozen-v1', dataset_id='unit-fixture', source_kind='synthetic',
                calendar_source='four synthetic sessions', benchmark_id='cash', capital_basis='marked equity, no flows',
                evaluation_stage='holdout', policy_frozen_ms=0, initial_equity_cents=10000,
                cost_basis='reference_prices', family_size=1, independent_trial_sharpes=None,
                sessions=sessions, trades=trades)


class PolicyValidationTests(unittest.TestCase):
    def test_gross_majority_wins_negative_net_payoffs_and_timeouts_count(self):
        report = evaluate(fixture(), as_of_ms=AS_OF)
        self.assertEqual(report['total_net_cents'], -149)
        self.assertAlmostEqual(report['mean_net_cents_per_trade'], -149/3)
        self.assertAlmostEqual(report['mean_r_multiple'], -149/300)
        self.assertAlmostEqual(report['win_rate_after_costs'], 2/3)
        self.assertAlmostEqual(report['profit_factor'], 76/225)
        self.assertEqual(report['zero_trade_sessions'], 1)
        self.assertEqual(report['cost_cents'], 75)
        self.assertEqual(report['exit_reasons'], {'target': 1, 'stop': 1, 'timeout': 1})
        self.assertEqual(report['max_session_close_drawdown_cents'], 225)
        self.assertEqual(report['longest_underwater_sessions'], 2)
        self.assertEqual(report['verdict'], 'EDGE_NOT_ESTABLISHED')
        self.assertEqual(report['source_kind'], 'synthetic')

    def test_zero_trades_and_undefined_ratios(self):
        data = fixture()
        data.update(trades=[], sessions=[])
        report = evaluate(data, as_of_ms=AS_OF)
        for key in ('mean_net_cents_per_trade', 'win_rate_after_costs', 'profit_factor',
                    'per_session_sortino_zero_reference', 'worst_five_percent_mean_session_return'):
            self.assertIsNone(report[key])
        self.assertIsNone(report['sharpe']['per_session_sharpe_zero_reference'])
        self.assertIn('reason', report['inference'])
        self.assertFalse(report['trade_execution'])

    def test_duplicate_missing_future_data_and_no_double_counting_in_fills(self):
        changes = [lambda d: d['trades'].append(d['trades'][0]),
                   lambda d: d['trades'].pop(),
                   lambda d: d['trades'][0].update(feature_available_ms=5000),
                   lambda d: d['sessions'][-1].update(close_ms=AS_OF+1),
                   lambda d: d['sessions'][1].update(open_ms=699),
                   lambda d: d['sessions'][1].update(open_ms=701, close_ms=800),
                   lambda d: d['sessions'][0].update(completed_trades=3),
                   lambda d: d.update(source_kind='broker_fills'),
                   lambda d: d.update(policy_frozen_ms=d['sessions'][0]['open_ms']),
                   lambda d: d['trades'][0].update(fees_cents=None),
                   lambda d: d['trades'][0].update(slippage_cents=-1),
                   lambda d: d['trades'][0].update(initial_risk_cents=0),
                   lambda d: d['trades'][0].update(contracts=.5),
                   lambda d: d.update(cost_basis='fill_prices'),
                   lambda d: d.update(independent_trial_sharpes=[.2, .3])]
        for change in changes:
            with self.subTest(change=change):
                data = fixture()
                change(data)
                with self.assertRaises(LedgerError):
                    evaluate(data, as_of_ms=AS_OF)

    def test_no_session_returns_past_equity_exhaustion(self):
        with self.assertRaisesRegex(LedgerError, 'nonpositive'):
            equity_path(100, [-110, 40])

    def test_signed_shortfall_includes_fractional_mass(self):
        # 30 observations put 1.5 observations into the lowest 5%.
        self.assertAlmostEqual(expected_shortfall([-.3, -.15] + [0]*28), -.25)

    def test_retain_zero_sessions_in_portfolio_signal(self):
        series, _, _, _ = equity_path(10000, [100, 0, -101])
        self.assertEqual(series, [.01, 0, -.01])
        self.assertEqual(sharpe_diagnostics(series, None)['per_session_sharpe_zero_reference'], 0)

    def test_sharpe_iid_reference_matches_sharpe_frontier_appendix_a3(self):
        psr, length = iid_sharpe_test(2/math.sqrt(12), -.72, 5.78, 59.895, 1/math.sqrt(12))
        self.assertAlmostEqual(psr, .95, places=6)
        self.assertEqual(length, 60)
        _, length = iid_sharpe_test(.1, 0, 3, 60, benchmark=.2)
        self.assertIsNone(length)

    def test_no_infinite_constant_or_short_path_sharpe_confidence(self):
        report = sharpe_diagnostics([.01]*100, [.5, .7])
        self.assertTrue(all(v is None for v in report.values()))
        near_constant = [.01, math.nextafter(.01, 1.)] * 40
        self.assertIsNone(sharpe_diagnostics(near_constant, None)['per_session_sharpe_zero_reference'])
        self.assertIsNone(sharpe_diagnostics([-.01, .02], [.5, .7])['iid_dsr'])

    def test_selection_deflation_and_unknown_family(self):
        returns = [-.02, .01, .03, -.011, .002] * 12
        missing = sharpe_diagnostics(returns, None)
        self.assertIsNone(missing['iid_dsr'])
        known = sharpe_diagnostics(returns, [-.9, -.3, .3, .9])
        self.assertLess(known['iid_dsr'], known['iid_psr_vs_zero'])
        self.assertLess(known['iid_dsr'], .05)
        self.assertAlmostEqual(known['iid_selection_benchmark_sharpe'], .813238, places=2)
        one = sharpe_diagnostics(returns, [.25])
        self.assertEqual(one['iid_dsr'], one['iid_psr_vs_zero'])

    def test_session_bootstrap_paired_and_reproducible_with_search_penalty(self):
        counts = [2, 1, 0, 1, 2] * 12
        pnl = [10, -8, 0, -15, 20] * 12
        deltas = [v / 1e5 for v in pnl]
        base = lower_bounds(pnl, counts, deltas, 1, 3, 123, 1200)
        self.assertEqual(base, lower_bounds(pnl, counts, deltas, 1, 3, 123, 1200))
        multiple = lower_bounds(pnl, counts, deltas, 3, 3, 123, 1200)
        for field in ('expectancy_lower_cents_per_trade', 'mean_paired_session_return_improvement_lower'):
            self.assertLessEqual(multiple[field], base[field])
        for family in (None, 1000):
            self.assertIn('reason', lower_bounds(pnl, counts, deltas, family, 3, 123, 1200))
        self.assertIn('reason', lower_bounds([1]*60, [1]*60, [1.]*60, 1, 3, 123, 1200))

    def test_cli_records_digest_and_does_not_promote_asserted_broker_data(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'ledger.json'
            data = fixture()
            data.update(source_kind='broker_fills', cost_basis='fill_prices')
            for trade in data['trades']:
                trade['slippage_cents'] = 0
            path.write_text(json.dumps(data))
            result = subprocess.run([sys.executable, '-m', 'scripts.policy_validation', '--ledger', str(path),
                                     '--as-of-ms', str(AS_OF)], capture_output=True, check=True, text=True)
            report = json.loads(result.stdout)
            self.assertEqual(report['ledger_sha256'], read_ledger(path)[1])
            self.assertTrue(report['ledger_sha256'])
            self.assertEqual(report['source_verification'], 'user_declared_only')
            self.assertEqual(report['verdict'], 'EDGE_NOT_ESTABLISHED')
            path.write_text('{"x": 0, "x": 1}')
            with self.assertRaisesRegex(LedgerError, 'Duplicate JSON key'):
                read_ledger(path)


if __name__ == '__main__':
    unittest.main()
