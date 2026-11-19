"""No-key, independent, DELAYED NQ futures prices from Yahoo Finance.

This client reads an unofficial Yahoo Finance chart endpoint for NQ=F.
Quotes are NOT CME real-time, can be delayed or unavailable, and may be
blocked or rate-limited. Only use the output for personal research.
No browser, brokerage login, Databento key, order flow, or trades involved.

stdout format: as_of_utc_ms,price_in_quarter_point_ticks
stderr: warnings, quote age, and provider errors
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import json
import sys
import time
from urllib import error, request

URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/NQ%3DF"
    "?interval=1m&range=1d"
)
DEFAULT_MAX_AGE_SECONDS = 60 * 60


class PriceUnavailable(ValueError):
    """Provider did not supply a recent, valid delayed NQ futures price."""


def decode_snapshot(data: dict, now_seconds: int, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS):
    """Return (event_ms, integer_quarter_point_ticks, age_seconds).

    Never silently substitute Nasdaq-100 cash index (^NDX) or QQQ.
    Time is the provider-reported market timestamp, not fetch time.
    """
    try:
        chart = data["chart"]
        if chart.get("error"):
            raise PriceUnavailable(f"Yahoo Finance reported: {chart['error']}")
        results = chart["result"]
        if not isinstance(results, list) or len(results) != 1:
            raise PriceUnavailable("Missing NQ=F chart results")
        meta = results[0]["meta"]
        if meta.get("symbol") != "NQ=F":
            raise PriceUnavailable("Unexpected instrument: not NQ=F futures")
        if meta.get("instrumentType") not in (None, "FUTURE"):
            raise PriceUnavailable("Unexpected instrument type")
        if meta.get("currency") not in (None, "USD"):
            raise PriceUnavailable("Unexpected quote currency")
        stamp = meta.get("regularMarketTime")
        value = meta.get("regularMarketPrice")
        if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp <= 0:
            raise PriceUnavailable("Missing quote event timestamp")
        if isinstance(value, (bool, type(None))):
            raise PriceUnavailable("Missing quote price")
        ticks_decimal = Decimal(str(value)) * Decimal(4)
        if not ticks_decimal.is_finite() or ticks_decimal <= 0:
            raise PriceUnavailable("Invalid quote price")
        if ticks_decimal != ticks_decimal.to_integral_value():
            raise PriceUnavailable("Price is not aligned to a CME 0.25-point tick")
        ticks = int(ticks_decimal)
        if ticks > 1_000_000:
            raise PriceUnavailable("Quote exceeds supported NQ price range")
        age_seconds = now_seconds - stamp
        if age_seconds < -30:
            raise PriceUnavailable("Provider quote timestamp is in the future")
        if age_seconds > max_age_seconds:
            raise PriceUnavailable(
                f"STALE: last NQ quote is {age_seconds // 60} minutes old"
            )
        return stamp * 1000, ticks, max(0, age_seconds)
    except (KeyError, TypeError, IndexError, InvalidOperation, OverflowError) as exc:
        raise PriceUnavailable(f"Malformed Yahoo Finance NQ data: {exc}") from exc


def fetch_snapshot(now_seconds: int | None = None, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS):
    """Perform one unauthenticated Yahoo chart read with a strict timeout."""
    req = request.Request(
        URL,
        headers={
            "User-Agent": "MNQResearchAgent/1.0 (price-only; personal research)",
            "Accept": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=12) as response:
            payload = json.load(response)
    except (error.HTTPError, error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise PriceUnavailable(f"Yahoo Finance request unavailable: {exc}") from exc
    return decode_snapshot(
        payload,
        int(time.time()) if now_seconds is None else now_seconds,
        max_age_seconds,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Independent free DELAYED NQ=F futures price (no API key)"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Fetch one delayed NQ price, then exit (useful for testing)"
    )
    parser.add_argument(
        "--poll-seconds", type=int, default=60,
        help="Repeat poll interval, 30-3600 seconds, default 60"
    )
    parser.add_argument(
        "--max-age-minutes", type=int, default=60,
        help="Reject provider quotes older than this, default 60"
    )
    args = parser.parse_args()
    if not 30 <= args.poll_seconds <= 3600:
        parser.error("--poll-seconds must be between 30 and 3600")
    if not 15 <= args.max_age_minutes <= 1440:
        parser.error("--max-age-minutes must be between 15 and 1440")

    print(
        "Yahoo NQ=F DELAYED futures feed (unofficial, no API key). "
        "Never treat these as live or use for immediate trade execution.",
        file=sys.stderr, flush=True,
    )
    last_ms: int | None = None
    while True:
        try:
            ts_ms, ticks, age_seconds = fetch_snapshot(
                max_age_seconds=args.max_age_minutes * 60
            )
            if last_ms is None or ts_ms > last_ms:
                print(f"{ts_ms},{ticks}", flush=True)
                last_ms = ts_ms
                print(
                    f"NQ=F DELAYED update as_of_utc_ms={ts_ms} "
                    f"reported_quote_age={age_seconds // 60}min",
                    file=sys.stderr, flush=True,
                )
            elif ts_ms < last_ms:
                raise PriceUnavailable("Provider timestamp moved backwards")
            else:
                print(
                    f"NQ=F DELAYED quote unchanged "
                    f"(age={age_seconds // 60}min)",
                    file=sys.stderr, flush=True,
                )
        except PriceUnavailable as exc:
            print(f"NQ=F UNAVAILABLE (no new price): {exc}", file=sys.stderr, flush=True)
            if args.once:
                return 2

        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Delayed price monitoring stopped.", file=sys.stderr)
        sys.exit(130)
