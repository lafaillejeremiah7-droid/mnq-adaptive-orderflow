"""Tick-accurate NQ/MNQ volume profile and historical level-reaction research.

No external feeds, order placement, or assertion of trading edge. Only completed
RTH sessions form levels used in later sessions; no same-day final-profile leakage.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from quantlab import ticks

NY = ZoneInfo("America/New_York")
BILLION = 1_000_000_000
COLUMNS = ["timestamp_ns", "contract", "price", "size", "side", "sequence"]
CONTRACT = re.compile(r"(?:NQ|MNQ)[HMUZ][0-9]{1,4}\Z")
SPEC_KEYS = {
    "id", "question", "falsifier", "data_source", "data_sha256",
    "data_kind", "contract", "rth_start", "rth_end",
    "value_area_fraction", "touch_tolerance_ticks", "excursion_ticks",
    "horizon_seconds", "min_profile_trades", "min_eval_trades",
    "min_session_pairs", "max_gap_calendar_days", "seed", "max_trades",
}


@dataclass(frozen=True)
class Trade:
    timestamp_ns: int
    contract: str
    price_ticks: int
    size: int
    side: str
    sequence: int


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _int(value, label, low=0):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        raise ValueError(f"{label} must be an unsigned decimal integer")
    number = int(value)
    if number < low:
        raise ValueError(f"{label} below minimum")
    return number


def time_hhmm(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        raise ValueError("expected HH:MM in America/New_York")
    h, m = map(int, value.split(":"))
    return 60 * h + m


def validate_spec(spec: dict) -> None:
    if not isinstance(spec, dict) or set(spec) != SPEC_KEYS:
        raise ValueError("invalid profile study protocol keys")
    if not isinstance(spec["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", spec["id"]):
        raise ValueError("invalid study id")
    for field in ("question", "falsifier", "data_source"):
        if not isinstance(spec[field], str) or not spec[field].strip():
            raise ValueError(f"missing {field}")
    if spec["data_kind"] not in ("synthetic", "historical"):
        raise ValueError("data_kind must be synthetic or historical")
    if not isinstance(spec["data_sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", spec["data_sha256"]):
        raise ValueError("invalid data SHA-256")
    if not isinstance(spec["contract"], str) or not CONTRACT.fullmatch(spec["contract"]):
        raise ValueError("contract must be one NQ/MNQ quarterly outright")
    a, b = time_hhmm(spec["rth_start"]), time_hhmm(spec["rth_end"])
    if b <= a or b - a > 720:
        raise ValueError("RTH window must be same-day and <=12 hours")
    if type(spec["value_area_fraction"]) not in (int, float) or not 0.5 <= spec["value_area_fraction"] <= 0.95:
        raise ValueError("value area fraction must be 0.5 to 0.95")
    for key, low, high in [
        ("touch_tolerance_ticks", 0, 8), ("excursion_ticks", 1, 1000),
        ("horizon_seconds", 1, 3600), ("min_profile_trades", 1, 2_000_000),
        ("min_eval_trades", 2, 2_000_000), ("min_session_pairs", 1, 1000),
        ("max_gap_calendar_days", 1, 7), ("seed", 0, 2**32 - 1),
        ("max_trades", 1, 5_000_000),
    ]:
        if type(spec[key]) is not int or not low <= spec[key] <= high:
            raise ValueError(f"invalid {key}")
    if spec["excursion_ticks"] <= spec["touch_tolerance_ticks"]:
        raise ValueError("excursion must exceed touch tolerance")


def read_trades(raw: bytes, contract: str, max_trades: int) -> list[Trade]:
    """Read a canonical file; equal event times need increasing source sequence."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("trade CSV must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames != COLUMNS:
        raise ValueError("trade CSV must use " + ",".join(COLUMNS))
    trades: list[Trade] = []
    last = None
    for row in reader:
        if len(trades) >= max_trades:
            raise ValueError("max_trades exceeded; partition input by session")
        if set(row) != set(COLUMNS) or any(value is None for value in row.values()):
            raise ValueError("missing or unexpected trade fields")
        if row["contract"] != contract:
            raise ValueError("mixed or unexpected instrument; do not combine NQ and MNQ")
        ns = _int(row["timestamp_ns"], "timestamp_ns", 946684800 * BILLION)
        if ns >= 4102444800 * BILLION:
            raise ValueError("timestamp is outside supported 2000-2099 interval")
        sequence = _int(row["sequence"], "sequence")
        key = (ns, sequence)
        if last is not None and key <= last:
            raise ValueError("trade events must be in strictly increasing timestamp/sequence order")
        last = key
        size = _int(row["size"], "size", 1)
        if size > 50_000_000:
            raise ValueError("unreasonably large trade size")
        side = row["side"]
        if side not in ("B", "A", "N"):
            raise ValueError("side must be B (buy), A (sell), or N (unknown)")
        trades.append(Trade(ns, contract, ticks(row["price"]), size, side, sequence))
    if not trades:
        raise ValueError("no trade events")
    return trades


def rth_groups(trades: list[Trade], start_minute: int, end_minute: int) -> dict[str, list[Trade]]:
    sessions: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        dt = datetime.fromtimestamp(trade.timestamp_ns // BILLION, tz=timezone.utc).astimezone(NY)
        minute = dt.hour * 60 + dt.minute
        if dt.weekday() < 5 and start_minute <= minute < end_minute:
            sessions[dt.date().isoformat()].append(trade)
    return dict(sorted(sessions.items()))


def _aggregate_profile(trades: list[Trade], backend: str):
    """Exact integer counters; C++ is explicitly optional and never required."""
    if backend not in ("python", "cpp", "auto"):
        raise ValueError("profile backend must be python, cpp or auto")
    # Avoid extension-loading and attribute-marshalling overhead on small samples.
    use_cpp = backend == "cpp" or (backend == "auto" and len(trades) >= 20_000)
    if use_cpp:
        from importlib import import_module

        try:
            native = import_module("company._nq_cpp")
        except ModuleNotFoundError as exc:
            if exc.name != "company._nq_cpp":
                raise
            if backend == "cpp":
                raise RuntimeError(
                    "C++ research kernel not built: pip install pybind11 setuptools; "
                    "python setup.py build_ext --inplace"
                ) from exc
        else:
            price_volume, at_price, at_minute, side_totals, weight, total, count = native.aggregate(trades)
            if count != len(trades):
                raise RuntimeError("C++ kernel returned a different trade count")
            labels = ("B", "A", "N")
            return (
                Counter(price_volume),
                dict(zip(labels, side_totals, strict=True)),
                {
                    price: dict(zip(labels, values, strict=True))
                    for price, values in at_price.items()
                },
                {
                    minute: dict(zip(labels, values, strict=True))
                    for minute, values in at_minute.items()
                },
                weight, total,
            )
    vap = Counter()
    side_volume = Counter()
    side_at_price = defaultdict(Counter)
    side_by_minute = defaultdict(Counter)
    weight = 0
    total = 0
    for item in trades:
        vap[item.price_ticks] += item.size
        side_volume[item.side] += item.size
        side_at_price[item.price_ticks][item.side] += item.size
        side_by_minute[item.timestamp_ns // (60 * BILLION)][item.side] += item.size
        weight += item.price_ticks * item.size
        total += item.size
    return vap, side_volume, side_at_price, side_by_minute, weight, total


def volume_profile(trades: list[Trade], fraction: float, backend: str = "python") -> dict:
    """VAP in one 0.25-point tick bin per exchange price; contiguous VA from POC.

    Python is the audited default. The compiled C++ backend accelerates only
    the integer counter pass. All VA, HVN/LVN and reporting logic stays shared.
    """
    if not trades:
        raise ValueError("profile requires trade events")
    vap, side_volume, side_at_price, side_by_minute, weight, total = (
        _aggregate_profile(trades, backend)
    )
    lower, upper = min(vap), max(vap)
    if upper - lower > 200_000:
        raise ValueError("profile price span too large; partition input")
    poc = min(vap, key=lambda price: (-vap[price], abs(price * total - weight), price))
    lo = hi = poc
    covered = vap[poc]
    target = math.ceil(fraction * total - 1e-10)
    while covered < target:
        left, right = lo - 1 if lo > lower else None, hi + 1 if hi < upper else None
        if left is None and right is None:
            break
        if left is None:
            selected = right
        elif right is None:
            selected = left
        else:
            vl, vr = vap[left], vap[right]
            selected = (
                left if vl > vr else right if vr > vl
                else left if abs(left * total - weight) <= abs(right * total - weight) else right
            )
        covered += vap[selected]
        lo = min(lo, selected)
        hi = max(hi, selected)
    peak = max(vap.values())
    # A deterministic, explicitly heuristic one-tick local-extrema rule.
    high_nodes = []
    low_nodes = []
    zeros = 0
    for price in range(lower, upper + 1):
        current = vap[price]
        if not current:
            zeros += 1
        if price in (lower, upper):
            continue
        before, after = vap[price - 1], vap[price + 1]
        if current > 0 and current >= before and current >= after and (current > before or current > after):
            if current * 2 >= peak:
                high_nodes.append(price)
        if current > 0 and current < before and current < after and current * 2 <= peak:
            low_nodes.append(price)
    if poc not in high_nodes:
        high_nodes.append(poc)
    high_nodes = sorted(high_nodes, key=lambda p: (-vap[p], p))[:5]
    low_nodes = sorted(low_nodes, key=lambda p: (vap[p], p))[:5]
    minute_flow = {}
    running_known_delta = 0
    complete_to_date = True
    for minute_key, sides in sorted(side_by_minute.items()):
        buy, sell, unknown = sides["B"], sides["A"], sides["N"]
        running_known_delta += buy - sell
        complete_to_date = complete_to_date and unknown == 0
        minute_flow[str(minute_key * 60 * BILLION)] = {
            "aggressor_buy_volume": buy,
            "aggressor_sell_volume": sell,
            "unknown_side_volume": unknown,
            "known_delta": buy - sell,
            "running_known_delta": running_known_delta,
            "complete_side_coverage_through_minute": complete_to_date,
        }
    return {
        "contract": trades[0].contract,
        "total_contracts_traded": total,
        "trade_count": len(trades),
        "poc_ticks": poc,
        "vah_ticks": hi,
        "val_ticks": lo,
        "vwap_points": weight / (4 * total),
        "value_area_volume_fraction_actual": covered / total,
        "value_area_fraction_requested": fraction,
        "hvn_ticks": high_nodes,
        "lvn_ticks": low_nodes,
        "untraded_price_bins": zeros,
        "volume_at_price": {str(p / 4): vap[p] for p in sorted(vap)},
        "volume_at_price_aggressor": {
            str(p / 4): {
                "buy": side_at_price[p]["B"],
                "sell": side_at_price[p]["A"],
                "unknown": side_at_price[p]["N"],
                "known_delta": side_at_price[p]["B"] - side_at_price[p]["A"],
                "complete_aggressor_coverage": side_at_price[p]["N"] == 0,
            } for p in sorted(vap)
        },
        "one_minute_trade_delta": minute_flow,
        "aggressor_buy_volume": side_volume["B"],
        "aggressor_sell_volume": side_volume["A"],
        "aggressor_unknown_volume": side_volume["N"],
        "known_trade_delta": side_volume["B"] - side_volume["A"],
        "delta_covers_all_volume": side_volume["N"] == 0,
        "tie_breaking": "POC by VWAP proximity then lower; VA adjacent-volume then VWAP proximity then lower",
        "node_definition": "One-tick local extrema; HVN >=50% of POC volume, LVN <=50%; 5 nodes max each",
    }


def profile_levels(profile: dict) -> list[tuple[str, int]]:
    levels = []
    seen = set()
    for label, price in (("POC", profile["poc_ticks"]), ("VAH", profile["vah_ticks"]),
                         ("VAL", profile["val_ticks"])):
        # Different labels at exactly the same price are one physical touch.
        if price not in seen:
            levels.append((label, price))
            seen.add(price)
    for name, values in (("HVN", profile["hvn_ticks"]), ("LVN", profile["lvn_ticks"])):
        for price in values:
            if price not in seen:
                levels.append((name, price))
                seen.add(price)
    return levels


def first_touch(trades: list[Trade], level: int, tolerance: int, threshold: int,
                horizon_ns: int) -> dict | None:
    """One first-touch per session/level, after price was first outside tolerance.

    The first threshold hit after touch determines 'rejection_first' or
    'cross_first'. An unhit threshold is unresolved, not a profitable strategy.
    """
    for i in range(1, len(trades)):
        previous, current = trades[i - 1], trades[i]
        dist = previous.price_ticks - level
        if abs(dist) <= tolerance or abs(current.price_ticks - level) > tolerance:
            continue
        approach = 1 if dist > 0 else -1
        last = None
        count = 0
        first_passage_ns = None
        max_rejection_ticks = 0
        max_cross_ticks = 0
        outcome = "censored_no_future_trade"
        touch_ns = current.timestamp_ns
        for later in trades[i + 1:]:
            if later.timestamp_ns - touch_ns > horizon_ns:
                break
            last = later
            count += 1
            relative = approach * (later.price_ticks - level)
            max_rejection_ticks = max(max_rejection_ticks, relative)
            max_cross_ticks = max(max_cross_ticks, -relative)
            if outcome in ("censored_no_future_trade", "unresolved"):
                if relative >= threshold:
                    outcome = "rejection_first"
                    first_passage_ns = later.timestamp_ns
                elif relative <= -threshold:
                    outcome = "cross_first"
                    first_passage_ns = later.timestamp_ns
                else:
                    outcome = "unresolved"
        return {
            "touch_ts_ns": touch_ns,
            "level_ticks": level,
            "touch_price_ticks": current.price_ticks,
            "approach_from": "above" if approach > 0 else "below",
            "outcome": outcome,
            "followup_trades": count,
            "first_passage_seconds": None if first_passage_ns is None else (first_passage_ns - touch_ns) / BILLION,
            "max_rejection_excursion_ticks": max_rejection_ticks if count else None,
            "max_cross_excursion_ticks": max_cross_ticks if count else None,
            "last_observed_offset_seconds": None if last is None else (last.timestamp_ns - touch_ns) / BILLION,
            "final_signed_away_from_level_ticks": None if last is None else approach * (last.price_ticks - level),
        }
    return None


def summarize(events: list[dict]) -> dict:
    grouped = defaultdict(list)
    for event in events:
        grouped[event["kind"]].append(event)
    result = {}
    for kind, records in sorted(grouped.items()):
        outcomes = Counter(item["outcome"] for item in records)
        conclusive = outcomes["rejection_first"] + outcomes["cross_first"]
        points = [x["final_signed_away_from_level_ticks"] for x in records
                  if x["final_signed_away_from_level_ticks"] is not None]
        passage_times = [x["first_passage_seconds"] for x in records if x["first_passage_seconds"] is not None]
        result[kind] = {
            "events": len(records),
            "distinct_session_dates": len({x["session_date"] for x in records}),
            "rejection_first": outcomes["rejection_first"],
            "cross_first": outcomes["cross_first"],
            "unresolved": outcomes["unresolved"],
            "censored": outcomes["censored_no_future_trade"],
            "rejection_share_conditional_on_first_passage": outcomes["rejection_first"] / conclusive if conclusive else None,
            "median_signed_terminal_ticks": statistics.median(points) if points else None,
            "median_time_to_first_passage_seconds": statistics.median(passage_times) if passage_times else None,
        }
    return result


def research(spec: dict, raw: bytes, profile_backend: str = "python") -> dict:
    validate_spec(spec)
    if profile_backend not in ("python", "cpp", "auto"):
        raise ValueError("profile backend must be python, cpp or auto")
    if profile_backend == "cpp":
        # Fail early even when the sample contains no eligible session pairs.
        from importlib import import_module
        try:
            import_module("company._nq_cpp")
        except ModuleNotFoundError as exc:
            if exc.name != "company._nq_cpp":
                raise
            raise RuntimeError(
                "C++ research kernel not built; run python setup.py build_ext --inplace"
            ) from exc
    if hash_bytes(raw) != spec["data_sha256"]:
        raise ValueError("research input checksum mismatch")
    trades = read_trades(raw, spec["contract"], spec["max_trades"])
    sessions = rth_groups(trades, time_hhmm(spec["rth_start"]), time_hhmm(spec["rth_end"]))
    keys = sorted(sessions)
    events = []
    used = []
    excluded = {}
    profiles = {}
    control_rng = random.Random(spec["seed"])
    for i in range(1, len(keys)):
        old_key, today = keys[i - 1], keys[i]
        gap = (datetime.fromisoformat(today).date() - datetime.fromisoformat(old_key).date()).days
        old, current = sessions[old_key], sessions[today]
        if gap > spec["max_gap_calendar_days"]:
            excluded[today] = "large_calendar_gap"
            continue
        if len(old) < spec["min_profile_trades"] or len(current) < spec["min_eval_trades"]:
            excluded[today] = "insufficient_trade_coverage"
            continue
        profile = volume_profile(old, spec["value_area_fraction"], backend=profile_backend)
        levels = profile_levels(profile)
        profiles[old_key] = profile
        key_prices = {p for _, p in levels}
        candidates = [
            p for p in sorted({t.price_ticks for t in old})
            if all(abs(p - named) > spec["touch_tolerance_ticks"] + 4 for named in key_prices)
        ]
        if candidates:
            levels.append(("CONTROL", control_rng.choice(candidates)))
        # Auto selects native only on large groups with a built extension.
        # Record the backend actually used, not just the requested mode.
        native_used = profile_backend == "cpp"
        if profile_backend == "auto" and len(old) >= 20_000:
            from importlib.util import find_spec
            native_used = find_spec("company._nq_cpp") is not None
        used.append({"profile_date": old_key, "evaluation_date": today,
                     "profile_last_event_ns": old[-1].timestamp_ns,
                     "evaluation_first_event_ns": current[0].timestamp_ns,
                     "aggregation_backend_used": "cpp" if native_used else "python"})
        for kind, px in levels:
            event = first_touch(current, px, spec["touch_tolerance_ticks"],
                                spec["excursion_ticks"], spec["horizon_seconds"] * BILLION)
            if event:
                events.append({
                    "kind": kind, "session_date": today, "prior_profile_date": old_key,
                    "profile_level_points": px / 4,
                    **event,
                })
    status = "descriptive_only" if len(used) >= spec["min_session_pairs"] else "insufficient_session_pairs"
    return {
        "employee": "quant-researcher-001",
        "study_id": spec["id"],
        "question": spec["question"],
        "falsifier": spec["falsifier"],
        "data_kind": spec["data_kind"],
        "data_source": spec["data_source"],
        "input_sha256": hash_bytes(raw),
        "contract": spec["contract"],
        "profile_method": "prior observed completed New York RTH session; one tick per histogram bin",
        "requested_aggregation_backend": profile_backend,
        "actual_aggregation_backends": sorted({r["aggregation_backend_used"] for r in used}),
        "data_admission": {
            "status": "not_checked",
            "independent_exchange_authentication": False,
            "independent_license_verification": False,
        },
        "rth_window": [spec["rth_start"], spec["rth_end"]],
        "session_pairs": used,
        "excluded_pairs": excluded,
        "prior_session_profiles": profiles,
        "events": events,
        "event_summary": summarize(events),
        "status": status,
        "independent_holdout": False,
        "tradable_edge_validated": False,
        "limitations": [
            "Price reactions are first-passage descriptions after the first printed touch; no order submission or fills.",
            "A cross without a printed touch is not a touch; missing quote/depth information can affect interpretation.",
            "The previous observed weekday is not a verified exchange-calendar session; omitted history is not inferred.",
            "The control is an unmatched random traded-price level, not a matched causal experiment.",
            "Within-day and across-level events are correlated; no significance claim or alpha promotion.",
            "A single exchange contract must be used; NQ and MNQ profiles/impact can differ.",
            "Trade aggressor side may be unknown; no resting-book absorption can be inferred from prints alone.",
            "HVN/LVN definitions, VA algorithm, window and horizons are explicitly heuristic and platform-dependent.",
            "Data need independent provenance, vendor permissions, full coverage and a prospective holdout.",
        ],
    }


def run(spec_path: Path, trades_path: Path, output_root: Path,
        profile_backend: str = "python",
        admission_manifest: Path | None = None) -> Path:
    frozen = Path(spec_path).read_bytes()
    spec = json.loads(frozen)
    raw = Path(trades_path).read_bytes()
    admission = None
    if admission_manifest is not None:
        from company.data_admission import admit_trades
        manifest_bytes = Path(admission_manifest).read_bytes()
        manifest = json.loads(manifest_bytes)
        if (manifest.get("contract") != spec.get("contract")
                or manifest.get("session_start") != spec.get("rth_start")
                or manifest.get("session_end") != spec.get("rth_end")
                or manifest.get("source_kind") != spec.get("data_kind")):
            raise ValueError("admission manifest contract/session/source kind must match research protocol")
        admission = admit_trades(manifest, raw)
        admission["manifest_sha256"] = hash_bytes(manifest_bytes)
    result = research(spec, raw, profile_backend=profile_backend)
    if admission is not None:
        result["data_admission"] = admission
    result["protocol_sha256"] = hash_bytes(frozen)
    result["engine_sha256"] = hash_bytes(Path(__file__).read_bytes())
    if "cpp" in result["actual_aggregation_backends"]:
        from importlib.util import find_spec
        native_spec = find_spec("company._nq_cpp")
        if native_spec is not None and native_spec.origin is not None:
            result["cpp_source_sha256"] = hash_bytes(
                Path(__file__).with_name("_nq_cpp.cpp").read_bytes()
            )
            result["cpp_binary_sha256"] = hash_bytes(Path(native_spec.origin).read_bytes())
    folder = Path(output_root) / spec["id"]
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.mkdir(exist_ok=False)
    (folder / "protocol.json").write_bytes(frozen)
    (folder / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    lines = [
        "# NQ/MNQ volume-profile level research: " + spec["id"], "",
        "Question: " + spec["question"], "Falsifier: " + spec["falsifier"],
        "Study status: " + result["status"] + "; **NOT a validated trading edge**.", "",
        "Contract: " + spec["contract"], "Source: " + spec["data_source"],
        "SHA-256: " + result["input_sha256"],
        "Prior-session/evaluation pairs: " + str(len(result["session_pairs"])), "",
        "| Level | Touches | Rejection first | Cross first | Unresolved | Censored |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for kind, summary in result["event_summary"].items():
        lines.append("| " + kind + " | " + " | ".join(
            str(summary[field]) for field in ("events", "rejection_first", "cross_first", "unresolved", "censored")
        ) + " |")
    lines += ["", "## Limitations", *["- " + x for x in result["limitations"]], "",
              "All metrics are descriptive. Levels were computed exclusively on earlier completed sessions.",
              "Independent review and new untouched data are required before any trading hypothesis.", ""]
    (folder / "research_note.md").write_text("\n".join(lines))
    return folder


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--trades", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, default=Path("research-runs"))
    parser.add_argument("--profile-backend", choices=("python", "cpp", "auto"),
                        default="python", help="opt-in C++ aggregation or availability-based auto")
    parser.add_argument("--admission-manifest", type=Path,
                        help="optional declared session/coverage integrity manifest")
    args = parser.parse_args()
    try:
        output = run(args.spec, args.trades, args.out_root,
                     profile_backend=args.profile_backend,
                     admission_manifest=args.admission_manifest)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, csv.Error) as error:
        parser.exit(2, "research rejected: " + str(error) + "\n")
    print(json.dumps({"employee": "quant-researcher-001", "artifacts": str(output)}))


if __name__ == "__main__":
    main()
