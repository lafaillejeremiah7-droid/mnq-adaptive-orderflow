"""Synthetic unit tests; no market feed, provider calls, or real profitability."""
from bisect import bisect_left
import csv
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.agent_tournament import (
    Event, InputError, WORKERS, group_by_outcome_resolution, load_history,
    run_tournament, forecasts_for_event, score,
)

BASE = (1_700_000_000_000 // 60000) * 60000


def event(i, *, regime=None, outcome=None, resolved_minutes=1):
    start = BASE + i * 4 * 60 * 60000
    return Event(
        detected_at_ms=start,
        resolved_at_ms=start + resolved_minutes * 60000,
        regime=regime or ("TREND_UP" if i % 2 == 0 else "TREND_DOWN"),
        direction="LONG",
        target_distance_ticks=80,
        stop_distance_ticks=40,
        horizon_bars=10,
        outcome=outcome or (
            "TARGET_FIRST" if (i % 2 == 0) != ((i // 2) % 10 == 0)
            else "STOP_FIRST"
        ),
    )


def synth_events(n=600):
    return [event(i) for i in range(n)]


def write_csv(file, rows):
    with open(file, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "detected_at_ms", "resolved_at_ms", "regime", "direction",
            "target_distance_ticks", "stop_distance_ticks", "horizon_bars",
            "outcome",
        ])
        writer.writeheader()
        for row in rows:
            writer.writerow({field: getattr(row, field) for field in writer.fieldnames})


class AgentTournamentTests(unittest.TestCase):
    def test_four_independent_agents_compete_on_identical_prediction(self):
        rows = synth_events(80)
        prediction = forecasts_for_event(rows[79], rows[:79])
        self.assertEqual(set(prediction), {agent.name for agent in WORKERS})
        for p in prediction.values():
            self.assertGreater(p, 0)
            self.assertLess(p, 1)
        self.assertNotEqual(
            prediction["regime_specialist"], prediction["baseline_same_geometry"]
        )

    def test_clear_regime_signal_can_win_locked_test(self):
        report = run_tournament(synth_events())
        self.assertEqual(report["status"], "RESEARCH_CHAMPION_ONLY", report)
        self.assertIn(report["champion"], ("regime_specialist", "regime_recency_specialist"))
        self.assertGreater(
            report["final_holdout"]["paired_day_bootstrap_95pct_lower_improvement"],
            0,
        )
        self.assertGreaterEqual(report["samples"]["final_holdout_sessions_et"], 10)
        self.assertFalse(report["trade_execution"])
        self.assertFalse(report["live_price_feed"])

    def test_no_champion_for_all_same_outcomes(self):
        rows = [event(i, outcome="TARGET_FIRST") for i in range(600)]
        report = run_tournament(rows)
        self.assertEqual(report["status"], "NO_VALIDATED_WINNER")
        self.assertNotIn("champion", report)

    def test_no_champion_if_insufficient_samples(self):
        report = run_tournament(synth_events(45))
        self.assertEqual(report["status"], "NO_VALIDATED_WINNER")
        self.assertIn("Need >=", report["reason"])

    def test_no_lookahead_from_unresolved_event(self):
        early = event(0, outcome="TARGET_FIRST", resolved_minutes=10)
        soon = replace(
            event(1),
            detected_at_ms=early.detected_at_ms + 60000,
            resolved_at_ms=early.detected_at_ms + 2 * 60000,
        )
        catalog = group_by_outcome_resolution([early, soon])
        times, rows = catalog[soon.geometry]
        available = rows[:bisect_left(times, soon.detected_at_ms)]
        self.assertEqual(available, [])
        self.assertEqual(forecasts_for_event(soon, available)["baseline_same_geometry"], .5)

    def test_same_timestamp_has_no_self_label_access(self):
        first = event(0)
        second = replace(first, direction="SHORT")
        catalog = group_by_outcome_resolution([first, second])
        for row in (first, second):
            times, rows = catalog[row.geometry]
            self.assertEqual(bisect_left(times, row.detected_at_ms), 0)

    def test_fail_closed_when_history_unsorted(self):
        with TemporaryDirectory() as temp:
            file = Path(temp) / "unsorted.csv"
            write_csv(file, [event(1), event(0)])
            with self.assertRaisesRegex(InputError, "sorted"):
                load_history(file)

    def test_reject_duplicate_or_unresolved(self):
        with TemporaryDirectory() as temp:
            file = Path(temp) / "duplicates.csv"
            write_csv(file, [event(0), event(0)])
            with self.assertRaisesRegex(InputError, "Duplicate"):
                load_history(file)
            invalid = replace(event(0), resolved_at_ms=event(0).detected_at_ms)
            write_csv(file, [invalid])
            with self.assertRaisesRegex(InputError, "Resolution"):
                load_history(file)

    def test_reject_future_label_beyond_declared_horizon(self):
        with TemporaryDirectory() as temp:
            file = Path(temp) / "future.csv"
            invalid = replace(event(0), resolved_at_ms=event(0).detected_at_ms + 11 * 60000)
            write_csv(file, [invalid])
            with self.assertRaisesRegex(InputError, "horizon"):
                load_history(file)

    def test_round_trip_reproducible(self):
        with TemporaryDirectory() as temp:
            file = Path(temp) / "events.csv"
            rows = synth_events()
            write_csv(file, rows)
            self.assertEqual(load_history(file), rows)
            self.assertEqual(run_tournament(load_history(file)), run_tournament(rows))

    def test_time_limit_not_claimed_loss(self):
        row = event(0, outcome="TIME_LIMIT")
        self.assertEqual(row.label, 0)
        result = run_tournament([row])
        self.assertIn("not necessarily realized trading losses", result["assumption"])


if __name__ == "__main__":
    unittest.main()
