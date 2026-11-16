"""Automatic real-time MNQ print analysis via licensed Databento CME feed.

No trade execution. No broker access. Actual passive liquidity / depth
absorption is NOT available from trade prints alone.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import deque
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

from .engine import (
    Bar, Trade, absorption_proxy, bar_data, bucket_start, histogram,
    merge_hist, session_day, to_price, volume_profile,
)

ET = __import__("zoneinfo").ZoneInfo("America/New_York")
NANOS_PER_TICK = 250_000_000  # Databento prices have 1e-9 precision.
DEFAULT_SYMBOL = "MNQ.v.0"

def trade_from_db_record(record, contract: str) -> Trade | None:
    """Decode a Trades schema record, not fills or depth updates."""
    if getattr(record, "action", None) != "T":
        return None
    side = getattr(record, "side", None)
    if side == "N":
        raise ValueError("Unknown aggressor side; signed delta is no longer complete")
    if side not in ("A", "B"):
        raise ValueError("Unrecognized aggressor side")
    price = int(record.price)
    if price % NANOS_PER_TICK:
        raise ValueError("MNQ price not tick aligned")
    size = int(record.size)
    if size <= 0:
        raise ValueError("Nonpositive trade size")
    timestamp_ns = int(record.ts_event)
    if timestamp_ns <= 0:
        raise ValueError("Invalid event timestamp")
    seconds, nano = divmod(timestamp_ns, 1_000_000_000)
    ts = datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=nano // 1000)
    return Trade(
        timestamp=ts, price_ticks=price // NANOS_PER_TICK, size=size,
        side="B" if side == "B" else "S", contract=contract,
    )

class LiveAnalyzer:
    """Small bounded state (up to 20 prior 1m bars, 3 longer bars and today's VAP)."""

    def __init__(self):
        self.day = None
        self.active = {1: None, 5: None, 15: None}
        self.done5 = deque(maxlen=3)
        self.done15 = deque(maxlen=3)
        self.prior1 = deque(maxlen=20)
        self.profile = {}
        self.prior_profile = None
        self.cvd = 0
        self.last_time = None
        self.degraded = False
        self.degradation_reasons = set()
        self.observed_rth_start = None
        self.accepted_prints = 0

    def invalidate(self, reason: str):
        self.degraded = True
        self.degradation_reasons.add(reason)

    def _reset_day(self, day, start):
        if self.day is not None and self.profile:
            self.prior_profile = volume_profile(self.profile)
        self.day = day
        self.active = {1: None, 5: None, 15: None}
        self.done5.clear()
        self.done15.clear()
        self.prior1.clear()
        self.profile = {}
        self.cvd = 0
        self.degraded = False
        self.degradation_reasons.clear()
        self.observed_rth_start = start
        self.accepted_prints = 0
        if start.hour != 9 or start.minute != 30:
            self.invalidate("RTH data did not start at 09:30 ET; developing profile incomplete")

    def _close_higher(self, asof):
        for tf, output in ((5, self.done5), (15, self.done15)):
            bar = self.active[tf]
            if bar is not None and bar.end <= asof:
                output.append(bar)
                self.active[tf] = None

    def _complete_1m(self):
        bar = self.active[1]
        if bar is None:
            return None
        self._close_higher(bar.end)
        latest5 = self.done5[-1] if self.done5 else None
        latest15 = self.done15[-1] if self.done15 else None
        prior = volume_profile(self.profile)
        absorption = absorption_proxy(bar, list(self.prior1))
        bias = "neutral"
        if len(self.done15) >= 2:
            recent, older = self.done15[-1], self.done15[-2]
            bias = "up" if recent.close > older.close else "down" if recent.close < older.close else "neutral"
        levels = []
        for name, p in (
            ("prior_rth", self.prior_profile),
            ("developing_before_bar", prior),
            ("last_closed_5m", volume_profile(histogram(latest5.levels)) if latest5 else None),
            ("last_closed_15m", volume_profile(histogram(latest15.levels)) if latest15 else None),
        ):
            if p is not None:
                for kind in ("poc", "vah", "val"):
                    levels.append({"source": name, "kind": kind, "price": p[kind]})
        ranges = [previous.high - previous.low for previous in self.prior1]
        from statistics import median
        tolerance = max(4, min(16, int(median(ranges) / 4))) if ranges else 8
        nearest = min(
            levels, key=lambda x: abs(round(x["price"] / 0.25) - bar.close), default=None
        )
        near = bool(nearest and abs(round(nearest["price"] / 0.25) - bar.close) <= tolerance)
        local_time = bar.end.time()
        in_window = bar.end.weekday() in (0,1,2,3) and time(10, 0) <= local_time < time(15, 0)
        signal = "none"
        if not self.degraded and in_window and near and latest5 is not None:
            if absorption["bullish"] and bias == "up" and latest5.delta > 0:
                signal = "long_candidate"
            elif absorption["bearish"] and bias == "down" and latest5.delta < 0:
                signal = "short_candidate"
        self.cvd += bar.delta
        merge_hist(self.profile, histogram(bar.levels))
        result = {
            "source": "databento_glbx_mdp3_trades",
            "rth_date": self.day.isoformat(),
            "asof": bar.end.isoformat(),
            "contract": bar.start.date().isoformat(),
            "one_minute": bar_data(bar),
            "five_minute_closed": bar_data(latest5),
            "fifteen_minute_closed": bar_data(latest15),
            "rth_cvd": self.cvd,
            "developing_rth_profile": volume_profile(self.profile),
            "previous_rth_profile": self.prior_profile,
            "fifteen_minute_bias": bias,
            "absorption_proxy": absorption,
            "nearest_reference": nearest,
            "signal": signal,
            "signal_is_unvalidated_hypothesis": True,
            "data_healthy": not self.degraded,
            "degradation_reasons": sorted(self.degradation_reasons),
            "rth_prints_seen": self.accepted_prints,
            "live_order_book_absorption_available": False,
        }
        self.prior1.append(bar)
        self.active[1] = None
        return result

    def on_trade(self, trade: Trade):
        """Return one completed-minute snapshot when a newer print confirms closing."""
        if self.last_time is not None:
            if trade.timestamp < self.last_time:
                self.invalidate("Out-of-order timestamp")
                return None
            if (trade.timestamp - self.last_time) > timedelta(minutes=2) and self.day == session_day(trade.timestamp):
                self.invalidate("Missing more than two minutes of trade prints")
        self.last_time = trade.timestamp
        day = session_day(trade.timestamp)
        if day is None:
            return None
        start = bucket_start(trade.timestamp, 1)
        if self.day != day:
            self._reset_day(day, start)
        snapshot = None
        old_minute = self.active[1]
        if old_minute is not None and old_minute.start != start:
            snapshot = self._complete_1m()
        # Complete 5m/15m that passed during sparse minutes only after old
        # 1m snapshot was generated; otherwise lookahead would result.
        self._close_higher(trade.timestamp.astimezone(ET))
        for tf in (1,5,15):
            new_start = bucket_start(trade.timestamp, tf)
            bar = self.active[tf]
            if bar is None or bar.start != new_start:
                tick = trade.price_ticks
                bar = Bar(new_start, tf, tick, tick, tick, tick)
                self.active[tf] = bar
            bar.add(trade)
        self.accepted_prints += 1
        return snapshot

class RecordFilter:
    """Locks one continuous contract to its actual instrument ID."""
    def __init__(self, requested_symbol):
        self.requested_symbol = requested_symbol
        self.instrument_id = None
        self.contract = None
        self.invalid = False
        self.reason = None

    def accept(self, record):
        if hasattr(record, "stype_out_symbol"):
            symbol_in = getattr(record, "stype_in_symbol", None)
            symbol_out = getattr(record, "stype_out_symbol", None)
            if symbol_in == self.requested_symbol:
                new_id = int(record.instrument_id)
                if self.instrument_id is not None and new_id != self.instrument_id:
                    self.invalid = True
                    self.reason = "Contract rollover or mapping changed; restart and revalidate"
                else:
                    self.instrument_id = new_id
                    self.contract = symbol_out
            return None
        if not hasattr(record, "action"):
            if "Error" in type(record).__name__ or "Err" in type(record).__name__:
                self.invalid = True
                self.reason = "Provider error: " + str(record)[:160]
            return None
        if self.invalid or self.instrument_id is None:
            return None
        if int(record.instrument_id) != self.instrument_id:
            return None
        return trade_from_db_record(record, str(self.contract))

def save_latest(path: Path, record: dict):
    # Only the latest derived snapshot, no redistribution of raw trade prints.
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(record, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)

def run_live(symbol: str, status_path: Path, signals_only: bool = False):
    if not os.environ.get("DATABENTO_API_KEY"):
        raise RuntimeError(
            "Missing DATABENTO_API_KEY. Licensed CME Databento live access is required; "
            "your chart subscription cannot be assumed to provide API entitlement."
        )
    try:
        import databento as db
    except ImportError as error:
        raise RuntimeError("Install Python client: python3 -m pip install databento") from error
    state = LiveAnalyzer()
    mapping = RecordFilter(symbol)
    def callback(record):
        try:
            trade = mapping.accept(record)
            if mapping.invalid:
                state.invalidate(mapping.reason or "Provider instrument mapping error")
                return
            if trade is None:
                return
            snapshot = state.on_trade(trade)
            if snapshot is None:
                return
            snapshot["contract"] = mapping.contract
            # Prints replayed from intraday history are backfill, not live alerts.
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(snapshot["asof"]).astimezone(timezone.utc)).total_seconds()
            snapshot["live_now"] = 0 <= age <= 120 and snapshot["data_healthy"]
            snapshot["actionable_live_candidate"] = (
                snapshot["live_now"] and snapshot["signal"] != "none"
            )
            save_latest(status_path, snapshot)
            if (not signals_only) or snapshot["actionable_live_candidate"]:
                print(json.dumps(snapshot, separators=(",", ":")), flush=True)
        except (ValueError, OverflowError) as error:
            state.invalidate("Bad or incomplete source data: " + str(error))
            print("DATA DEGRADED: " + str(error), file=sys.stderr, flush=True)

    client = db.Live()
    # Continuous volume-leader is resolved at subscription time. It does
    # NOT automatically remap during the live session; restart on rollover.
    local = datetime.now(ET)
    opening = local.replace(hour=9, minute=30, second=0, microsecond=0)
    subscribe_args = {
        "dataset": "GLBX.MDP3", "schema": "trades",
        "stype_in": "continuous", "symbols": symbol,
    }
    if local.weekday() < 5 and time(9, 30) <= local.time() <= time(16, 0):
        subscribe_args["start"] = opening.isoformat()
    client.subscribe(**subscribe_args)
    client.add_callback(callback, exception_callback=lambda e: print(
        "CALLBACK ERROR: " + str(e), file=sys.stderr, flush=True))
    print(
        "Starting licensed CME live MNQ trades. Symbol: " + symbol
        + ". Signal rules are unvalidated. No orders are placed.",
        file=sys.stderr, flush=True,
    )
    try:
        client.start()
        client.block_for_close()
    except KeyboardInterrupt:
        client.stop()

def main():
    parser = argparse.ArgumentParser(description="Licensed real MNQ data to automatic signals.")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL,
                        help="Databento continuous MNQ symbol, default MNQ.v.0")
    parser.add_argument("--status", default="live_status.json",
                        help="Latest automatically computed snapshot")
    parser.add_argument("--signals-only", action="store_true",
                        help="Only print current (non-backfill) candidates")
    args = parser.parse_args()
    if args.symbol != DEFAULT_SYMBOL:
        parser.error("Only tested adapter symbol MNQ.v.0 is allowed")
    try:
        run_live(args.symbol, Path(args.status), args.signals_only)
    except (RuntimeError, OSError, ValueError) as error:
        parser.error(str(error))

if __name__ == "__main__":
    main()
