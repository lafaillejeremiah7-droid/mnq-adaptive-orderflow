"""Synthetic adversarial checks for path-dependent NQ/MNQ risk research."""
import csv
import hashlib
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from company import risk_research as risk


def fake_history(sign=1, contract="MNQ"):
    out=io.StringIO()
    writer=csv.writer(out,lineterminator="\n")
    writer.writerow(risk.COLUMNS)
    day=date(2025,1,6)
    for i in range(12):
        while day.weekday()>4:
            day+=timedelta(days=1)
        writer.writerow([day.isoformat(),1,contract,sign*8])
        writer.writerow([day.isoformat(),2,contract,sign*8])
        day+=timedelta(days=1)
    return out.getvalue().encode()


def params(raw, **change):
    return {
      "id":"path-dependent-risk-synthetic-001",
      "source_sha256":hashlib.sha256(raw).hexdigest(),
      "source_kind":"synthetic",
      "source_rights":"unverified",
      "contract":"MNQ",
      "starting_balance_usd":1000,
      "profit_target_usd":10,
      "maximum_drawdown_usd":20,
      "drawdown_mode":"static",
      "eod_floor_cap_at_start":False,
      "daily_stop_usd":0,
      "round_trip_fees_per_contract_usd":0,
      "contracts":1,
      "max_trades_per_day":2,
      "horizon_days":10,
      "simulations":400,
      "seed":3,
      "sample_already_examined":True,
      **change,
    }


class Tests(unittest.TestCase):
    def test_tick_values_exact(self):
        self.assertEqual(risk.TICKS,{"NQ":5.0,"MNQ":0.5})

    def test_positive_history_hits_target(self):
        raw=fake_history(1)
        result=risk.research(params(raw),raw)
        self.assertEqual(result["target_hit_fraction"],1)
        self.assertEqual(result["drawdown_failure_fraction"],0)
        self.assertEqual(result["median_days_to_target_conditional"],2)
        self.assertFalse(result["profitability_proven"])

    def test_target_first_is_reached_before_later_intraday_drawdown(self):
        class Pick:
            def choice(self, population):
                return population[0]
        raw = fake_history()
        p = params(raw, horizon_days=1, profit_target_usd=10,
                   maximum_drawdown_usd=20)
        # MNQ $0.50/tick: +40 prints a +$20 balance above the target;
        # -100 would later breach the account drawdown if erroneously evaluated.
        actual = risk.one_path([[40, -100]], p, Pick())
        self.assertEqual(actual["outcome"], "passed_target")
        self.assertEqual(actual["final_equity"], 1020)

    def test_negative_history_fails_before_horizon(self):
        raw=fake_history(-1)
        result=risk.research(params(raw),raw)
        self.assertEqual(result["target_hit_fraction"],0)
        self.assertEqual(result["drawdown_failure_fraction"],1)
        self.assertEqual(result["unfinished_fraction"],0)

    def test_simulation_is_reproducible(self):
        raw=fake_history(1)
        p=params(raw)
        self.assertEqual(risk.research(p,raw),risk.research(p,raw))

    def test_distinct_eod_trailing_floor(self):
        class Sequence:
            def __init__(self): self.i=0
            def choice(self,arr):
                selected=arr[self.i]
                self.i+=1
                return selected
        raw=fake_history()
        p=params(raw,profit_target_usd=500,maximum_drawdown_usd=30,
                 horizon_days=2,drawdown_mode="eod_trailing")
        losses=[ [100],[-90] ]
        trailing=risk.one_path(losses,p,Sequence())
        self.assertEqual(trailing["outcome"],"failed_drawdown")
        static=risk.one_path(losses,{**p,"drawdown_mode":"static"},Sequence())
        self.assertEqual(static["outcome"],"unfinished")

    def test_daily_stop_changes_path(self):
        raw=fake_history(-1)
        base=params(raw)
        all_trades=risk.one_path([[-8,-8]],base,__import__("random").Random(0))
        stopped=risk.one_path([[-8,-8]],{**base,"daily_stop_usd":1},
                              __import__("random").Random(0))
        self.assertEqual(all_trades["outcome"],"failed_drawdown")
        self.assertEqual(stopped["outcome"],"failed_drawdown")
        self.assertGreater(stopped["day"],all_trades["day"])

    def test_wilson_bounds_and_unfinished_mass(self):
        self.assertEqual(risk.wilson(50,100)[0] < .5,True)
        self.assertEqual(risk.wilson(50,100)[1] > .5,True)
        raw=fake_history()
        p=params(raw,horizon_days=1,profit_target_usd=1000)
        result=risk.research(p,raw)
        self.assertEqual(result["unfinished_fraction"],1)
        self.assertEqual(sum(result["outcomes"].values()),400)

    def test_checksum_and_mixed_instrument_rejected(self):
        raw=fake_history()
        with self.assertRaisesRegex(ValueError,"checksum"):
            risk.research(params(raw),raw+b"changed")
        bad=fake_history(contract="NQ")
        with self.assertRaisesRegex(ValueError,"mixed"):
            risk.research(params(bad),bad)

    def test_oversized_trade_count_and_unordered_rejected(self):
        raw=fake_history()
        with self.assertRaisesRegex(ValueError,"more daily"):
            risk.research(params(raw,max_trades_per_day=1),raw)
        # Reverse just two rows within the first day.
        lines=raw.decode().splitlines()
        damaged=("\n".join([lines[0],lines[2],lines[1],*lines[3:]])+"\n").encode()
        with self.assertRaises(ValueError):
            risk.research(params(damaged),damaged)

    def test_unreasonable_rules_rejected(self):
        raw=fake_history()
        for kwargs in (
            {"maximum_drawdown_usd":1000},
            {"contracts":0},
            {"drawdown_mode":"magic"},
            {"starting_balance_usd":0},
            {"eod_floor_cap_at_start":"yes"},
            {"simulations":0},
        ):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                risk.research(params(raw,**kwargs),raw)

    def test_immutable_artifacts(self):
        raw=fake_history()
        p=params(raw)
        with tempfile.TemporaryDirectory() as t:
            base=Path(t)
            conf=base/"p.json"
            data=base/"trades.csv"
            conf.write_text(json.dumps(p))
            data.write_bytes(raw)
            out=risk.run(conf,data,base/"runs")
            self.assertTrue((out/"result.json").exists())
            self.assertEqual(json.loads((out/"result.json").read_text())["source_kind"],"synthetic")
            with self.assertRaises(FileExistsError):
                risk.run(conf,data,base/"runs")


if __name__=="__main__":
    unittest.main()
