import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import audit
import quantlab
import researcher

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "examples/protocol.json"
BARS = ROOT / "examples/bars.csv"


class EngineTests(unittest.TestCase):
    def evaluate(self, raw=None, **changes):
        raw = BARS.read_bytes() if raw is None else raw
        spec = {**quantlab.read(SPEC), **changes, "data_sha256":quantlab.digest(raw)}
        quantlab.validate(spec)
        return quantlab.backtest(spec, raw)

    def test_stop_first_and_exact_costs(self):
        r = self.evaluate()
        self.assertEqual([t["side"] for t in r["trades"]], [1,-1])
        self.assertEqual([t["exit_reason"] for t in r["trades"]], ["stop","target"])
        self.assertEqual((r["ambiguous_bars"], r["gross_cents"], r["cost_cents"], r["net_cents"]), (1,0,2200,-2200))
        self.assertEqual(r["target_first_sensitivity_cents"],1800)
        self.assertEqual(r["closed_trade_drawdown_cents"],3100)

    def test_micro_and_efutures_units(self):
        r = self.evaluate(BARS.read_bytes().replace(b"NQH5", b"MNQH5"), instrument="MNQ", contract="MNQH5")
        self.assertEqual([t["net_cents"] for t in r["trades"]], [-400,0])

    def test_no_prior_bar_from_outside_window_or_across_gap(self):
        self.assertEqual(self.evaluate(start="2025-01-02T15:01:00Z")["trade_count"],1)
        raw = BARS.read_bytes().replace(b"15:03:",b"15:04:")
        self.assertEqual(self.evaluate(raw,end="2025-01-02T15:05:00Z")["trade_count"],1)

    def test_invalid_prices_timestamp_or_contract(self):
        for a,b in [(b"21001",b"21001.1"),(b"15:03:",b"15:01:"),(b"NQH5",b"NQM5")]:
            with self.subTest(b=b), self.assertRaises(ValueError):
                self.evaluate(BARS.read_bytes().replace(a,b))

    def test_follow_and_fade(self):
        self.assertEqual([t["side"] for t in self.evaluate(direction="fade")["trades"]],[-1,1])

    def test_launcher_selects_separate_roles(self):
        self.assertIn("read-only", researcher.command("reviewer","inspect",ROOT))
        self.assertIn("workspace-write", researcher.command("researcher","design",ROOT))


class JournalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.ledger = Path(temp.name)
        self.call("register", SPEC)

    def call(self,*args,ok=True,script="quantlab.py"):
        r = subprocess.run([sys.executable,str(ROOT/script),"--ledger",str(self.ledger),*map(str,args)],capture_output=True,text=True)
        self.assertEqual(r.returncode==0,ok,r.stderr)
        return r.stdout

    def test_replay_and_receipt_in_clean_clone(self):
        self.call("run","fixture-001",BARS)
        self.call("publish","fixture-001",script="audit.py")
        path = self.ledger/"fixture-001"/"result.json"
        original=path.read_bytes()
        path.unlink()
        self.call("verify","fixture-001",BARS,script="audit.py")
        self.assertEqual(path.read_bytes(),original)
        self.call("replay","fixture-001",BARS)
        self.call("register",SPEC,ok=False)
        self.call("run","fixture-001",BARS,ok=False)

    def test_rejection_pinned_to_result(self):
        self.call("run","fixture-001",BARS)
        p=self.ledger/"review-input.json"
        verdict=dict(reviewer="test",findings="fixture",verdict="reject",result_sha256="wrong")
        p.write_text(json.dumps(verdict))
        self.call("review","fixture-001",p,ok=False)
        verdict["result_sha256"]=quantlab.digest((self.ledger/"fixture-001/result.json").read_bytes())
        p.write_text(json.dumps({**verdict,"verdict":"retain_for_paper"}))
        self.call("review","fixture-001",p,ok=False)
        p.write_text(json.dumps(verdict))
        self.call("review","fixture-001",p)
        self.call("review","fixture-001",p,ok=False)

    def test_failed_attempt_consumes_window(self):
        self.call("run","fixture-001",SPEC,ok=False)
        self.assertTrue((self.ledger/"fixture-001/failed.json").is_file())
        path = self.ledger/"next.json"
        path.write_text(json.dumps({**quantlab.read(SPEC),"id":"new-attempt"}))
        self.call("register",path)
        self.call("run","new-attempt",BARS,ok=False)
