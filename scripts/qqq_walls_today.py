"""Fetch latest available QQQ gamma walls using the AlgoX Flow public API.

On-demand HTTPS read only, no API key. This does NOT fetch any NQ price, stream
market prices, or place trades. Provider-calculated QQQ walls are distinguished
from the repository's separate, offline raw-option-chain calculator.

API docs / permissions: https://algoxflow.com/api-docs
Free CC BY 4.0 data; visible attribution required.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys
from urllib import error, request
from zoneinfo import ZoneInfo

from scripts.qqq_option_walls import nq_tick_round, parse_utc, positive_decimal

SOURCE_URL = "https://algoxflow.com/api/gexmap?ticker=QQQ"
ATTRIBUTION_URL = "https://algoxflow.com"
US_EASTERN = ZoneInfo("America/New_York")
CACHE_MINUTES = 15
MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_MAX_AGE_HOURS = 10


class DataUnavailable(ValueError):
    """No usable, current-session QQQ options wall snapshot."""


def decimal_or_none(value: object, name: str) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DataUnavailable(f"Provider {name} is invalid") from exc
    if not number.is_finite():
        raise DataUnavailable(f"Provider {name} must be finite")
    return number


def parse_response(
    raw: object,
    *,
    now: datetime | None = None,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> dict:
    """Validate provider-produced QQQ walls against the current ET trading day.

    'updated' is a provider computation/snapshot timestamp, NOT a verified
    QQQ last-trade timestamp. NQ conversions therefore remain approximate.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise DataUnavailable("Current clock must be timezone aware")
    current = current.astimezone(timezone.utc)
    if not isinstance(raw, dict):
        raise DataUnavailable("Provider response must be a JSON object")
    if raw.get("ticker") != "QQQ":
        raise DataUnavailable("Provider returned an instrument other than QQQ")
    if raw.get("error") or raw.get("stale") is True:
        raise DataUnavailable("Provider returned an error or explicitly stale data")
    try:
        asof = parse_utc(raw["updated"])
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise DataUnavailable("Provider lacks a valid UTC 'updated' timestamp") from exc
    age_seconds = (current - asof).total_seconds()
    if age_seconds < -30 or age_seconds > max_age_hours * 3600:
        raise DataUnavailable(
            f"Provider QQQ snapshot is future-dated or too old: {age_seconds / 3600:.1f} hours"
        )
    observed_date = asof.astimezone(US_EASTERN).date()
    today = current.astimezone(US_EASTERN).date()
    if observed_date != today:
        raise DataUnavailable(
            f"Not today's QQQ options data: snapshot {observed_date}, ET today {today}"
        )
    if isinstance(raw.get("spot"), bool) or isinstance(raw.get("callWall"), bool) or isinstance(raw.get("putWall"), bool):
        raise DataUnavailable("Provider price fields cannot be boolean")
    try:
        spot = positive_decimal(str(raw["spot"]), "QQQ spot")
        call = positive_decimal(str(raw["callWall"]), "QQQ call wall")
        put = positive_decimal(str(raw["putWall"]), "QQQ put wall")
    except (KeyError, TypeError, ValueError) as exc:
        raise DataUnavailable(f"Provider QQQ spot/callWall/putWall missing or invalid: {exc}") from exc
    # Reject responses that are catastrophically inconsistent with spot.
    # Gamma walls can be far away, but not multiple orders of magnitude.
    for name, level in (("callWall", call), ("putWall", put)):
        if level < spot / 2 or level > spot * 2:
            raise DataUnavailable(f"Provider {name} implausibly far from QQQ spot")

    result: dict = {
        "ticker": "QQQ",
        "source": "AlgoX Flow",
        "source_url": SOURCE_URL,
        "attribution": "Options gamma data by AlgoX Flow",
        "attribution_url": ATTRIBUTION_URL,
        "method": "PROVIDER_CALCULATED_GAMMA_WALLS",
        "scope": "provider nearest-expiry / potentially capped chain; not guaranteed full-chain",
        "as_of_utc": asof.isoformat(),
        "as_of_us_eastern": asof.astimezone(US_EASTERN).isoformat(),
        "quote_age_minutes_at_request": round(max(0, age_seconds) / 60, 1),
        "qqq_spot": str(spot),
        "qqq_spot_timestamp_note": "Provider spot timestamp not separately verified; 'updated' is snapshot time",
        "qqq_call_wall": str(call),
        "qqq_put_wall": str(put),
        "not_live": True,
        "nq_price_feed_enabled": False,
        "warning": (
            "Walls are vendor-modeled options positioning, not observed dealer books, "
            "guaranteed support/resistance, or trade signals. 15-minute cache applies."
        ),
    }
    optional_fields = {
        "gamma_flip": ("flip", "price"),
        "atm_iv_pct": ("atmIv", "percent"),
        "expected_move_qqq_points": ("expMove", "price"),
        "expected_move_pct": ("expMovePct", "percent"),
    }
    for output, (field, unit) in optional_fields.items():
        number = decimal_or_none(raw.get(field), field)
        if number is not None:
            if unit == "price" and number <= 0:
                continue
            if unit == "percent" and number < 0:
                continue
            result[output] = str(number)
    if isinstance(raw.get("regime"), str):
        result["provider_gamma_regime"] = raw["regime"]
    return result


def add_nq_equivalents(
    report: dict,
    *,
    nq_price: str,
    nq_asof: str,
    max_time_gap_seconds: int = 300,
) -> dict:
    """Use user-supplied NQ contract price near the provider's QQQ snapshot."""
    try:
        nq = positive_decimal(nq_price, "NQ reference price")
        nq_when = parse_utc(nq_asof)
        source_when = parse_utc(report["as_of_utc"])
    except (TypeError, ValueError, KeyError) as exc:
        raise DataUnavailable(f"Invalid NQ reference: {exc}") from exc
    gap = abs((nq_when - source_when).total_seconds())
    if gap > max_time_gap_seconds:
        raise DataUnavailable(
            f"NQ reference is {gap:.0f} seconds from QQQ snapshot "
            f"(max {max_time_gap_seconds}s). No equivalence calculated."
        )
    spot = Decimal(report["qqq_spot"])
    ratio = nq / spot
    updated = dict(report)
    updated["nq_reference_price"] = str(nq)
    updated["nq_reference_asof_utc"] = nq_when.isoformat()
    updated["nq_futures_contract"] = "USER_MUST_VERIFY_SELECTED_CONTRACT"
    updated["nq_conversion_ratio"] = str(ratio)
    updated["nq_call_wall_equivalent"] = str(
        nq_tick_round(Decimal(report["qqq_call_wall"]) * ratio)
    )
    updated["nq_put_wall_equivalent"] = str(
        nq_tick_round(Decimal(report["qqq_put_wall"]) * ratio)
    )
    updated["nq_conversion_warning"] = (
        "Approximate QQQ-to-NQ ratio, not native NQ options GEX. "
        "NQ price was supplied by the user, not downloaded by the agent. "
        "QQQ spot may have a different last-trade time than the provider snapshot."
    )
    return updated


def fetch_provider(timeout_seconds: int = 12) -> dict:
    req = request.Request(
        SOURCE_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "mnq-adaptive-orderflow/1.0 (research; AlgoX Flow attributed)",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            if getattr(response, "status", 200) != 200:
                raise DataUnavailable(f"Provider HTTP {response.status}")
            payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise DataUnavailable("Provider response too large")
        data = json.loads(payload)
    except (error.URLError, TimeoutError, OSError, ValueError) as exc:
        if isinstance(exc, DataUnavailable):
            raise
        raise DataUnavailable(f"AlgoX Flow QQQ request failed: {exc}") from exc
    if not isinstance(data, dict):
        raise DataUnavailable("Provider response is not a JSON object")
    return data


def load_with_cache(
    cache_path: Path,
    *,
    now: datetime | None = None,
    fetcher=fetch_provider,
) -> tuple[dict, str]:
    """Observe vendor's recommended >=15-minute on-demand fetch cadence."""
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        acquired = parse_utc(cached["fetched_at"])
        seconds = (moment - acquired).total_seconds()
        if 0 <= seconds < CACHE_MINUTES * 60 and isinstance(cached["response"], dict):
            return cached["response"], "local_cache"
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass
    fresh = fetcher()
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp = cache_path.with_name(cache_path.name + ".tmp")
        temp.write_text(
            json.dumps({"fetched_at": moment.isoformat(), "response": fresh}),
            encoding="utf-8",
        )
        temp.replace(cache_path)
    except OSError as exc:
        # Still allow one-shot use when filesystem cache is unavailable.
        print(f"WARNING unable to cache vendor snapshot: {exc}", file=sys.stderr)
    return fresh, "remote_fetch"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch today's free QQQ gamma walls; optional user-supplied NQ mapping"
    )
    parser.add_argument(
        "--nq-price", help="Optional NQ futures reference in index points, from YOUR chart"
    )
    parser.add_argument(
        "--nq-asof", help="Required with --nq-price: NQ reference timestamp UTC ISO-8601"
    )
    parser.add_argument(
        "--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS,
        help="Reject provider snapshots older than this number of hours (default 10)"
    )
    parser.add_argument(
        "--cache", type=Path,
        default=Path.home() / ".cache" / "mnq-adaptive-orderflow" / "qqq-gamma.json",
        help="Local 15-minute provider response cache"
    )
    args = parser.parse_args()
    if bool(args.nq_price) != bool(args.nq_asof):
        parser.error("--nq-price and --nq-asof must be provided together")
    if not 0.25 <= args.max_age_hours <= 24:
        parser.error("--max-age-hours must be between 0.25 and 24")
    try:
        now = datetime.now(timezone.utc)
        raw, fetch_method = load_with_cache(args.cache, now=now)
        report = parse_response(raw, now=now, max_age_hours=args.max_age_hours)
        report["retrieval_method"] = fetch_method
        if args.nq_price is not None:
            report = add_nq_equivalents(
                report, nq_price=args.nq_price, nq_asof=args.nq_asof
            )
        else:
            report["nq_equivalents"] = "NOT_CALCULATED: no matched NQ reference supplied"
    except DataUnavailable as exc:
        print(f"QQQ WALLS UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
