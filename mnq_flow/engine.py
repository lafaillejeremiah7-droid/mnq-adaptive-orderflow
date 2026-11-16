"""MNQ trade-print research engine. No live orders and no synthetic delta."""
from __future__ import annotations
import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TICK = Decimal("0.25")
POINT_VALUE_USD = 2.0

@dataclass(frozen=True)
class Trade:
    timestamp: datetime
    price_ticks: int
    size: int
    side: str
    contract: str = "MNQ"

@dataclass
class Bar:
    start: datetime
    timeframe: int
    open: int
    high: int
    low: int
    close: int
    buy: int = 0
    sell: int = 0
    levels: dict[int, list[int]] = field(default_factory=dict)

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.timeframe)

    @property
    def delta(self) -> int:
        return self.buy - self.sell

    @property
    def volume(self) -> int:
        return self.buy + self.sell

    def add(self, trade: Trade) -> None:
        tick = trade.price_ticks
        self.high = max(self.high, tick)
        self.low = min(self.low, tick)
        self.close = tick
        if trade.side == "B":
            self.buy += trade.size
        else:
            self.sell += trade.size
        level = self.levels.setdefault(tick, [0, 0])
        level[0 if trade.side == "B" else 1] += trade.size

def load_trades(path: str | Path) -> list[Trade]:
    """Require true aggressor classifications and offset-aware timestamps."""
    result: list[Trade] = []
    with open(path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or not {"timestamp", "price", "size", "side"}.issubset(reader.fieldnames):
            raise ValueError("CSV requires timestamp,price,size,side")
        contract_seen = None
        for line, row in enumerate(reader, 2):
            try:
                timestamp = datetime.fromisoformat(row["timestamp"].strip().replace("Z", "+00:00"))
                if timestamp.utcoffset() is None:
                    raise ValueError("timestamp must have UTC offset")
                price = Decimal(row["price"].strip())
                ticks = price / TICK
                if not ticks.is_finite() or ticks != ticks.to_integral_value():
                    raise ValueError("price not aligned with 0.25 MNQ tick")
                size = int(row["size"])
                if size <= 0:
                    raise ValueError("size must be positive")
                side = row["side"].strip().upper()
                if side not in {"B", "S"}:
                    raise ValueError("side must be B or S")
                contract = (row.get("contract") or "MNQ").strip().upper()
                if contract_seen is not None and contract != contract_seen:
                    raise ValueError("mixed contracts: process each expiry separately")
                contract_seen = contract
                trade = Trade(timestamp, int(ticks), size, side, contract)
                if result and trade.timestamp < result[-1].timestamp:
                    raise ValueError("CSV must be chronologically sorted")
                result.append(trade)
            except (ValueError, InvalidOperation, TypeError, AttributeError) as error:
                raise ValueError(f"Invalid CSV line {line}: {error}") from error
    return result

def session_day(timestamp: datetime):
    local = timestamp.astimezone(ET)
    if local.weekday() >= 5 or not (time(9, 30) <= local.time() < time(16, 0)):
        return None
    return local.date()

def bucket_start(timestamp: datetime, minutes: int) -> datetime:
    local = timestamp.astimezone(ET)
    minute = (local.hour * 60 + local.minute) // minutes * minutes
    return local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=minute)

def build_bars(trades: list[Trade], timeframe: int) -> list[Bar]:
    if timeframe not in {1, 5, 15}:
        raise ValueError("Only 1m, 5m, and 15m bars are supported")
    result: dict[tuple, Bar] = {}
    for trade in trades:
        day = session_day(trade.timestamp)
        if day is None:
            continue
        start = bucket_start(trade.timestamp, timeframe)
        key = (day, start)
        if key not in result:
            tick = trade.price_ticks
            result[key] = Bar(start, timeframe, tick, tick, tick, tick)
        result[key].add(trade)
    return sorted(result.values(), key=lambda bar: bar.start)

def histogram(levels: dict[int, list[int]]) -> dict[int, int]:
    return {price: sum(sides) for price, sides in levels.items()}

def merge_hist(target: dict[int, int], additions: dict[int, int]) -> None:
    for tick, volume in additions.items():
        target[tick] = target.get(tick, 0) + volume

def to_price(ticks: int) -> float:
    return ticks * 0.25

def volume_profile(levels: dict[int, int], value_fraction: float = 0.70):
    """Contiguous 70 percent value area, expanded from POC."""
    if not levels:
        return None
    if not (0 < value_fraction <= 1):
        raise ValueError("invalid value_fraction")
    ordered = sorted((t, v) for t, v in levels.items() if v > 0)
    if not ordered:
        return None
    total = sum(v for _, v in ordered)
    weighted_tick = sum(t * v for t, v in ordered) / total
    poc = min(ordered, key=lambda x: (-x[1], abs(x[0] - weighted_tick), x[0]))[0]
    left = right = [t for t, _ in ordered].index(poc)
    covered = ordered[left][1]
    while covered < total * value_fraction:
        lo = ordered[left-1][1] if left > 0 else -1
        hi = ordered[right+1][1] if right+1 < len(ordered) else -1
        if lo < 0 and hi < 0:
            break
        if lo >= hi:
            left -= 1
            covered += lo
        else:
            right += 1
            covered += hi
    return {
        "poc": to_price(poc), "val": to_price(ordered[left][0]),
        "vah": to_price(ordered[right][0]), "volume": total,
        "value_area_fraction": round(covered / total, 4),
    }

def bar_data(bar: Bar | None):
    if bar is None:
        return None
    return {
        "start": bar.start.isoformat(), "end": bar.end.isoformat(),
        "open": to_price(bar.open), "high": to_price(bar.high),
        "low": to_price(bar.low), "close": to_price(bar.close),
        "volume": bar.volume, "buy_volume": bar.buy, "sell_volume": bar.sell,
        "delta": bar.delta, "profile": volume_profile(histogram(bar.levels)),
    }

def absorption_proxy(bar: Bar, history: list[Bar]):
    """Trade-print proxy for absorption, NOT actual resting-liquidity measurement."""
    prior = history[-20:]
    if len(prior) < 10:
        return {"bullish": False, "bearish": False, "ready": False}
    lows = [b.levels.get(b.low, [0, 0])[1] for b in prior]
    highs = [b.levels.get(b.high, [0, 0])[0] for b in prior]
    sell_threshold = max(5, 1.8 * median(lows))
    buy_threshold = max(5, 1.8 * median(highs))
    width = bar.high - bar.low
    if width < 2:
        return {"bullish": False, "bearish": False, "ready": True}
    lows_sell = bar.levels.get(bar.low, [0, 0])[1]
    highs_buy = bar.levels.get(bar.high, [0, 0])[0]
    bullish = (bar.delta < 0 and lows_sell >= sell_threshold
               and (bar.close - bar.low) / width >= 0.60)
    bearish = (bar.delta > 0 and highs_buy >= buy_threshold
               and (bar.high - bar.close) / width >= 0.60)
    return {
        "bullish": bullish, "bearish": bearish, "ready": True,
        "sell_at_low": lows_sell, "buy_at_high": highs_buy,
        "sell_threshold": round(sell_threshold, 2),
        "buy_threshold": round(buy_threshold, 2),
    }

def analyze(trades: list[Trade]) -> list[dict]:
    """Snapshots contain only previously observed prints and completed bars."""
    if not trades:
        return []
    if any(trades[i].timestamp > trades[i+1].timestamp for i in range(len(trades)-1)):
        raise ValueError("Trades must be chronological")
    if len({t.contract for t in trades}) > 1:
        raise ValueError("Mixed contract expiries unsupported")
    last_seen = trades[-1].timestamp.astimezone(ET)
    bars = {tf: [b for b in build_bars(trades, tf) if b.end <= last_seen]
            for tf in (1, 5, 15)}
    days = sorted({b.start.date() for b in bars[1]})
    results: list[dict] = []
    previous_session = None
    contract = trades[0].contract
    for day in days:
        m1 = [b for b in bars[1] if b.start.date() == day]
        m5 = [b for b in bars[5] if b.start.date() == day]
        m15 = [b for b in bars[15] if b.start.date() == day]
        idx5 = idx15 = 0
        complete5: list[Bar] = []
        complete15: list[Bar] = []
        previous_minutes: list[Bar] = []
        session_levels: dict[int, int] = {}
        cvd = 0
        for bar in m1:
            existing = volume_profile(session_levels)  # Before current bar.
            while idx5 < len(m5) and m5[idx5].end <= bar.end:
                complete5.append(m5[idx5])
                idx5 += 1
            while idx15 < len(m15) and m15[idx15].end <= bar.end:
                complete15.append(m15[idx15])
                idx15 += 1
            last5 = complete5[-1] if complete5 else None
            last15 = complete15[-1] if complete15 else None
            bias = "neutral"
            if len(complete15) >= 2:
                if complete15[-1].close > complete15[-2].close:
                    bias = "up"
                elif complete15[-1].close < complete15[-2].close:
                    bias = "down"
            absorption = absorption_proxy(bar, previous_minutes)
            reference = []
            for name, p in (
                ("prior_rth", previous_session),
                ("developing_before_bar", existing),
                ("last_closed_5m", volume_profile(histogram(last5.levels)) if last5 else None),
                ("last_closed_15m", volume_profile(histogram(last15.levels)) if last15 else None),
            ):
                if p:
                    for kind in ("poc", "vah", "val"):
                        reference.append({"source": name, "kind": kind, "price": p[kind]})
            ranges = [b.high - b.low for b in previous_minutes[-20:]]
            tolerance_ticks = max(4, min(16, int(median(ranges) / 4))) if ranges else 8
            nearest = min(reference,
                          key=lambda level: abs(round(level["price"] / .25) - bar.close),
                          default=None)
            distance = abs(round(nearest["price"] / .25) - bar.close) if nearest else None
            near = nearest is not None and distance <= tolerance_ticks
            in_window = time(10, 0) <= bar.end.time() < time(15, 0)
            signal = "none"
            if in_window and near and last5:
                if absorption["bullish"] and bias == "up" and last5.delta > 0:
                    signal = "long_candidate"
                elif absorption["bearish"] and bias == "down" and last5.delta < 0:
                    signal = "short_candidate"
            cvd += bar.delta
            merge_hist(session_levels, histogram(bar.levels))
            results.append({
                "rth_date": day.isoformat(), "asof": bar.end.isoformat(),
                "contract": contract, "one_minute": bar_data(bar),
                "five_minute_closed": bar_data(last5),
                "fifteen_minute_closed": bar_data(last15),
                "rth_cvd": cvd,
                "developing_rth_profile": volume_profile(session_levels),
                "previous_rth_profile": previous_session,
                "fifteen_minute_bias": bias, "absorption_proxy": absorption,
                "nearest_reference": nearest, "distance_to_reference_ticks": distance,
                "adaptive_level_tolerance_ticks": tolerance_ticks,
                "signal": signal, "in_user_entry_window": in_window,
                "invalidation_price": (
                    to_price(bar.low - 2) if signal == "long_candidate"
                    else to_price(bar.high + 2) if signal == "short_candidate"
                    else None),
            })
            previous_minutes.append(bar)
        previous_session = volume_profile(session_levels)
    return results

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Analyze MNQ trade prints (no orders).")
    parser.add_argument("csv", help="Sorted prints: timestamp,price,size,side[,contract]")
    parser.add_argument("--out", help="Write every completed minute to JSONL")
    parser.add_argument("--candidates", action="store_true", help="Show only candidates")
    args = parser.parse_args()
    snapshots = analyze(load_trades(args.csv))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as outfile:
            for item in snapshots:
                outfile.write(json.dumps(item, separators=(",", ":")) + "\n")
    selected = [s for s in snapshots if s["signal"] != "none"] if args.candidates else snapshots[-1:]
    print(json.dumps(selected if args.candidates else (selected[0] if selected else {}),
                     indent=2))

if __name__ == "__main__":
    main()
