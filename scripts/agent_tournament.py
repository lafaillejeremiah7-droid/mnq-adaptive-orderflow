"""Offline MNQ agent tournament: multiple research policies compete on ONE task.

Task: P(hypothetical target touched before stop), given labeled historical
events with fixed target/stop geometry. Every prediction sees only outcomes
resolved BEFORE that event's timestamp. A validation segment selects a
challenger, then an untouched chronological test segment judges it.

Workers are transparent, deterministic quantitative policies, NOT LLMs.
Nothing here reads current NQ prices, submits trades, or claims profitability.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import sys
from zoneinfo import ZoneInfo

REQUIRED = {
    "detected_at_ms", "resolved_at_ms", "regime", "direction",
    "target_distance_ticks", "stop_distance_ticks", "horizon_bars", "outcome",
}
REGIMES = {"TREND_UP", "TREND_DOWN", "RANGE", "VOLATILITY_SPIKE"}
DIRECTIONS = {"LONG", "SHORT"}
OUTCOMES = {"TARGET_FIRST", "STOP_FIRST", "TIME_LIMIT"}
NEW_YORK = ZoneInfo("America/New_York")


class InputError(ValueError):
    """Invalid input; never silently repair market history."""


@dataclass(frozen=True)
class Event:
    detected_at_ms: int
    resolved_at_ms: int
    regime: str
    direction: str
    target_distance_ticks: int
    stop_distance_ticks: int
    horizon_bars: int
    outcome: str

    @property
    def geometry(self) -> tuple[str, int, int, int]:
        return (
            self.direction, self.target_distance_ticks,
            self.stop_distance_ticks, self.horizon_bars,
        )

    @property
    def label(self) -> int:
        # Timeouts count as "not target-first" (NOT confirmed trading loss).
        return int(self.outcome == "TARGET_FIRST")


def parse_strict_positive(value: str | None, field: str) -> int:
    if value is None or not value.isdigit():
        raise InputError(f"{field} must be a nonnegative ASCII integer")
    number = int(value)
    if number <= 0:
        raise InputError(f"{field} must be positive")
    return number


def load_history(path: Path) -> list[Event]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
                raise InputError(f"Expected columns: {', '.join(sorted(REQUIRED))}")
            records = []
            seen = set()
            previous_detection = -1
            for line, row in enumerate(reader, 2):
                if None in row or any(row.get(k) is None for k in REQUIRED):
                    raise InputError(f"Malformed CSV row at line {line}")
                detected = parse_strict_positive(row["detected_at_ms"], "detected_at_ms")
                resolved = parse_strict_positive(row["resolved_at_ms"], "resolved_at_ms")
                regime = row["regime"].strip().upper()
                direction = row["direction"].strip().upper()
                outcome = row["outcome"].strip().upper()
                target = parse_strict_positive(row["target_distance_ticks"], "target_distance_ticks")
                stop = parse_strict_positive(row["stop_distance_ticks"], "stop_distance_ticks")
                horizon = parse_strict_positive(row["horizon_bars"], "horizon_bars")
                if regime not in REGIMES or direction not in DIRECTIONS or outcome not in OUTCOMES:
                    raise InputError(f"Unknown regime, direction, or outcome at line {line}")
                if not 1 <= horizon <= 500 or target > 1_000_000 or stop > 1_000_000:
                    raise InputError(f"Unsupported horizon or price distance at line {line}")
                if detected % 60000 or resolved % 60000:
                    raise InputError(f"Event timestamp not minute-aligned at line {line}")
                duration = resolved - detected
                if not 60000 <= duration <= horizon * 60000:
                    raise InputError(f"Resolution outside event horizon at line {line}")
                if detected < previous_detection:
                    raise InputError("CSV must be sorted by detected_at_ms; no silent resorting")
                previous_detection = detected
                event = Event(detected, resolved, regime, direction, target, stop, horizon, outcome)
                key = (detected, direction, target, stop, horizon, regime)
                if key in seen:
                    raise InputError(f"Duplicate hypothetical setup at line {line}")
                seen.add(key)
                records.append(event)
    except OSError as exc:
        raise InputError(f"Unable to read historical events: {exc}") from exc
    if not records:
        raise InputError("No historical labeled events supplied")
    return records


def smooth(observations: list[Event], baseline: float, strength: float) -> float:
    return (sum(x.label for x in observations) + baseline * strength) / (
        len(observations) + strength
    )


class BaselineAgent:
    name = "baseline_same_geometry"

    def forecast(self, event: Event, past: list[Event], base: float) -> float:
        return base


class RegimeSpecialist:
    name = "regime_specialist"

    def forecast(self, event: Event, past: list[Event], base: float) -> float:
        relevant = [row for row in past if row.regime == event.regime]
        return smooth(relevant, base, 20.0)


class RecencySpecialist:
    name = "recency_specialist"

    def forecast(self, event: Event, past: list[Event], base: float) -> float:
        recent = past[-80:]
        if not recent:
            return base
        weights = [0.5 ** ((len(recent) - i - 1) / 25.0) for i in range(len(recent))]
        success_weight = sum(w * row.label for w, row in zip(weights, recent))
        total = sum(weights)
        return (success_weight + 20.0 * base) / (total + 20.0)


class RegimeRecencySpecialist:
    name = "regime_recency_specialist"

    def forecast(self, event: Event, past: list[Event], base: float) -> float:
        relevant = [row for row in past if row.regime == event.regime][-80:]
        if not relevant:
            return base
        weights = [0.5 ** ((len(relevant) - i - 1) / 20.0) for i in range(len(relevant))]
        success_weight = sum(w * row.label for w, row in zip(weights, relevant))
        total = sum(weights)
        return (success_weight + 20.0 * base) / (total + 20.0)


WORKERS = (BaselineAgent(), RegimeSpecialist(), RecencySpecialist(), RegimeRecencySpecialist())
CHALLENGERS = tuple(worker.name for worker in WORKERS[1:])


def forecasts_for_event(event: Event, past: list[Event]) -> dict[str, float]:
    base = (1.0 + sum(row.label for row in past)) / (len(past) + 2.0)
    forecasts = {}
    for worker in WORKERS:
        prediction = worker.forecast(event, past, base)
        if not math.isfinite(prediction) or not 0 < prediction < 1:
            raise InputError(f"{worker.name} emitted an invalid probability")
        forecasts[worker.name] = prediction
    return forecasts


def loss(prediction: float, actual: int) -> float:
    return (prediction - actual) ** 2


def mean(values: list[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def score(predictions: list[tuple[Event, dict[str, float]]]) -> dict[str, float]:
    return {
        name: mean([loss(p[name], event.label) for event, p in predictions])
        for name in (worker.name for worker in WORKERS)
    }


def group_by_outcome_resolution(events: list[Event]):
    grouped = defaultdict(list)
    for row in events:
        grouped[row.geometry].append(row)
    return {
        key: (
            [row.resolved_at_ms for row in sorted(rows, key=lambda r: r.resolved_at_ms)],
            sorted(rows, key=lambda r: r.resolved_at_ms),
        )
        for key, rows in grouped.items()
    }


def evaluate_rows(
    events: list[Event],
    cutoff_times: tuple[int, int],
    min_prior: int,
) -> tuple[list, list, dict]:
    catalog = group_by_outcome_resolution(events)
    validation = []
    test = []
    skipped = {"validation_insufficient_prior": 0, "test_insufficient_prior": 0}
    for event in events:
        if event.detected_at_ms < cutoff_times[0]:
            continue
        times, resolved = catalog[event.geometry]
        available_count = bisect_left(times, event.detected_at_ms)  # strictly earlier
        phase = "validation" if event.detected_at_ms < cutoff_times[1] else "test"
        if available_count < min_prior:
            skipped[f"{phase}_insufficient_prior"] += 1
            continue
        past = resolved[:available_count]
        forecasts = forecasts_for_event(event, past)
        (validation if phase == "validation" else test).append((event, forecasts))
    return validation, test, skipped


def market_date(event: Event) -> str:
    return datetime.fromtimestamp(
        event.detected_at_ms / 1000, tz=timezone.utc
    ).astimezone(NEW_YORK).date().isoformat()


def block_bootstrap_improvement_lower_bound(
    test: list[tuple[Event, dict[str, float]]], challenger: str,
    *,
    iterations: int = 800,
    seed: int = 41,
) -> float:
    """Paired ET-day bootstrap, lower 2.5% improvement quantile.

    Bootstrapping cannot repair data leakage, strategy selection bias, or
    overlapping targets; it merely quantifies one dependence-aware check.
    """
    by_day: dict[str, list[float]] = defaultdict(list)
    for event, p in test:
        improvement = (
            loss(p["baseline_same_geometry"], event.label)
            - loss(p[challenger], event.label)
        )
        by_day[market_date(event)].append(improvement)
    days = sorted(by_day)
    random_gen = random.Random(seed)
    samples = []
    for _ in range(iterations):
        selected = [random_gen.choice(days) for _ in days]
        values = [x for day in selected for x in by_day[day]]
        samples.append(sum(values) / len(values))
    samples.sort()
    return samples[int((iterations - 1) * .025)]


def run_tournament(
    events: list[Event],
    *,
    min_prior: int = 50,
    min_validation: int = 40,
    min_holdout: int = 40,
    min_test_days: int = 10,
    validation_margin: float = 0.003,
) -> dict:
    """Select on middle chronological segment; confirm on last untouched one."""
    if min_prior < 1 or min_validation < 1 or min_holdout < 1 or min_test_days < 2:
        raise InputError("Sample minimums must be positive (test days >= 2)")
    if not 0 < validation_margin < 1:
        raise InputError("Validation Brier improvement margin must be between 0 and 1")
    times = sorted({x.detected_at_ms for x in events})
    report = {
        "task": "historical_target_before_stop_probability",
        "instrument": "MNQ_hypothetical_setup_labels",
        "source": "USER_SUPPLIED_OFFLINE_CSV",
        "agent_type": "DETERMINISTIC_POLICIES_NOT_LLMS",
        "num_agents": len(WORKERS),
        "agents": [worker.name for worker in WORKERS],
        "event_count": len(events),
        "data_validation": "PASSED",
        "status": "NO_VALIDATED_WINNER",
        "trade_execution": False,
        "live_price_feed": False,
        "assumption": "TARGET_FIRST is positive; STOP_FIRST and TIME_LIMIT are not target-first, not necessarily realized trading losses",
        "method": "chronological 60% development / 20% selection / 20% locked test by unique detection time; forecasts use only earlier-resolved same-geometry records",
        "notes": [
            "Candidate selection is based ONLY on validation, not final test.",
            "An accepted challenger beats same-geometry baseline on the final holdout with a positive ET-day bootstrap lower bound.",
            "No direct strategy P&L, fill simulation, predictive calibration proof, or current market signals.",
        ],
    }
    if len(times) < 10:
        report["reason"] = "Fewer than ten distinct chronological detection times"
        return report
    validation_start = times[int(0.6 * len(times))]
    holdout_start = times[int(0.8 * len(times))]
    report["periods"] = {
        "development_end_exclusive_ms": validation_start,
        "holdout_start_ms": holdout_start,
    }
    validation, test, skipped = evaluate_rows(
        events, (validation_start, holdout_start), min_prior
    )
    report["samples"] = {
        "validation": len(validation),
        "final_holdout": len(test),
        "final_holdout_sessions_et": len(set(market_date(event) for event, _ in test)),
        **skipped,
    }
    if len(validation) < min_validation:
        report["reason"] = f"Need >= {min_validation} eligible validation events"
        return report
    val_scores = score(validation)
    ranked = sorted(
        CHALLENGERS, key=lambda name: (val_scores[name], name)
    )
    report["validation_brier_by_agent"] = {
        name: round(val_scores[name], 6) for name in val_scores
    }
    chosen = ranked[0]
    improvement = val_scores["baseline_same_geometry"] - val_scores[chosen]
    report["selection"] = {
        "candidate": chosen,
        "validation_brier_improvement": round(improvement, 6),
        "minimum_required_improvement": validation_margin,
    }
    if improvement < validation_margin:
        report["reason"] = "No challenger improves the validation Brier score enough"
        return report
    if len(test) < min_holdout:
        report["reason"] = f"Need >= {min_holdout} eligible untouched test events"
        return report
    days = len(set(market_date(event) for event, _ in test))
    if days < min_test_days:
        report["reason"] = f"Need >= {min_test_days} distinct ET days in test"
        return report
    test_scores = score(test)
    lower_bound = block_bootstrap_improvement_lower_bound(test, chosen)
    test_improvement = test_scores["baseline_same_geometry"] - test_scores[chosen]
    report["final_holdout"] = {
        "selected_challenger": chosen,
        "baseline_brier": round(test_scores["baseline_same_geometry"], 6),
        "challenger_brier": round(test_scores[chosen], 6),
        "improvement": round(test_improvement, 6),
        "paired_day_bootstrap_95pct_lower_improvement": round(lower_bound, 6),
    }
    if test_improvement <= 0 or lower_bound <= 0:
        report["reason"] = "Selected agent did not demonstrate positive out-of-sample improvement"
        return report
    report["status"] = "RESEARCH_CHAMPION_ONLY"
    report["champion"] = chosen
    report["reason"] = "Out-of-sample Brier improvement passed configured evidence gates"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline multi-agent MNQ outcome competition")
    parser.add_argument("--history", type=Path, required=True, help="Chronologically sorted labeled setup CSV")
    parser.add_argument("--output", type=Path, help="Optional path to save JSON report (must not exist)")
    parser.add_argument("--min-prior", type=int, default=50)
    parser.add_argument("--min-validation", type=int, default=40)
    parser.add_argument("--min-holdout", type=int, default=40)
    parser.add_argument("--min-test-days", type=int, default=10)
    args = parser.parse_args()
    try:
        history = load_history(args.history)
        report = run_tournament(
            history,
            min_prior=args.min_prior,
            min_validation=args.min_validation,
            min_holdout=args.min_holdout,
            min_test_days=args.min_test_days,
        )
        data = json.dumps(report, indent=2) + "\n"
        if args.output is not None:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(data)
        print(data, end="")
    except (InputError, OSError) as exc:
        print(f"TOURNAMENT FAILED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
