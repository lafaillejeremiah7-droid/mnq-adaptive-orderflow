"""Offline contract tests for live stream; no external data or API key required."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from mnq_flow.live_stream import (
    LiveAnalyzer, RecordFilter, save_latest, trade_from_db_record,
)

def raw(ts, ticks=81000, side="B", size=3, instrument_id=101):
    nanoseconds = int(ts.timestamp()) * 1_000_000_000
    return SimpleNamespace(
        action="T", side=side, price=ticks * 250_000_000,
        size=size, ts_event=nanoseconds, instrument_id=instrument_id,
    )

def stamp(minute):
    return datetime.fromisoformat("2026-11-12T14:30:00+00:00") + timedelta(minutes=minute)

def mapping(in_id=101, symbol="MNQ.v.0", contract="MNQZ6"):
    return SimpleNamespace(
        stype_in_symbol=symbol, stype_out_symbol=contract,
        instrument_id=in_id,
    )

class LiveTests(unittest.TestCase):
    def test_side_mapping_and_tick(self):
        trade = trade_from_db_record(raw(stamp(0), side="A"), "MNQZ6")
        self.assertEqual(trade.side, "S")
        self.assertEqual(trade.price_ticks, 81000)
        self.assertEqual(trade.contract, "MNQZ6")
        self.assertEqual(trade.timestamp, stamp(0))

    def test_unknown_side_is_not_invented(self):
        with self.assertRaisesRegex(ValueError, "Unknown aggressor"):
            trade_from_db_record(raw(stamp(0), side="N"), "MNQZ6")

    def test_bad_tick_rejected(self):
        record = raw(stamp(0))
        record.price += 1
        with self.assertRaisesRegex(ValueError, "tick aligned"):
            trade_from_db_record(record, "MNQZ6")

    def test_no_trade_before_mapping(self):
        f = RecordFilter("MNQ.v.0")
        self.assertIsNone(f.accept(raw(stamp(0))))
        self.assertIsNone(f.accept(mapping()))
        self.assertEqual(f.contract, "MNQZ6")
        self.assertEqual(f.accept(raw(stamp(0), instrument_id=202)), None)
        self.assertIsNotNone(f.accept(raw(stamp(0), instrument_id=101)))

    def test_contract_rollover_is_fail_closed(self):
        f = RecordFilter("MNQ.v.0")
        f.accept(mapping(101))
        f.accept(mapping(102, contract="MNQH7"))
        self.assertTrue(f.invalid)
        self.assertIsNone(f.accept(raw(stamp(1), instrument_id=101)))

    def test_incremental_closed_bars_and_cvd(self):
        live = LiveAnalyzer()
        snapshots = []
        for minute in range(36):
            tick = 81000 + minute
            trade = trade_from_db_record(raw(stamp(minute), ticks=tick), "MNQZ6")
            result = live.on_trade(trade)
            if result is not None:
                snapshots.append(result)
        self.assertEqual(len(snapshots), 35)
        self.assertEqual(snapshots[0]["rth_cvd"], 3)
        self.assertIsNone(snapshots[0]["five_minute_closed"])
        self.assertIsNone(snapshots[0]["fifteen_minute_closed"])
        at15 = next(x for x in snapshots if x["asof"].endswith("09:45:00-05:00"))
        self.assertIsNotNone(at15["five_minute_closed"])
        self.assertIsNotNone(at15["fifteen_minute_closed"])
        self.assertEqual(at15["rth_cvd"], 45)
        self.assertEqual(at15["fifteen_minute_bias"], "neutral")
        self.assertEqual(snapshots[-1]["asof"], "2026-11-12T10:05:00-05:00")
        self.assertFalse(snapshots[-1]["signal_is_unvalidated_hypothesis"] is False)

    def test_mid_session_start_is_degraded(self):
        live = LiveAnalyzer()
        late = raw(stamp(40))
        live.on_trade(trade_from_db_record(late, "MNQZ6"))
        self.assertTrue(live.degraded)
        self.assertTrue(live.degradation_reasons)

    def test_bad_order_blocks_future_candidates(self):
        live = LiveAnalyzer()
        live.on_trade(trade_from_db_record(raw(stamp(0)), "MNQZ6"))
        live.on_trade(trade_from_db_record(raw(stamp(2)), "MNQZ6"))
        self.assertIsNone(live.on_trade(trade_from_db_record(raw(stamp(1)), "MNQZ6")))
        self.assertTrue(live.degraded)

    def test_missing_prints_degrades(self):
        live = LiveAnalyzer()
        live.on_trade(trade_from_db_record(raw(stamp(0)), "MNQZ6"))
        live.on_trade(trade_from_db_record(raw(stamp(5)), "MNQZ6"))
        self.assertTrue(live.degraded)

    def test_atomic_json_latest(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "live_status.json"
            save_latest(path, {"signal":"none","rth_cvd":123})
            self.assertEqual(json.loads(path.read_text())["rth_cvd"], 123)
            self.assertFalse(path.with_suffix(".json.tmp").exists())

if __name__ == "__main__":
    unittest.main()
