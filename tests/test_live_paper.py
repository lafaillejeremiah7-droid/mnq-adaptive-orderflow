import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from company import config_digest, ingest, open_ledger
from live_paper import checkpoint
from solana_paper import account_report


class LivePaperTests(unittest.TestCase):
    def test_wall_clock_signal_and_next_quote_fills_survive_checkpoint(self):
        c = json.loads(Path("examples/paper.json").read_text())
        c["max_gap_seconds"] = 3600
        q = json.loads(Path("examples/quotes.jsonl").read_text().splitlines()[0])
        start = q["ts"]
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            db = open_ledger(folder / "ledger.sqlite")
            try:

                def tick(seconds, price):
                    quote = {
                        **q,
                        "ts": start + seconds,
                        "bid": str(price),
                        "ask": str(price),
                    }
                    return ingest(
                        db,
                        c,
                        config_digest(c, "live-test"),
                        quote,
                        quote["ts"],
                        live=True,
                    )

                for seconds in (0, 15, 30, 45):
                    e = tick(seconds, 100 if seconds == 0 else 102)
                    self.assertIsNone(e["pending"])
                self.assertEqual(tick(2700, 102)["pending"]["side"], "buy")
                self.assertEqual(tick(2715, 102)["action"], "paper_buy")
                self.assertEqual(tick(2730, 108)["pending"]["side"], "sell")
                before = account_report(db, c, start + 2730)
                checkpoint(folder, c, before)
                self.assertEqual(account_report(db, c, start + 2730), before)
                self.assertEqual(tick(2745, 108)["action"], "paper_sell")
                after = account_report(db, c, start + 2745)
                checkpoint(folder, c, after)
                checkpoint(folder, c, after)
                self.assertEqual(after, account_report(db, c, start + 2745))
                self.assertEqual(after["observations"], 8)
                self.assertEqual(after["closed_trades"], 1)
                lines = [
                    line
                    for path in folder.glob("journal/*/*.gz")
                    for line in gzip.decompress(path.read_bytes()).splitlines()
                ]
                self.assertEqual(len(lines), 8)
            finally:
                db.close()
