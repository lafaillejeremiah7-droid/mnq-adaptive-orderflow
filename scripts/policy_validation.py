#!/usr/bin/env python3
"""Offline net performance diagnostics for a frozen, flat-at-session-close policy."""
import argparse
from bisect import bisect_left
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import NormalDist, fmean, median, stdev
from zoneinfo import ZoneInfo


class LedgerError(ValueError):
    """The supplied record cannot be reconciled with its evaluation assumptions."""


def integer(value, field, minimum=None):
    if type(value) is not int or abs(value) > 2**53 - 1 or (minimum is not None and value < minimum):
        raise LedgerError(f"Invalid integer for {field}")
    return value


def checked_fields(record, fields, name):
    if not isinstance(record, dict) or set(record) != set(fields.split()):
        raise LedgerError(f"Unexpected or missing fields for {name}. Expected {fields}")


def nonblank(value, field):
    if not isinstance(value, str) or not value.strip():
        raise LedgerError(f"Missing text for {field}")
    return value


def read_ledger(path):
    def unique(pairs):
        record = {}
        for key, value in pairs:
            if key in record:
                raise LedgerError(f"Duplicate JSON key {key}")
            record[key] = value
        return record

    data = path.read_bytes()
    return json.loads(data, object_pairs_hook=unique), hashlib.sha256(data).hexdigest()


def reconcile(spec, as_of_ms):
    """Assign every fill to a declared complete session and retain all zero-trade sessions."""
    checked_fields(spec, 'policy_id dataset_id source_kind calendar_source benchmark_id capital_basis '
                   'evaluation_stage policy_frozen_ms initial_equity_cents cost_basis family_size '
                   'independent_trial_sharpes sessions trades', 'ledger')
    for key in ('policy_id', 'dataset_id', 'calendar_source', 'benchmark_id', 'capital_basis'):
        nonblank(spec[key], key)
    if spec['source_kind'] not in ('synthetic', 'historical_simulation', 'paper_fills', 'broker_fills'):
        raise LedgerError('Unknown source_kind')
    if spec['evaluation_stage'] not in ('development', 'validation', 'holdout', 'forward'):
        raise LedgerError('Unknown evaluation_stage')
    if spec['cost_basis'] not in ('reference_prices', 'fill_prices'):
        raise LedgerError('Unknown cost_basis')
    if spec['source_kind'] in ('paper_fills', 'broker_fills') and spec['cost_basis'] != 'fill_prices':
        raise LedgerError('Paper and broker fills require actual fill-to-fill prices')
    capital = integer(spec['initial_equity_cents'], 'initial_equity_cents', 1)
    frozen = integer(spec['policy_frozen_ms'], 'policy_frozen_ms', 0)
    integer(as_of_ms, 'as_of_ms', 0)
    if as_of_ms > int(datetime.now(timezone.utc).timestamp() * 1000):
        raise LedgerError('As-of time is in the future')
    sessions, trades = spec['sessions'], spec['trades']
    if not isinstance(sessions, list) or not isinstance(trades, list):
        raise LedgerError('sessions and trades must be arrays')
    family = spec['family_size']
    if family is not None:
        integer(family, 'family_size', 1)
    trials = spec['independent_trial_sharpes']
    if trials is not None and (not isinstance(trials, list) or len(trials) != family or
                               any(type(x) not in (float, int) or abs(x) > 1e12 or not math.isfinite(x) for x in trials)):
        raise LedgerError('Independent trial Sharpes must cover the entire declared family')
    closes = []
    previous_date = None
    market_tz = ZoneInfo('America/New_York')
    for session in sessions:
        checked_fields(session, 'open_ms close_ms completed_trades benchmark_net_cents', 'session')
        start = integer(session['open_ms'], 'open_ms', 0)
        close = integer(session['close_ms'], 'close_ms', 0)
        if not frozen < start < close <= as_of_ms or (closes and start <= closes[-1]):
            raise LedgerError('Session overlaps, predates policy freeze or closes after as-of')
        close_date = datetime.fromtimestamp(close / 1000, market_tz).date()
        if close_date == previous_date:
            raise LedgerError('Expected one complete evaluation session per Eastern close date')
        previous_date = close_date
        if integer(session['completed_trades'], 'completed_trades', 0) > 2:
            raise LedgerError('Session exceeds personal two-trade limit')
        integer(session['benchmark_net_cents'], 'benchmark_net_cents')
        closes.append(close)
    day_nets = [0] * len(sessions)
    counts = [0] * len(sessions)
    seen_ids = set()
    net_trades = []
    r_multiples = []
    costs = 0
    contracts = 0
    exits = Counter()
    for trade in trades:
        checked_fields(trade, 'id feature_available_ms decision_ms submitted_ms entry_ms exit_ms '
                       'gross_cents fees_cents slippage_cents other_costs_cents initial_risk_cents contracts exit_reason', 'trade')
        trade_id = nonblank(trade['id'], 'id')
        if trade_id in seen_ids:
            raise LedgerError(f'Duplicate trade ID {trade_id}')
        seen_ids.add(trade_id)
        available, decision, submit, entry, exit_ms = [integer(trade[k], k, 0) for k in
            ('feature_available_ms', 'decision_ms', 'submitted_ms', 'entry_ms', 'exit_ms')]
        day = bisect_left(closes, exit_ms)
        if (day == len(sessions) or decision < sessions[day]['open_ms'] or
                not available <= decision <= submit <= entry < exit_ms):
            raise LedgerError(f'Out-of-session or noncausal timestamps for {trade_id}')
        gross = integer(trade['gross_cents'], 'gross_cents')
        fees, slip, other = [integer(trade[k], k, 0) for k in ('fees_cents', 'slippage_cents', 'other_costs_cents')]
        if spec['cost_basis'] == 'fill_prices' and slip:
            raise LedgerError('Fill-to-fill gross already incorporates execution slippage')
        cost = fees + slip + other
        net = gross - cost
        risk = integer(trade['initial_risk_cents'], 'initial_risk_cents', 1)
        contracts += integer(trade['contracts'], 'contracts', 1)
        costs += cost
        exits[nonblank(trade['exit_reason'], 'exit_reason')] += 1
        day_nets[day] += net
        counts[day] += 1
        net_trades.append(net)
        r_multiples.append(net / risk)
    if counts != [s['completed_trades'] for s in sessions]:
        raise LedgerError('Ledger does not match declared session completed-trade counts')
    return capital, day_nets, counts, net_trades, r_multiples, costs, contracts, dict(exits)


def equity_path(initial_cents, daily_net):
    equity = peak = initial_cents
    worst = duration = longest = 0
    worst_fraction = 0.0
    returns = []
    for net in daily_net:
        if equity <= 0:
            raise LedgerError('Further observations after nonpositive marked equity')
        returns.append(net / equity)
        equity += net
        peak = max(peak, equity)
        depth = peak - equity
        duration = duration + 1 if depth else 0
        longest = max(longest, duration)
        worst = max(worst, depth)
        worst_fraction = max(worst_fraction, depth / peak)
    return returns, worst, worst_fraction, longest


def iid_sharpe_test(sr, skew, kurtosis, n, benchmark=0.0):
    """Bailey/Lopez de Prado PSR and minimum observations, at native return frequency."""
    variance_term = 1 - skew * sr + (kurtosis - 1) * sr**2 / 4
    if variance_term <= 0 or n < 2:
        return None, None
    difference = sr - benchmark
    psr = NormalDist().cdf(difference * math.sqrt((n - 1) / variance_term))
    length = None
    if difference > 0:
        length = math.ceil(1 + variance_term * (NormalDist().inv_cdf(.95) / difference)**2)
    return psr, length


def sharpe_diagnostics(returns, trial_sharpes):
    result = {'per_session_sharpe_zero_reference': None, 'iid_psr_vs_zero': None,
              'iid_minimum_sessions_95pct_vs_zero': None, 'iid_dsr': None,
              'iid_selection_benchmark_sharpe': None}
    if len(returns) < 2 or min(returns) == max(returns):
        return result
    mu = fmean(returns)
    sd = stdev(returns)
    if sd <= 32 * math.ulp(max(abs(r) for r in returns)):
        return result
    sr = mu / sd
    result['per_session_sharpe_zero_reference'] = sr
    # Higher empirical moments and asymptotic inference are unstable on short paths.
    if len(returns) < 30:
        return result
    centered = [v - mu for v in returns]
    moment_sd = math.sqrt(fmean(v*v for v in centered))
    skew = fmean((v / moment_sd)**3 for v in centered)
    kurt = fmean((v / moment_sd)**4 for v in centered)
    result['iid_psr_vs_zero'], result['iid_minimum_sessions_95pct_vs_zero'] = iid_sharpe_test(sr, skew, kurt, len(returns))
    if trial_sharpes:
        count = len(trial_sharpes)
        if count == 1:
            benchmark = 0.0
        else:
            sigma = stdev(trial_sharpes)
            if sigma == 0:
                return result
            gamma = .5772156649015329
            normal = NormalDist()
            benchmark = sigma * ((1-gamma)*normal.inv_cdf(1-1/count)
                                 + gamma*normal.inv_cdf(1-1/(count*math.e)))
        result['iid_selection_benchmark_sharpe'] = benchmark
        result['iid_dsr'], _ = iid_sharpe_test(sr, skew, kurt, len(returns), benchmark)
    return result


def lower_bounds(day_nets, counts, return_deltas, family, block, seed, draws):
    """Paired circular moving-block percentile bounds for two endpoints per tested policy."""
    integer(block, 'block_sessions', 2)
    integer(seed, 'seed', 0)
    integer(draws, 'draws', 1)
    n = len(counts)
    if family is None:
        return {'reason': 'Search history missing'}
    alpha = .05 / (2 * family)
    if n < 30 or n // block < 10 or sum(counts) < 2:
        return {'reason': 'Need 30 sessions, 10 block lengths and two completed trades'}
    if alpha * draws < 10:
        return {'reason': 'Too few bootstrap draws for the family-adjusted tail'}
    rng = random.Random(seed)
    mean_nets, paired_means = [], []
    # Prefix sums allow each circular block to be sampled in constant time.
    prefixes = []
    for values in (day_nets, counts, return_deltas):
        prefix = [0]
        for v in values * 2:
            prefix.append(prefix[-1] + v)
        prefixes.append(prefix)
    for _ in range(draws):
        totals = [0, 0, 0.0]
        for offset in range(0, n, block):
            start = rng.randrange(n)
            end = start + min(block, n - offset)
            for j, prefix in enumerate(prefixes):
                totals[j] += prefix[end] - prefix[start]
        if totals[1] == 0:
            return {'reason': 'Resample lacked trades; expectancy bound withheld'}
        mean_nets.append(totals[0] / totals[1])
        paired_means.append(totals[2] / n)
    if min(mean_nets) == max(mean_nets) or min(paired_means) == max(paired_means):
        return {'reason': 'Degenerate resampling distribution; uncertainty unavailable'}
    index = max(0, math.floor(alpha * draws) - 1)
    return {'one_sided_alpha_per_endpoint': alpha,
            'expectancy_lower_cents_per_trade': sorted(mean_nets)[index],
            'mean_paired_session_return_improvement_lower': sorted(paired_means)[index]}


def expected_shortfall(returns):
    """Signed mean of the worst 5% including fractional weight at the boundary."""
    if not returns:
        return None
    ordered = sorted(returns)
    weight = len(ordered) / 20
    count = int(weight)
    return (sum(ordered[:count]) + (weight - count) * ordered[count]) / weight


def evaluate(spec, *, as_of_ms, block_sessions=3, seed=247, draws=3999):
    capital, daily, counts, nets, multiples, costs, contracts, exits = reconcile(spec, as_of_ms)
    returns, depth, depth_fraction, duration = equity_path(capital, daily)
    baseline, *_ = equity_path(capital, [s['benchmark_net_cents'] for s in spec['sessions']])
    deltas = [r-b for r, b in zip(returns, baseline)]
    losses = [v for v in nets if v < 0]
    wins = [v for v in nets if v > 0]
    downside = math.sqrt(fmean(min(0, r)**2 for r in returns)) if returns else 0
    return {
        'verdict': 'EDGE_NOT_ESTABLISHED', 'trade_execution': False,
        'source_verification': 'user_declared_only', 'source_kind': spec['source_kind'],
        'evaluation_stage': spec['evaluation_stage'], 'as_of_ms': as_of_ms,
        'dataset_id': spec['dataset_id'], 'policy_id': spec['policy_id'], 'benchmark_id': spec['benchmark_id'],
        'session_count': len(returns), 'zero_trade_sessions': counts.count(0), 'trade_count': len(nets),
        'contracts_round_tripped': contracts, 'exit_reasons': exits, 'cost_cents': costs,
        'total_net_cents': sum(nets), 'mean_net_cents_per_trade': fmean(nets) if nets else None,
        'median_net_cents_per_trade': median(nets) if nets else None, 'mean_r_multiple': fmean(multiples) if nets else None,
        'win_rate_after_costs': len(wins)/len(nets) if nets else None,
        'average_win_cents': fmean(wins) if wins else None, 'average_loss_cents': fmean(losses) if losses else None,
        'payoff_ratio': fmean(wins)/-fmean(losses) if wins and losses else None,
        'profit_factor': sum(wins)/-sum(losses) if losses else None,
        'max_session_close_drawdown_cents': depth, 'max_session_close_drawdown_fraction': depth_fraction,
        'longest_underwater_sessions': duration, 'mean_paired_session_return_improvement': fmean(deltas) if deltas else None,
        'per_session_sortino_zero_reference': fmean(returns)/downside if downside else None,
        'worst_five_percent_mean_session_return': expected_shortfall(returns),
        'sharpe': sharpe_diagnostics(returns, spec['independent_trial_sharpes']),
        'inference': {'block_sessions': block_sessions, 'draws': draws, 'seed': seed, 'family_size': spec['family_size'],
                      **lower_bounds(daily, counts, deltas, spec['family_size'], block_sessions, seed, draws)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--as-of-ms', type=int, help='Historical evaluation cutoff, UTC epoch milliseconds')
    parser.add_argument('--block-sessions', type=int, default=3)
    parser.add_argument('--seed', type=int, default=247)
    parser.add_argument('--draws', type=int, default=3999)
    args = parser.parse_args()
    try:
        now = int(datetime.now(timezone.utc).timestamp()*1000)
        as_of = now if args.as_of_ms is None else args.as_of_ms
        ledger, digest = read_ledger(args.ledger)
        report = evaluate(ledger, as_of_ms=as_of, block_sessions=args.block_sessions, seed=args.seed, draws=args.draws)
        report['ledger_sha256'] = digest
        print(json.dumps(report, indent=2, allow_nan=False))
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Invalid policy ledger: {exc}\n')


if __name__ == '__main__':
    main()
