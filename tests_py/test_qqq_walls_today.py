"""Offline mocked tests: no external HTTP or NQ futures feed required."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.qqq_walls_today import (
    DataUnavailable, add_nq_equivalents, fetch_provider, load_with_cache,
    parse_response, SOURCE_URL,
)

TIME = datetime(2026, 11, 18, 20, 30, tzinfo=timezone.utc)


def sample(**change):
    original = {
        "ticker": "QQQ",
        "updated": "2026-11-18T20:00:00Z",
        "spot": 600.0,
        "callWall": 610,
        "putWall": 590,
        "atmIv": 20.5,
        "flip": 595,
        "expMove": 8.5,
        "expMovePct": 1.42,
        "regime": "positive",
    }
    original.update(change)
    return original


class QQQWallAutoTests(unittest.TestCase):
    def test_provider_qqq_walls_and_provenance(self):
        report = parse_response(sample(), now=TIME)
        self.assertEqual(report["qqq_call_wall"], "610")
        self.assertEqual(report["qqq_put_wall"], "590")
        self.assertEqual(report["qqq_spot"], "600.0")
        self.assertEqual(report["atm_iv_pct"], "20.5")
        self.assertEqual(report["method"], "PROVIDER_CALCULATED_GAMMA_WALLS")
        self.assertTrue(report["not_live"])
        self.assertFalse(report["nq_price_feed_enabled"])
        self.assertIn("algoxflow.com", report["attribution_url"])

    def test_optional_nq_mapping_from_matched_price(self):
        report = parse_response(sample(), now=TIME)
        mapped = add_nq_equivalents(
            report, qqq_price="600.0", qqq_asof="2026-11-18T20:00:00Z",
            nq_price="24000", nq_asof="2026-11-18T20:01:00Z", now=TIME
        )
        self.assertEqual(mapped["nq_call_wall_equivalent"], "24400.00")
        self.assertEqual(mapped["nq_put_wall_equivalent"], "23600.00")
        self.assertEqual(mapped["nq_conversion_ratio"], "4E+1")  # 24000 / 600.0
        self.assertIn("user-supplied", mapped["nq_conversion_warning"])

    def test_rounding_nq_to_quarter_tick(self):
        report = parse_response(sample(callWall=610.25), now=TIME)
        mapped = add_nq_equivalents(
            report, qqq_price="600", qqq_asof="2026-11-18T20:00:00Z",
            nq_price="24001", nq_asof="2026-11-18T20:00:00Z", now=TIME
        )
        self.assertEqual(Decimal(mapped["nq_call_wall_equivalent"]) % Decimal(".25"), 0)

    def test_timestamp_mismatch_refuses_conversion(self):
        report = parse_response(sample(), now=TIME)
        with self.assertRaisesRegex(DataUnavailable, "apart"):
            add_nq_equivalents(
                report, qqq_price="600", qqq_asof="2026-11-18T20:00:00Z",
                nq_price="24000", nq_asof="2026-11-18T20:10:00Z", now=TIME
            )

    def test_vendor_update_after_hours_does_not_fake_qqq_trade_timestamp(self):
        late = datetime(2026, 11, 19, 3, 30, tzinfo=timezone.utc)
        provider = parse_response(
            sample(updated="2026-11-19T03:17:14Z"), now=late
        )
        # Both chart observations were at 3:55pm ET, whereas provider ran
        # after 10pm ET. This paired conversion is allowed and labelled.
        mapped = add_nq_equivalents(
            provider,
            qqq_price="668.65", qqq_asof="2026-11-18T20:55:00Z",
            nq_price="26700", nq_asof="2026-11-18T20:56:00Z",
            now=late,
        )
        self.assertEqual(mapped["qqq_reference_price"], "668.65")
        self.assertEqual(mapped["nq_reference_price"], "26700")
        self.assertIn("NOT the vendor", mapped["nq_conversion_warning"])

    def test_reject_cross_session_references(self):
        report = parse_response(sample(), now=TIME)
        with self.assertRaisesRegex(DataUnavailable, "session date"):
            add_nq_equivalents(
                report, qqq_price="600", qqq_asof="2026-11-17T20:00:00Z",
                nq_price="24000", nq_asof="2026-11-17T20:01:00Z",
                now=TIME,
            )

    def test_old_previous_session_refused(self):
        with self.assertRaisesRegex(DataUnavailable, "Not today's"):
            parse_response(sample(updated="2026-11-17T20:00:00Z"), now=TIME)

    def test_provider_stale_flag_refused(self):
        with self.assertRaisesRegex(DataUnavailable, "stale"):
            parse_response(sample(stale=True), now=TIME)

    def test_future_dated_rejected(self):
        with self.assertRaisesRegex(DataUnavailable, "future-dated"):
            parse_response(sample(updated="2026-11-18T22:00:00Z"), now=TIME)

    def test_explicit_age_limit(self):
        with self.assertRaisesRegex(DataUnavailable, "too old"):
            parse_response(sample(updated="2026-11-18T15:00:00Z"), now=TIME, max_age_hours=5)

    def test_wrong_ticker_rejected(self):
        with self.assertRaisesRegex(DataUnavailable, "other than QQQ"):
            parse_response(sample(ticker="^NDX"), now=TIME)

    def test_null_wall_fails_not_guessed(self):
        with self.assertRaisesRegex(DataUnavailable, "missing or invalid"):
            parse_response(sample(callWall=None), now=TIME)

    def test_far_away_wall_rejected(self):
        with self.assertRaisesRegex(DataUnavailable, "implausibly"):
            parse_response(sample(callWall=70000), now=TIME)

    def test_valid_data_is_cached_fifteen_minutes(self):
        with TemporaryDirectory() as folder:
            cache = Path(folder) / "wall.json"
            calls = []
            def fetch():
                calls.append(1)
                return sample()
            first, source = load_with_cache(cache, now=TIME, fetcher=fetch)
            second, cached_source = load_with_cache(
                cache, now=TIME + timedelta(minutes=10), fetcher=fetch
            )
            self.assertEqual(len(calls), 1)
            self.assertEqual(source, "remote_fetch")
            self.assertEqual(cached_source, "local_cache")
            self.assertEqual(first, second)
            third, new_source = load_with_cache(
                cache, now=TIME + timedelta(minutes=16), fetcher=fetch
            )
            self.assertEqual(len(calls), 2)
            self.assertEqual(new_source, "remote_fetch")
            self.assertEqual(third, first)

    def test_http_request_is_keyless_and_qqq_only(self):
        payload = json.dumps(sample()).encode()
        dummy = io.BytesIO(payload)
        with patch("scripts.qqq_walls_today.request.urlopen", return_value=dummy) as mock:
            out = fetch_provider()
            self.assertEqual(out["ticker"], "QQQ")
            args, kwargs = mock.call_args
            self.assertEqual(args[0].full_url, SOURCE_URL)
            self.assertNotIn("Authorization", args[0].headers)
            self.assertEqual(kwargs["timeout"], 12)


if __name__ == "__main__":
    unittest.main()
