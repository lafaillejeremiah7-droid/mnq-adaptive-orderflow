"""Offline QQQ options walls and approximate NQ futures equivalents.

gex: rank call/put strikes by unsigned gamma exposure magnitude, separately.
oi: rank call/put strikes by open-interest contracts.
Neither proves actual dealer positioning or predictive support/resistance.
No network calls, market-data feeds, order entry, or account access.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path

TICK_NQ = Decimal("0.25")
QQQ_CONTRACT_SHARES = Decimal(100)
REQUIRED_COLUMNS = {"expiration", "option_type", "strike", "open_interest"}


class WallDataError(ValueError):
    """Invalid, incomplete, or misaligned QQQ/NQ research inputs."""


@dataclass(frozen=True)
class OptionContract:
    expiry: str
    kind: str
    strike: Decimal
    open_interest: int
    gamma: Decimal | None


def positive_decimal(value: str, label: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise WallDataError(f"Invalid {label}: {value!r}") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise WallDataError(f"{label} must be positive and finite")
    return parsed


def parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise WallDataError(f"Invalid UTC ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise WallDataError("Provide a UTC timestamp ending in Z or +00:00")
    return parsed.astimezone(timezone.utc)


def load_options(path: Path, *, expiry: str | None = None) -> list[OptionContract]:
    if expiry is not None:
        try:
            datetime.strptime(expiry, "%Y-%m-%d")
        except ValueError as exc:
            raise WallDataError("--expiration must be YYYY-MM-DD") from exc
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
                raise WallDataError(
                    "CSV requires expiration,option_type,strike,open_interest "
                    "(and gamma for gex)"
                )
            records: list[OptionContract] = []
            seen: set[tuple[str, str, Decimal]] = set()
            for line_number, row in enumerate(reader, start=2):
                if None in row:
                    raise WallDataError(f"Extra CSV columns on line {line_number}")
                expiry_text = (row["expiration"] or "").strip()
                try:
                    if datetime.strptime(expiry_text, "%Y-%m-%d").strftime("%Y-%m-%d") != expiry_text:
                        raise ValueError
                except ValueError as exc:
                    raise WallDataError(f"Invalid expiration on line {line_number}") from exc
                if expiry is not None and expiry_text != expiry:
                    continue
                kind = (row["option_type"] or "").strip().lower()
                if kind not in {"call", "put"}:
                    raise WallDataError(f"Invalid option_type on line {line_number}")
                strike = positive_decimal(row["strike"], "strike")
                try:
                    oi_text = (row["open_interest"] or "").strip()
                    if oi_text == "" or any(c not in "0123456789" for c in oi_text):
                        raise ValueError
                    oi = int(oi_text)
                except ValueError as exc:
                    raise WallDataError(f"Invalid open_interest on line {line_number}") from exc
                gamma_raw = row.get("gamma")
                gamma = None
                if gamma_raw is not None and gamma_raw.strip() != "":
                    try:
                        gamma = Decimal(gamma_raw)
                    except InvalidOperation as exc:
                        raise WallDataError(f"Invalid gamma on line {line_number}") from exc
                    if not gamma.is_finite() or gamma < 0:
                        raise WallDataError(f"Gamma must be finite and >= 0 on line {line_number}")
                if "multiplier" in row and (row["multiplier"] or "").strip():
                    try:
                        multiplier = Decimal(row["multiplier"])
                    except InvalidOperation as exc:
                        raise WallDataError(f"Invalid multiplier on line {line_number}") from exc
                    if multiplier != QQQ_CONTRACT_SHARES:
                        raise WallDataError(
                            f"Non-standard QQQ contract multiplier on line {line_number}"
                        )
                identifier = (expiry_text, kind, strike)
                if identifier in seen:
                    raise WallDataError(
                        f"Duplicate expiration/type/strike on line {line_number}"
                    )
                seen.add(identifier)
                records.append(OptionContract(expiry_text, kind, strike, oi, gamma))
    except OSError as exc:
        raise WallDataError(f"Cannot read options CSV: {exc}") from exc
    if not records:
        raise WallDataError("No QQQ option rows for the requested expiration scope")
    return records


def validate_snapshots(
    chain_asof: datetime,
    qqq_asof: datetime,
    nq_asof: datetime,
    *,
    max_quote_gap_seconds: int = 300,
    max_chain_lag_minutes: int = 30,
) -> None:
    quote_gap = abs((nq_asof - qqq_asof).total_seconds())
    if quote_gap > max_quote_gap_seconds:
        raise WallDataError(
            f"QQQ/NQ quotes are {quote_gap:.0f}s apart (max {max_quote_gap_seconds}s)"
        )
    for name, timestamp in (("QQQ", qqq_asof), ("NQ", nq_asof)):
        lag_minutes = (timestamp - chain_asof).total_seconds() / 60
        if lag_minutes < 0 or lag_minutes > max_chain_lag_minutes:
            raise WallDataError(
                f"{name} reference is {lag_minutes:.1f} minutes after options snapshot "
                f"(allowed 0 to {max_chain_lag_minutes})"
            )


def nq_tick_round(value: Decimal) -> Decimal:
    return (value / TICK_NQ).quantize(Decimal(1), rounding=ROUND_HALF_UP) * TICK_NQ


def wall_levels(
    rows: list[OptionContract],
    *,
    metric: str,
    qqq_reference: Decimal,
    nq_reference: Decimal,
) -> dict:
    if metric not in {"gex", "oi"}:
        raise WallDataError("Metric must be gex or oi")
    if qqq_reference <= 0 or nq_reference <= 0:
        raise WallDataError("QQQ and NQ prices must be positive")
    ratio = nq_reference / qqq_reference
    grouped: dict[str, dict[Decimal, Decimal]] = {"call": {}, "put": {}}
    for option in rows:
        if metric == "gex":
            if option.gamma is None:
                raise WallDataError(
                    f"Missing gamma for {option.kind} {option.strike} "
                    f"expiry {option.expiry}; rerun with --metric oi if intentional"
                )
            # Unsigned gamma exposure: delta-dollar change for a 1% QQQ move.
            amount = (
                Decimal(option.open_interest)
                * option.gamma
                * QQQ_CONTRACT_SHARES
                * qqq_reference
                * qqq_reference
                * Decimal("0.01")
            )
        else:
            amount = Decimal(option.open_interest)
        grouped[option.kind][option.strike] = (
            grouped[option.kind].get(option.strike, Decimal(0)) + amount
        )
    output = {"metric": metric, "nq_qqq_ratio": str(ratio)}
    for kind in ("call", "put"):
        eligible = {strike: value for strike, value in grouped[kind].items() if value > 0}
        if not eligible:
            raise WallDataError(f"No positive {metric} observations for {kind} options")
        # Deterministic tie-breaking: lower strike comes first.
        strike = min(eligible, key=lambda s: (-eligible[s], s))
        output[f"{kind}_wall"] = {
            "qqq_strike": str(strike),
            "nq_equivalent_points": str(nq_tick_round(strike * ratio)),
            "weight": str(eligible[strike]),
        }
    return output


def calculate(
    path: Path,
    *,
    metric: str,
    expiration: str | None,
    qqq_price: str,
    nq_price: str,
    qqq_asof: str,
    nq_asof: str,
    chain_asof: str,
) -> dict:
    qqq = positive_decimal(qqq_price, "QQQ reference price")
    nq = positive_decimal(nq_price, "NQ futures reference price")
    qqq_dt, nq_dt, chain_dt = map(parse_utc, (qqq_asof, nq_asof, chain_asof))
    validate_snapshots(chain_dt, qqq_dt, nq_dt)
    records = load_options(path, expiry=expiration)
    output = wall_levels(records, metric=metric, qqq_reference=qqq, nq_reference=nq)
    output.update(
        symbol="QQQ",
        equivalent_instrument="NQ_FUTURES",
        expiration_scope=expiration or "all supplied expirations",
        options_asof_utc=chain_dt.isoformat(),
        qqq_reference_price=str(qqq),
        qqq_reference_asof_utc=qqq_dt.isoformat(),
        nq_reference_price=str(nq),
        nq_reference_asof_utc=nq_dt.isoformat(),
        options_contract_count=len(records),
        source="USER_PROVIDED_SNAPSHOT",
        data_status="OFFLINE_NOT_CURRENT_VERIFIED",
        interpretation=(
            "GEX-weighted unsigned call/put gamma concentration, not dealer signed GEX"
            if metric == "gex"
            else "Open-interest concentration, NOT gamma walls"
        ),
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline QQQ options put/call wall levels mapped to NQ futures"
    )
    parser.add_argument("--chain", type=Path, required=True, help="QQQ option chain CSV")
    parser.add_argument("--metric", choices=["gex", "oi"], default="gex")
    parser.add_argument("--expiration", help="Optional filter, YYYY-MM-DD")
    parser.add_argument("--chain-asof", required=True, help="UTC ISO-8601 snapshot time")
    parser.add_argument("--qqq-price", required=True, help="QQQ dollars")
    parser.add_argument("--qqq-asof", required=True, help="UTC ISO-8601 quote time")
    parser.add_argument("--nq-price", required=True, help="NQ futures points")
    parser.add_argument("--nq-asof", required=True, help="UTC ISO-8601 quote time")
    args = parser.parse_args()
    try:
        output = calculate(
            args.chain,
            metric=args.metric,
            expiration=args.expiration,
            chain_asof=args.chain_asof,
            qqq_price=args.qqq_price,
            qqq_asof=args.qqq_asof,
            nq_price=args.nq_price,
            nq_asof=args.nq_asof,
        )
    except WallDataError as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
