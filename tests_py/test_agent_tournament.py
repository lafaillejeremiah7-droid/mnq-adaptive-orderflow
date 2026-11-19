"""Synthetic unit tests; no market feed, provider calls, or real profitability."""
from bisect import bisect_left
import csv
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from scripts.agent_tournament import (
    Event, InputError, WORKERS, group_by_outcome_resolution, load_history,
    run_tournament, forecasts_for_event, load_history_bytes, score_period,
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

    def test_audit_cannot_be_bypassed_by_python_callers(self):
        row = event(0)
        invalid_inputs = (
            ([], "No historical"),
            ([row, replace(row, regime="RANGE")], "Duplicate"),
            ([replace(row, outcome="TIME_LIMIT")], "TIME_LIMIT"),
            ([replace(row, feature_available_at_ms=row.detected_at_ms + 1)], "Features"),
            ([replace(row, label_available_at_ms=row.resolved_at_ms - 1)], "availability"),
            ([replace(row, horizon_bars=True)], "positive integer"),
            ([replace(row, direction=[])], "Unknown"),
            ([replace(row, instrument="MNQ"), replace(event(1), instrument="NQ")], "Mixed"),
        )
        for rows, message in invalid_inputs:
            with self.subTest(message=message), self.assertRaisesRegex(InputError, message):
                run_tournament(rows)

    def test_historical_as_of_rejects_future_observations_or_late_releases(self):
        row = event(0)
        with self.assertRaisesRegex(InputError, "Future"):
            run_tournament([row], as_of_ms=row.detected_at_ms - 1)
        with self.assertRaisesRegex(InputError, "Future"):
            run_tournament([replace(row, label_available_at_ms=row.resolved_at_ms + 1)],
                           as_of_ms=row.resolved_at_ms)
        with self.assertRaisesRegex(InputError, "through the present"):
            run_tournament([row], as_of_ms=10**18)

    def test_new_csv_fields_and_duplicate_headers(self):
        row = event(0)
        with TemporaryDirectory() as temp:
            path = Path(temp) / "events.csv"
            write_csv(path, [row])
            headers, values = path.read_text().splitlines()
            extra = "feature_available_at_ms,label_available_at_ms,instrument,contract,setup_id"
            data = (headers + "," + extra + "\n" + values + "," +
                    f"{row.detected_at_ms},{row.resolved_at_ms + 50},MNQ,MNQZ3,S1\n").encode()
            parsed = load_history_bytes(data)[0]
            self.assertEqual(parsed.label_time, row.resolved_at_ms + 50)
            self.assertEqual((parsed.contract, parsed.setup_id), ("MNQZ3", "S1"))
            with self.assertRaisesRegex(InputError, "Duplicate CSV column"):
                load_history_bytes((headers + ",regime\n" + values + ",RANGE").encode())

    def test_current_event_outcome_is_inaccessible_to_workers(self):
        class Probe:
            name = "probe"

            def forecast(self, decision, past, base):
                self.fields = set(vars(decision))
                return base
        probe = Probe()
        forecasts_for_event(event(1), [event(0)], workers=(probe,))
        self.assertEqual(probe.fields, {"detected_at_ms", "regime", "geometry"})
        with self.assertRaisesRegex(InputError, "strictly before"):
            forecasts_for_event(event(0), [event(1)])
        with self.assertRaisesRegex(InputError, "geometry"):
            forecasts_for_event(event(1), [replace(event(0), direction="SHORT")])

    def test_purge_uses_declared_horizon_and_late_release_at_selection_freeze(self):
        rows = synth_events(30)
        freeze = rows[20].detected_at_ms
        # Two different reasons to purge, including equality at the boundary.
        rows[18] = replace(rows[18], label_available_at_ms=freeze)
        rows[19] = replace(rows[19], detected_at_ms=freeze - 10 * 60000,
                           resolved_at_ms=freeze - 9 * 60000)
        options = dict(min_prior=1, min_validation=1, min_holdout=1, min_test_days=2,
                       validation_start_ms=rows[10].detected_at_ms, holdout_start_ms=freeze)
        first = run_tournament(rows, **options)
        self.assertEqual(first["samples"]["validation"], 8)
        self.assertEqual(first["samples"]["validation_purged_at_holdout"], 2)
        changed = [replace(r, outcome="STOP_FIRST") if i >= 18 else r for i, r in enumerate(rows)]
        second = run_tournament(changed, **options)
        self.assertEqual(first["selection"], second["selection"])
        self.assertEqual(first["validation_brier_by_agent"], second["validation_brier_by_agent"])

    def test_label_release_and_embargo_delay_updates_past_boundary(self):
        early = event(0, outcome="TARGET_FIRST")
        later = event(1)
        release = later.detected_at_ms - 60000
        early = replace(early, label_available_at_ms=release)
        catalog = group_by_outcome_resolution([early, later])
        options = dict(min_prior=1, workers=(WORKERS[0],))
        eligible, skipped, _ = score_period([later], catalog, embargo_minutes=0, **options)
        self.assertEqual(skipped, 0)
        self.assertAlmostEqual(eligible[0][1][WORKERS[0].name], 2 / 3)
        eligible, skipped, _ = score_period([later], catalog, embargo_minutes=1, **options)
        self.assertEqual((eligible, skipped), ([], 1))

    def test_holdout_is_untouched_on_failed_selection(self):
        rows = [event(i, outcome="TARGET_FIRST") for i in range(600)]
        with patch("scripts.agent_tournament.score_period", wraps=score_period) as scoring:
            report = run_tournament(rows)
        self.assertEqual(scoring.call_count, 1)
        self.assertIsNone(report["samples"]["final_holdout"])
        self.assertEqual(report["independent_review"]["final_comparisons"], 0)

    def test_holdout_has_one_fixed_comparison_and_never_promotes_synthetic_edge(self):
        rows = synth_events()
        with patch("scripts.agent_tournament.score_period", wraps=score_period) as scoring:
            report = run_tournament(rows, evidence_kind="synthetic", seed=512)
        self.assertEqual(scoring.call_count, 2)
        holdout_workers = [w.name for w in scoring.call_args.kwargs["workers"]]
        self.assertEqual(holdout_workers, [WORKERS[0].name, report["selection"]["candidate"]])
        self.assertEqual(report["independent_review"]["bootstrap_seed"], 512)
        self.assertEqual(report["evidence_kind"], "synthetic")
        self.assertEqual(report["edge_verdict"], "EDGE_NOT_ESTABLISHED")
        self.assertEqual(report["independent_review"]["final_comparisons"], 1)
        self.assertEqual(report["agent_findings"][WORKERS[0].name]["validation_predictions"],
                         report["samples"]["validation"])
        with self.assertRaisesRegex(InputError, "unverified"):
            run_tournament(rows, evidence_kind="LIVE_VERIFIED")

    def test_validation_only_regime_effect_is_rejected_in_final_test(self):
        rows = synth_events()
        # The held-out regime relationship reverses at the fixed cut. Freeze all
        # held-out releases beyond the segment to isolate this regime breakdown.
        freeze = rows[480].detected_at_ms
        release = rows[-1].resolved_at_ms
        for i in range(480, len(rows)):
            rows[i] = replace(rows[i], outcome="STOP_FIRST" if i % 2 == 0 else "TARGET_FIRST",
                              label_available_at_ms=release)
        result = run_tournament(rows, validation_start_ms=rows[360].detected_at_ms,
                                holdout_start_ms=freeze, seed=205)
        self.assertIn("selection", result)
        self.assertEqual(result["status"], "NO_VALIDATED_WINNER")
        self.assertLess(result["final_holdout"]["improvement"], 0)

    def test_fixed_cutoffs_require_both_and_bootstrap_needs_distinct_blocks(self):
        rows = synth_events()
        with self.assertRaisesRegex(InputError, "cutoffs"):
            run_tournament(rows, validation_start_ms=rows[300].detected_at_ms)
        with self.assertRaisesRegex(InputError, "integer"):
            run_tournament(rows, seed=True)
        report = run_tournament(rows, block_days=50)
        self.assertEqual(report["status"], "NO_VALIDATED_WINNER")
        self.assertIn("100 distinct", report["reason"])

    def test_round_trip_reproducible(self):
        with TemporaryDirectory() as temp:
            file = Path(temp) / "events.csv"
            rows = synth_events()
            write_csv(file, rows)
            self.assertEqual(load_history(file), rows)
            self.assertEqual(run_tournament(load_history(file)), run_tournament(rows))

    def test_time_limit_not_claimed_loss(self):
        row = event(0, outcome="TIME_LIMIT", resolved_minutes=10)
        self.assertEqual(row.label, 0)
        result = run_tournament([row])
        self.assertIn("not necessarily realized trading losses", result["assumption"])


if __name__ == "__main__":
    unittest.main()
