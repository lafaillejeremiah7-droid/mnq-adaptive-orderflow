"""Offline MNQ agent tournament: multiple research policies compete on ONE task.

Task: P(hypothetical target touched before stop), given labeled historical
events with fixed target/stop geometry. Every prediction sees only outcomes
available strictly before the decision (with configurable embargo). Validation
selects one challenger before the prequential holdout comparison.

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
import io
import json
import math
from pathlib import Path
import random
import sys
import time
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
    feature_available_at_ms: int | None = None
    label_available_at_ms: int | None = None
    instrument: str | None = None
    contract: str | None = None
    setup_id: str | None = None

    @property
    def label_time(self) -> int:
        return self.resolved_at_ms if self.label_available_at_ms is None else self.label_available_at_ms

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
    if not value or len(value) > 19 or not value.isascii() or not value.isdecimal():
        raise InputError(f"{field} must be a positive ASCII integer")
    number = int(value)
    if number <= 0:
        raise InputError(f"{field} must be positive")
    return number


def assessment_cutoff(as_of_ms: int | None) -> int:
    now = time.time_ns() // 1_000_000
    if as_of_ms is None:
        return now
    if type(as_of_ms) is not int or not 0 < as_of_ms <= now:
        raise InputError("Assessment as-of time must be a positive UTC timestamp through the present")
    return as_of_ms


def audit_history(events: list[Event], as_of_ms: int | None) -> None:
    cutoff = assessment_cutoff(as_of_ms)
    if not events:
        raise InputError("No historical labeled events supplied")
    seen = set()
    previous_detection = -1
    series = None
    for line, event in enumerate(events, 2):
        if not isinstance(event, Event):
            raise InputError(f"Invalid event record at line {line}")
        detected, resolved = event.detected_at_ms, event.resolved_at_ms
        for name in ("detected_at_ms", "resolved_at_ms", "target_distance_ticks",
                     "stop_distance_ticks", "horizon_bars"):
            value = getattr(event, name)
            if type(value) is not int or value < 1:
                raise InputError(f"{name} must be a positive integer at line {line}")
        categories = ((event.regime, REGIMES), (event.direction, DIRECTIONS), (event.outcome, OUTCOMES))
        if any(not isinstance(value, str) or value not in allowed for value, allowed in categories):
            raise InputError(f"Unknown regime, direction, or outcome at line {line}")
        if event.horizon_bars > 500 or max(event.target_distance_ticks, event.stop_distance_ticks) > 1_000_000:
            raise InputError(f"Unsupported horizon or price distance at line {line}")
        if detected % 60_000 or resolved % 60_000:
            raise InputError(f"Event timestamp not minute-aligned at line {line}")
        duration = resolved - detected
        horizon = event.horizon_bars * 60_000
        if not 60_000 <= duration <= horizon:
            raise InputError(f"Resolution outside event horizon at line {line}")
        if event.outcome == "TIME_LIMIT" and duration != horizon:
            raise InputError(f"TIME_LIMIT before the declared horizon at line {line}")
        features = event.feature_available_at_ms
        if features is not None and (type(features) is not int or not 0 < features <= detected):
            raise InputError(f"Features unavailable at detection at line {line}")
        if type(event.label_time) is not int or event.label_time < resolved:
            raise InputError(f"Label availability precedes resolution at line {line}")
        if event.label_time > cutoff:
            raise InputError(f"Future observation or label after assessment as-of time at line {line}")
        if detected < previous_detection:
            raise InputError("CSV must be sorted by detected_at_ms; no silent resorting")
        previous_detection = detected
        key = (detected, event.geometry)
        if key in seen:
            raise InputError(f"Duplicate hypothetical setup or conflicting label at line {line}")
        seen.add(key)
        if event.instrument is not None and event.instrument not in ("MNQ", "NQ"):
            raise InputError(f"Unsupported instrument at line {line}")
        identity = (event.instrument, event.contract, event.setup_id)
        if any(v is not None and (not isinstance(v, str) or not v.strip()) for v in identity):
            raise InputError(f"Invalid series identity at line {line}")
        if series is not None and identity != series:
            raise InputError(f"Mixed instrument, contract or setup definitions at line {line}")
        series = identity


def load_history(path: Path, *, as_of_ms: int | None = None) -> list[Event]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise InputError(f"Unable to read historical events: {exc}") from exc
    return load_history_bytes(data, as_of_ms=as_of_ms)


def load_history_bytes(data: bytes, *, as_of_ms: int | None = None) -> list[Event]:
    """Audit exactly the immutable CSV bytes fingerprinted by a research coordinator."""
    try:
        with io.StringIO(data.decode("utf-8-sig"), newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
                raise InputError(f"Expected columns: {', '.join(sorted(REQUIRED))}")
            if len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise InputError("Duplicate CSV column name")
            records = []
            for line, row in enumerate(reader, 2):
                if None in row or None in row.values():
                    raise InputError(f"Malformed CSV row at line {line}")
                numbers = {
                    key: parse_strict_positive(row[key], key)
                    for key in ("detected_at_ms", "resolved_at_ms", "target_distance_ticks",
                                "stop_distance_ticks", "horizon_bars", "feature_available_at_ms",
                                "label_available_at_ms") if key in row
                }
                records.append(Event(
                    **numbers,
                    regime=row["regime"].strip().upper(),
                    direction=row["direction"].strip().upper(),
                    outcome=row["outcome"].strip().upper(),
                    **{key: row[key].strip() for key in ("instrument", "contract", "setup_id") if key in row},
                ))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise InputError(f"Unable to read historical events: {exc}") from exc
    audit_history(records, as_of_ms)
    return records


def smooth(observations: list[Event], baseline: float, strength: float) -> float:
    return (sum(x.label for x in observations) + baseline * strength) / (
        len(observations) + strength
    )


@dataclass(frozen=True)
class ForecastInput:
    detected_at_ms: int
    regime: str
    geometry: tuple[str, int, int, int]


class BaselineAgent:
    name = "baseline_same_geometry"

    def forecast(self, event: ForecastInput, past: list[Event], base: float) -> float:
        return base


class RegimeSpecialist:
    name = "regime_specialist"

    def forecast(self, event: ForecastInput, past: list[Event], base: float) -> float:
        relevant = [row for row in past if row.regime == event.regime]
        return smooth(relevant, base, 20.0)


class RecencySpecialist:
    name = "recency_specialist"

    def forecast(self, event: ForecastInput, past: list[Event], base: float) -> float:
        recent = past[-80:]
        if not recent:
            return base
        weights = [0.5 ** ((len(recent) - i - 1) / 25.0) for i in range(len(recent))]
        success_weight = sum(w * row.label for w, row in zip(weights, recent))
        total = sum(weights)
        return (success_weight + 20.0 * base) / (total + 20.0)


class RegimeRecencySpecialist:
    name = "regime_recency_specialist"

    def forecast(self, event: ForecastInput, past: list[Event], base: float) -> float:
        relevant = [row for row in past if row.regime == event.regime][-80:]
        if not relevant:
            return base
        weights = [0.5 ** ((len(relevant) - i - 1) / 20.0) for i in range(len(relevant))]
        success_weight = sum(w * row.label for w, row in zip(weights, relevant))
        total = sum(weights)
        return (success_weight + 20.0 * base) / (total + 20.0)


WORKERS = (BaselineAgent(), RegimeSpecialist(), RecencySpecialist(), RegimeRecencySpecialist())
CHALLENGERS = tuple(worker.name for worker in WORKERS[1:])


def forecasts_for_event(event: Event, past: list[Event], workers=WORKERS) -> dict[str, float]:
    # Workers receive only decision features, never this event's outcome or duration.
    decision = ForecastInput(event.detected_at_ms, event.regime, event.geometry)
    positive = 0
    previous_release = 0
    for row in past:
        if not previous_release <= row.label_time < event.detected_at_ms or row.label_time < row.resolved_at_ms:
            raise InputError("Prior outcomes must be available in release order strictly before prediction")
        if row.geometry != event.geometry or (
            row.instrument, row.contract, row.setup_id
        ) != (event.instrument, event.contract, event.setup_id):
            raise InputError("Prior outcomes must match event geometry and series")
        previous_release = row.label_time
        positive += row.label
    base = (1.0 + positive) / (len(past) + 2.0)
    forecasts = {}
    for worker in workers:
        prediction = worker.forecast(decision, past, base)
        if not math.isfinite(prediction) or not 0 < prediction < 1:
            raise InputError(f"{worker.name} emitted an invalid probability")
        forecasts[worker.name] = prediction
    return forecasts


def loss(prediction: float, actual: int) -> float:
    return (prediction - actual) ** 2


def mean(values: list[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def score(predictions: list[tuple[Event, dict[str, float]]]) -> dict[str, float | None]:
    return {
        name: mean([loss(p[name], event.label) for event, p in predictions])
        for name in (worker.name for worker in WORKERS)
    }


def group_by_outcome_resolution(events: list[Event]):
    grouped = defaultdict(list)
    for row in events:
        grouped[row.geometry].append(row)
    catalog = {}
    for key, rows in grouped.items():
        ordered = sorted(rows, key=lambda row: (row.label_time, row.resolved_at_ms, row.detected_at_ms))
        catalog[key] = ([row.label_time for row in ordered], ordered)
    return catalog


def score_period(events, catalog, *, min_prior, embargo_minutes, workers, selection_freeze_ms=None):
    scored = []
    embargo_ms = embargo_minutes * 60_000
    insufficient_prior = 0
    purged = 0
    for event in events:
        # Use the predeclared window even when a touch happens early. Using
        # its actual short duration here would favor quick resolutions.
        window_end = event.detected_at_ms + event.horizon_bars * 60_000
        if selection_freeze_ms is not None and max(window_end, event.label_time) + embargo_ms >= selection_freeze_ms:
            purged += 1
            continue
        times, ordered = catalog[event.geometry]
        available_count = bisect_left(times, event.detected_at_ms - embargo_ms)
        if available_count < min_prior:
            insufficient_prior += 1
            continue
        probabilities = forecasts_for_event(event, ordered[:available_count], workers)
        scored.append((event, probabilities))
    return scored, insufficient_prior, purged


def evaluate_rows(events: list[Event], cutoff_times: tuple[int, int], min_prior: int):
    """Compatibility helper for callers requesting all worker forecasts on both periods."""
    catalog = group_by_outcome_resolution(events)
    options = dict(min_prior=min_prior, embargo_minutes=0, workers=WORKERS)
    validation_rows = [e for e in events if cutoff_times[0] <= e.detected_at_ms < cutoff_times[1]]
    test_rows = [e for e in events if e.detected_at_ms >= cutoff_times[1]]
    validation, skipped_v, purged = score_period(
        validation_rows, catalog, selection_freeze_ms=cutoff_times[1], **options
    )
    test, skipped_t, _ = score_period(test_rows, catalog, **options)
    return validation, test, {
        "validation_insufficient_prior": skipped_v, "test_insufficient_prior": skipped_t,
        "validation_purged_at_holdout": purged,
    }


def market_date(event: Event) -> str:
    return datetime.fromtimestamp(
        event.detected_at_ms / 1000, tz=timezone.utc
    ).astimezone(NEW_YORK).date().isoformat()


def block_bootstrap_improvement_lower_bound(
    test: list[tuple[Event, dict[str, float]]], challenger: str,
    *,
    iterations: int = 800,
    seed: int = 41,
    block_days: int = 2,
) -> float:
    """Paired event-weighted lower percentile, circular blocks of observed ET dates."""
    by_day: dict[str, list[float]] = defaultdict(list)
    for event, probabilities in test:
        by_day[market_date(event)].append(
            loss(probabilities["baseline_same_geometry"], event.label)
            - loss(probabilities[challenger], event.label)
        )
    totals = [(sum(by_day[day]), len(by_day[day])) for day in sorted(by_day)]
    n = len(totals)
    if type(block_days) is not int or block_days < 1 or n < 2 * block_days:
        raise InputError("Bootstrap requires at least two full date blocks")
    if type(iterations) is not int or iterations < 40:
        raise InputError("Bootstrap needs at least 40 replicates for a 2.5% tail")
    rng = random.Random(seed)
    samples = []
    for _ in range(iterations):
        total = 0.0
        count = 0
        for offset in range(0, n, block_days):
            start = rng.randrange(n)
            for j in range(min(block_days, n - offset)):
                value, size = totals[(start + j) % n]
                total += value
                count += size
        samples.append(total / count)
    samples.sort()
    return samples[int((iterations - 1) * .025)]


def describe_agents(catalog, validation, embargo_minutes):
    """Describe a common historical prediction; never construct a current signal."""
    assumptions = (
        "Beta(1,1) smoothed frequency for identical geometry",
        "Same-regime subset shrunk toward the geometry baseline with weight 20",
        "Last 80 released labels with 25-observation half-life and baseline weight 20",
        "Last 80 same-regime released labels with 20-observation half-life and baseline weight 20",
    )
    scores = score(validation)
    recent = validation[-1] if validation else None
    past = []
    same_regime = []
    if recent:
        event, probabilities = recent
        times, ordered = catalog[event.geometry]
        past = ordered[:bisect_left(times, event.detected_at_ms - embargo_minutes * 60_000)]
        same_regime = [row for row in past if row.regime == event.regime]
    findings = {}
    for worker, assumption, subset in zip(
        WORKERS, assumptions, (past, same_regime, past[-80:], same_regime[-80:])
    ):
        positive = sum(row.label for row in subset)
        findings[worker.name] = {
            "assumption": assumption,
            "last_validation_detection_ms": recent[0].detected_at_ms if recent else None,
            "last_validation_forecast": probabilities[worker.name] if recent else None,
            "same_geometry_prior": len(past),
            "subset_target_first": positive,
            "subset_non_target_first": len(subset) - positive,
            "validation_predictions": len(validation),
            "validation_brier": scores[worker.name],
            "uncertainty": "Dependent label counts; individual probability uncertainty is unquantified.",
            "abstention": "No eligible validation forecast" if not recent else "Historical diagnostic only",
        }
    return findings


def run_tournament(
    events: list[Event],
    *,
    min_prior: int = 50,
    min_validation: int = 40,
    min_holdout: int = 40,
    min_test_days: int = 10,
    validation_margin: float = 0.003,
    as_of_ms: int | None = None,
    embargo_minutes: int = 0,
    block_days: int = 2,
    seed: int = 41,
    validation_start_ms: int | None = None,
    holdout_start_ms: int | None = None,
    evidence_kind: str = "unverified",
) -> dict:
    """Freeze selection at holdout start, then score a prequential update policy."""
    audit_history(events, as_of_ms)
    minimums = (min_prior, min_validation, min_holdout, min_test_days, block_days)
    if any(type(n) is not int or n < 1 for n in minimums) or min_test_days < 2:
        raise InputError("Sample minimums and block length must be positive integers (test days >= 2)")
    if type(seed) is not int:
        raise InputError("Bootstrap seed must be an integer")
    if type(embargo_minutes) is not int or embargo_minutes < 0:
        raise InputError("Embargo must be a nonnegative integer count of minutes")
    if type(validation_margin) not in (int, float) or not 0 < validation_margin < 1:
        raise InputError("Validation Brier improvement margin must be between 0 and 1")
    if evidence_kind not in ("unverified", "synthetic"):
        raise InputError("Label evidence must be declared synthetic or unverified")
    times = sorted({x.detected_at_ms for x in events})
    fixed_split = validation_start_ms is not None or holdout_start_ms is not None
    if fixed_split and not (
        type(validation_start_ms) is int and type(holdout_start_ms) is int
        and times[0] < validation_start_ms < holdout_start_ms <= times[-1]
    ):
        raise InputError("Specify ordered validation and holdout cutoffs within the observed period")
    report = {
        "task": "historical_target_before_stop_probability",
        "instrument": events[0].instrument,
        "source": "USER_SUPPLIED_OFFLINE_LABELS",
        "evidence_kind": evidence_kind,
        "edge_verdict": "EDGE_NOT_ESTABLISHED",
        "agent_type": "DETERMINISTIC_POLICIES_NOT_LLMS",
        "num_agents": len(WORKERS),
        "agents": [worker.name for worker in WORKERS],
        "event_count": len(events),
        "data_validation": "PASSED_STRUCTURAL_CHECKS",
        "market_data": {
            "contract": events[0].contract, "setup_id": events[0].setup_id,
            "last_detection_ms": times[-1],
            "last_label_available_ms": max(row.label_time for row in events),
            "assessment_as_of_ms": as_of_ms,
            "explicit_feature_availability_rows": sum(row.feature_available_at_ms is not None for row in events),
            "explicit_label_availability_rows": sum(row.label_available_at_ms is not None for row in events),
            "missing_verification": ["raw bar/print coverage", "independent provenance",
                                     "point-in-time revisions", "exchange session calendar"],
        },
        "status": "NO_VALIDATED_WINNER",
        "trade_execution": False,
        "live_price_feed": False,
        "assumption": "TARGET_FIRST is positive; STOP_FIRST and TIME_LIMIT are not target-first, not necessarily realized trading losses",
        "method": "Prequential common-event scores. Earlier released outcomes update forecasts. Fixed challenger selection before holdout.",
        "independent_review": {
            "validation_candidates": len(CHALLENGERS),
            "final_comparisons": 0,
            "embargo_minutes": embargo_minutes,
            "bootstrap_observed_et_dates_per_block": block_days,
            "bootstrap_seed": seed,
            "selection_control": "Three challengers on validation; one preselected comparison on final holdout.",
            "skeptic_objections": [
                "Prior trials or reuse of this holdout require independent experiment history.",
                "Block resampling assumes the chosen block length captures relevant dependence.",
                "Hypothetical first-touch probabilities do not establish after-cost expectancy.",
            ],
        },
        "agent_findings": describe_agents({}, [], embargo_minutes),
    }
    if not fixed_split and len(times) < 10:
        report["reason"] = "Fewer than ten distinct chronological detection times"
        return report
    if not fixed_split:
        validation_start_ms = times[int(0.6 * len(times))]
        holdout_start_ms = times[int(0.8 * len(times))]
    report["periods"] = {
        "selection_rule": "fixed_utc_cutoffs" if fixed_split else "60_20_20_unique_detection_times",
        "development_end_exclusive_ms": validation_start_ms,
        "holdout_start_ms": holdout_start_ms,
    }
    pre_holdout = [e for e in events if e.detected_at_ms < holdout_start_ms]
    catalog = group_by_outcome_resolution(pre_holdout)
    validation, skipped, purged = score_period(
        (e for e in pre_holdout if e.detected_at_ms >= validation_start_ms), catalog,
        min_prior=min_prior, embargo_minutes=embargo_minutes, workers=WORKERS,
        selection_freeze_ms=holdout_start_ms,
    )
    report["samples"] = {
        "validation": len(validation), "validation_insufficient_prior": skipped,
        "validation_purged_at_holdout": purged,
        "final_holdout": None, "final_holdout_sessions_et": None, "test_insufficient_prior": None,
    }
    report["agent_findings"] = describe_agents(catalog, validation, embargo_minutes)
    if len(validation) < min_validation:
        report["reason"] = f"Need >= {min_validation} eligible validation events"
        return report
    val_scores = score(validation)
    chosen = min(CHALLENGERS, key=lambda name: (val_scores[name], name))
    report["validation_brier_by_agent"] = {
        name: round(val_scores[name], 6) for name in val_scores
    }
    improvement = val_scores["baseline_same_geometry"] - val_scores[chosen]
    report["selection"] = {
        "candidate": chosen,
        "validation_brier_improvement": round(improvement, 6),
        "minimum_required_improvement": validation_margin,
    }
    if improvement < validation_margin:
        report["reason"] = "No challenger improves the validation Brier score enough"
        return report
    chosen_workers = tuple(w for w in WORKERS if w.name in (WORKERS[0].name, chosen))
    test, skipped, _ = score_period(
        (e for e in events if e.detected_at_ms >= holdout_start_ms),
        group_by_outcome_resolution(events), min_prior=min_prior,
        embargo_minutes=embargo_minutes, workers=chosen_workers,
    )
    days = len(set(market_date(event) for event, _ in test))
    report["samples"].update(final_holdout=len(test), final_holdout_sessions_et=days,
                             test_insufficient_prior=skipped)
    if len(test) < min_holdout:
        report["reason"] = f"Need >= {min_holdout} eligible holdout events"
        return report
    if days < max(min_test_days, 2 * block_days):
        report["reason"] = f"Need >= {max(min_test_days, 2 * block_days)} distinct ET days in test"
        return report
    baseline = WORKERS[0].name
    baseline_brier = sum(loss(p[baseline], event.label) for event, p in test) / len(test)
    challenger_brier = sum(loss(p[chosen], event.label) for event, p in test) / len(test)
    lower_bound = block_bootstrap_improvement_lower_bound(test, chosen, block_days=block_days, seed=seed)
    test_improvement = baseline_brier - challenger_brier
    report["independent_review"]["final_comparisons"] = 1
    report["final_holdout"] = {
        "selected_challenger": chosen,
        "baseline_brier": round(baseline_brier, 6),
        "challenger_brier": round(challenger_brier, 6),
        "improvement": round(test_improvement, 6),
        "paired_day_bootstrap_95pct_lower_improvement": round(lower_bound, 6),
    }
    if test_improvement <= 0 or lower_bound <= 0:
        report["reason"] = "Selected agent did not demonstrate positive out-of-sample improvement"
        return report
    report["status"] = "RESEARCH_CHAMPION_ONLY"
    report["champion"] = chosen
    report["reason"] = "Selected challenger cleared the configured Brier gates on the supplied labels"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline multi-agent MNQ outcome competition")
    parser.add_argument("--history", type=Path, required=True, help="Chronologically sorted labeled setup CSV")
    parser.add_argument("--output", type=Path, help="Optional path to save JSON report (must not exist)")
    parser.add_argument("--min-prior", type=int, default=50)
    parser.add_argument("--min-validation", type=int, default=40)
    parser.add_argument("--min-holdout", type=int, default=40)
    parser.add_argument("--min-test-days", type=int, default=10)
    parser.add_argument("--as-of-ms", type=int, help="Latest admissible UTC observation (default: now)")
    parser.add_argument("--embargo-minutes", type=int, default=0)
    parser.add_argument("--block-days", type=int, default=2, help="Consecutive observed ET dates per bootstrap block")
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--validation-start-ms", type=int)
    parser.add_argument("--holdout-start-ms", type=int)
    parser.add_argument("--evidence-kind", choices=("synthetic", "unverified"), default="unverified")
    args = parser.parse_args()
    try:
        history = load_history(args.history, as_of_ms=args.as_of_ms)
        report = run_tournament(
            history,
            as_of_ms=args.as_of_ms,
            embargo_minutes=args.embargo_minutes,
            block_days=args.block_days,
            seed=args.seed,
            validation_start_ms=args.validation_start_ms,
            holdout_start_ms=args.holdout_start_ms,
            evidence_kind="synthetic" if args.history.name.startswith("ILLUSTRATIVE_") else args.evidence_kind,
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
