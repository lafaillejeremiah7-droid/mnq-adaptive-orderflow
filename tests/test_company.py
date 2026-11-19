import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from company import config_digest, ingest, open_ledger, validate_config
from solana_paper import account_report, scout


class PaperDesk(unittest.TestCase):
    def setUp(self):
        self.c = json.loads(Path("examples/paper.json").read_text())
        self.quotes = [
            json.loads(line)
            for line in Path("examples/quotes.jsonl").read_text().splitlines()
        ]
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "desk.sqlite"
        self.db = open_ledger(self.path)
        self.addCleanup(lambda: self.db.close())

    def tick(self, q):
        return ingest(self.db, self.c, config_digest(self.c, "test"), q, q["ts"])

    def test_next_quote_roundtrip_restart_and_idempotence(self):
        for q in self.quotes[:4]:
            self.assertEqual(self.tick(q)["action"], "observe")
        self.db.close()
        self.db = open_ledger(self.path)
        self.assertIsNone(self.tick(self.quotes[3]))
        events = [self.tick(q) for q in self.quotes[4:]]
        self.assertEqual(
            [e["action"] for e in events], ["paper_buy", "observe", "paper_sell"]
        )
        self.assertEqual(events[-1]["cash"], "1000.524890650")
        report = account_report(self.db, self.c, self.quotes[-1]["ts"])
        self.assertEqual((report["observations"], report["closed_trades"]), (7, 1))

    def test_failed_event_rolls_back_and_old_or_future_input_rejected(self):
        q = self.quotes[0]
        self.tick(q)
        for changes in (
            {"ask": "1"},
            {"ts": q["ts"] - 1},
            {"asset": "other"},
            {"bid": "NaN"},
        ):
            with self.assertRaises(ValueError):
                self.tick(dict(q, **changes))
        for now in (q["ts"] - 1, q["ts"] + 40):
            with self.assertRaises(ValueError):
                ingest(self.db, self.c, config_digest(self.c, "test"), q, now)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM journal").fetchone()[0], 1
        )

    def test_daily_halt_and_partial_exit(self):
        self.c["daily_loss_usd"] = "0.5"
        for q in self.quotes[:5]:
            self.tick(q)
        sell = dict(self.quotes[5], bid="90", ask="90")
        event = self.tick(sell)
        self.assertTrue(event["halted"])
        partial = self.tick(dict(sell, ts=sell["ts"] + 1, bid_size="0.01"))
        self.assertEqual(partial["qty"], "0.010000")
        self.assertEqual(partial["pending"]["side"], "sell")
        self.assertIsNone(self.tick(dict(sell, ts=sell["ts"] + 2))["position"])

    def test_expired_pending_and_config_mismatch(self):
        for q in self.quotes[:4]:
            self.tick(q)
        self.assertEqual(
            self.tick(dict(self.quotes[4], ts=self.quotes[4]["ts"] + 60))["action"],
            "observe",
        )
        self.c["order_usd"] = "1"
        with self.assertRaises(ValueError):
            self.tick(self.quotes[-1])

    def test_sol_quote_direction_and_size(self):
        c = json.loads(Path("examples/solana-forward.json").read_text())
        validate_config(c)
        with patch("solana_paper.quote_amount", side_effect=[10000000, 9900000]) as fn:
            q = scout(c)
        self.assertEqual(q["bid_size"], "100.00000")
        self.assertGreater(float(q["ask"]), float(q["bid"]))
        self.assertEqual(fn.call_args_list[0].args[0], fn.call_args_list[1].args[1])
