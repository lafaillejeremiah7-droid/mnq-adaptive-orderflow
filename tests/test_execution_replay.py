"""Offline deterministic synthetic top-of-book scenario tests."""
import csv
import hashlib
import io
import unittest
from copy import deepcopy

from company import execution_replay as er

BASE = 1_736_000_000_000_000_000


def quotes(rows, contract="MNQH5"):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(er.FIELDS)
    for row in rows:
        writer.writerow((row[0], row[1], contract, *row[2:]))
    return out.getvalue().encode()


def spec(raw, contract="MNQH5", **updates):
    baseline = {
        "contract": contract, "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_kind": "synthetic", "provider": "synthetic test rows",
        "schema": "top_of_book_v1", "rights_status": "unverified",
        "fees_per_contract_usd": "1.25",
        "conservative_slippage_ticks": 2,
        "max_quote_age_ns": 5 * er.NANO,
        "max_spread_ticks": 10, "max_records": 1000,
    }
    return {**baseline, **updates}


def intentions(ns=BASE + 100_000_000, side="BUY", contracts=2, latency_ns=0):
    return [{"decision_ns": ns, "side": side,
             "contracts": contracts, "latency_ns": latency_ns}]


Q = (BASE, BASE + 100, 80000, 5, 80002, 5, 100)


class TopOfBookScenarioTests(unittest.TestCase):
    def test_buy_uses_received_ask_spread_and_conservative_cost_mnq(self):
        raw = quotes([Q])
        result = er.simulate(raw, spec(raw), intentions())
        event = result["events"][0]
        self.assertEqual(event["status"], "hypothetical_market_order_fill")
        self.assertEqual(event["scenario_execution_ticks"], 80004)
        # 2 contracts: (1 half-spread + 2 slippage)*$0.50 + $1.25 fee = $5.50
        self.assertEqual(event["scenario_cost_vs_quoted_mid_usd"], "5.50")
        self.assertFalse(event["fill_guaranteed"])
        self.assertFalse(result["actual_exchange_fills_verified"])

    def test_nq_tick_dollars_and_sell_pricing(self):
        raw = quotes([Q], contract="NQH5")
        result = er.simulate(raw, spec(raw, "NQH5", fees_per_contract_usd="0"),
                             intentions(side="SELL", contracts=2))
        event = result["events"][0]
        self.assertEqual(event["scenario_execution_ticks"], 79998)
        self.assertEqual(event["scenario_cost_vs_quoted_mid_usd"], "30.00")

    def test_rejects_future_or_stale_quotes(self):
        raw = quotes([Q])
        no_quote = er.simulate(raw, spec(raw), intentions(ns=BASE))
        self.assertEqual(no_quote["events"][0]["reason"], "no_received_quote_by_arrival")
        stale = er.simulate(raw, spec(raw, max_quote_age_ns=1),
                            intentions(ns=BASE + 1000))
        self.assertEqual(stale["events"][0]["reason"], "stale_top_of_book")
        # Added latency allows the historical receive snapshot to exist.
        later = er.simulate(raw, spec(raw), intentions(ns=BASE, latency_ns=100))
        self.assertEqual(later["scenarios_with_assumed_fill"], 1)

    def test_refuses_crossed_book_overwide_spread_and_depleted_size(self):
        bad = quotes([(BASE, BASE + 100, 80004, 5, 80002, 5, 100)])
        with self.assertRaisesRegex(ValueError, "crossed"):
            er.simulate(bad, spec(bad), intentions())
        raw = quotes([Q])
        too_wide = er.simulate(raw, spec(raw, max_spread_ticks=1), intentions())
        self.assertEqual(too_wide["events"][0]["reason"], "spread_exceeds_limit")
        two = er.simulate(raw, spec(raw), intentions(contracts=4) + intentions(contracts=4))
        self.assertEqual(two["events"][1]["reason"], "insufficient_unconsumed_displayed_top_size")

    def test_rejects_time_reversal_wrong_contract_hash_and_schema(self):
        bad_order = quotes([Q, (BASE - 1, BASE + 90, 80000, 5, 80002, 5, 101)])
        with self.assertRaisesRegex(ValueError, "strictly"):
            er.read_quotes(bad_order, spec(bad_order))
        raw = quotes([Q])
        for change in (
            {"contract": "NQH5"}, {"schema": "bars"},
            {"fees_per_contract_usd": "-2"},
            {"max_quote_age_ns": 0},
            {"source_sha256": "0" * 64},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                er.simulate(raw, spec(raw, **change), intentions())
        faulty = deepcopy(intentions())
        faulty[0]["side"] = "LIMIT_BUY"
        with self.assertRaisesRegex(ValueError, "BUY/SELL"):
            er.simulate(raw, spec(raw), faulty)

    def test_read_quotes_distinguishes_event_and_receive_time(self):
        raw = quotes([(BASE, BASE + 10**9, 80000, 10, 80001, 10, 1)])
        before_received = er.simulate(raw, spec(raw), intentions(ns=BASE + 50))
        self.assertEqual(before_received["events"][0]["reason"], "no_received_quote_by_arrival")
        received = er.simulate(raw, spec(raw), intentions(ns=BASE + 10**9 + 1))
        self.assertEqual(received["scenarios_with_assumed_fill"], 1)
