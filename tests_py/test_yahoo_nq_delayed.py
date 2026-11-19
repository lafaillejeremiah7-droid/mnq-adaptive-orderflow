"""No-network tests for free Yahoo NQ=F DELAYED price mode."""

from contextlib import redirect_stdout, redirect_stderr
from io import BytesIO, StringIO
import json
import unittest
from unittest.mock import patch

from scripts.yahoo_nq_delayed import (
    PriceUnavailable, decode_snapshot, fetch_snapshot, main,
)

STAMP = 1_800_000_000


def response(price=25000.25, stamp=STAMP, symbol="NQ=F", instrument_type="FUTURE"):
    return {
        "chart": {
            "error": None,
            "result": [
                {"meta": {
                    "symbol": symbol,
                    "instrumentType": instrument_type,
                    "currency": "USD",
                    "regularMarketPrice": price,
                    "regularMarketTime": stamp,
                }}
            ],
        }
    }


class DelayedYahooNQTests(unittest.TestCase):
    def test_exact_contract_price_and_provider_timestamp(self):
        millis, ticks, age = decode_snapshot(response(), STAMP + 600)
        self.assertEqual(millis, STAMP * 1000)
        self.assertEqual(ticks, 100001)
        self.assertEqual(age, 600)

    def test_reject_other_instruments(self):
        for symbol in ("^NDX", "QQQ", "MNQ=F", "NQH27"):
            with self.subTest(symbol=symbol), self.assertRaises(PriceUnavailable):
                decode_snapshot(response(symbol=symbol), STAMP + 600)

    def test_reject_non_futures(self):
        with self.assertRaises(PriceUnavailable):
            decode_snapshot(response(instrument_type="INDEX"), STAMP + 600)

    def test_reject_stale_quote(self):
        with self.assertRaisesRegex(PriceUnavailable, "STALE"):
            decode_snapshot(response(), STAMP + 3601)

    def test_reject_far_future_timestamp(self):
        with self.assertRaises(PriceUnavailable):
            decode_snapshot(response(), STAMP - 40)

    def test_reject_non_tick_price(self):
        with self.assertRaisesRegex(PriceUnavailable, "tick"):
            decode_snapshot(response(price=25000.13), STAMP + 900)

    def test_reject_missing_price(self):
        bad = response()
        del bad["chart"]["result"][0]["meta"]["regularMarketPrice"]
        with self.assertRaises(PriceUnavailable):
            decode_snapshot(bad, STAMP + 900)

    def test_provider_error_not_silent(self):
        bad = {"chart": {"result": None, "error": {"code": "Bad Request"}}}
        with self.assertRaises(PriceUnavailable):
            decode_snapshot(bad, STAMP + 900)

    def test_fetch_uses_unauthed_request(self):
        payload = json.dumps(response()).encode("utf-8")
        with patch(
            "scripts.yahoo_nq_delayed.request.urlopen", return_value=BytesIO(payload)
        ) as mock_open:
            quote = fetch_snapshot(now_seconds=STAMP + 600)
        self.assertEqual(quote, (STAMP * 1000, 100001, 600))
        args, kwargs = mock_open.call_args
        self.assertIn("NQ%3DF", args[0].full_url)
        self.assertEqual(kwargs["timeout"], 12)
        self.assertNotIn("Authorization", args[0].headers)

    def test_once_mode_outputs_only_price_csv(self):
        out, err = StringIO(), StringIO()
        with (
            patch("sys.argv", ["yahoo_nq_delayed.py", "--once"]),
            patch(
                "scripts.yahoo_nq_delayed.fetch_snapshot",
                return_value=(STAMP * 1000, 100001, 900),
            ),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = main()
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), f"{STAMP * 1000},100001")
        self.assertIn("DELAYED", err.getvalue())

    def test_once_stale_fails_closed(self):
        out, err = StringIO(), StringIO()
        with (
            patch("sys.argv", ["yahoo_nq_delayed.py", "--once"]),
            patch(
                "scripts.yahoo_nq_delayed.fetch_snapshot",
                side_effect=PriceUnavailable("STALE"),
            ),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = main()
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("STALE", err.getvalue())


if __name__ == "__main__":
    unittest.main()
