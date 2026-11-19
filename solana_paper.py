"""One forward paper cycle on Solana mainnet swap quotes, with no signing capability."""

import argparse
import email.utils
import json
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from company import config_digest, ingest, open_ledger, validate_config

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
ASSET = f"solana:{BONK}/{USDC}"
WIF = "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"
PAIRS = {ASSET: (BONK, 5), f"solana:{WIF}/{USDC}": (WIF, 6)}
DAY = 86400
ROUTE = "https://transaction-v1.raydium.io/compute/swap-base-in"


def quote_amount(src, dst, amount, max_age):
    query = urllib.parse.urlencode(
        {
            "inputMint": src,
            "outputMint": dst,
            "amount": amount,
            "slippageBps": 30,
            "txVersion": "V0",
        }
    )
    req = urllib.request.Request(
        ROUTE + "?" + query,
        headers={
            "Cache-Control": "no-cache",
            "User-Agent": "SolanaPaperDesk/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        when = int(
            email.utils.parsedate_to_datetime(response.headers["Date"]).timestamp()
        )
        now = int(time.time())
        if (
            not -2 <= now - when <= max_age
            or int(response.headers.get("Age", 0)) > max_age
        ):
            raise ValueError("Old provider response")
        payload = json.load(response)
    r = payload.get("data", {})
    if (
        payload.get("success") is not True
        or r.get("swapType") != "BaseIn"
        or r.get("inputMint") != src
        or r.get("outputMint") != dst
        or int(r["inputAmount"]) != amount
        or int(r.get("actualInputAmount", amount)) != amount
        or int(r["slippageBps"]) != 30
        or not r["routePlan"]
    ):
        raise ValueError("Swap quote does not match requested mints and amount")
    out = int(r["otherAmountThreshold"])
    if not 0 < out <= int(r["outputAmount"]):
        raise ValueError("Invalid minimum output")
    return out


def scout(c, asset=ASSET):
    mint, decimals = PAIRS[asset]
    start = int(time.time())
    usdc = int(Decimal(c["order_usd"]) * 10**6)
    buy = quote_amount(USDC, mint, usdc, c["max_age_seconds"])
    sell = quote_amount(mint, USDC, buy, c["max_age_seconds"])
    size = Decimal(buy).scaleb(-decimals)
    ask = Decimal(usdc).scaleb(-6) / size
    bid = Decimal(sell).scaleb(-6) / size
    # Timestamp the older leg. Recheck age after both requests.
    return {
        "asset": asset,
        "ts": start,
        "bid": str(bid.quantize(Decimal("1e-24"))),
        "ask": str(ask.quantize(Decimal("1e-24"))),
        "bid_size": str(size),
        "ask_size": str(size),
    }


def journal_stats(db, c):
    initial = Decimal(c["cash_usd"])
    row = db.execute("SELECT stats FROM archived_stats WHERE id=1").fetchone()
    archived = json.loads(row[0]) if row else {}
    peak = Decimal(archived.get("peak", initial))
    drawdown = Decimal(archived.get("drawdown", 0))
    entries = archived.get("entries", 0)
    exits = archived.get("exits", 0)
    closed = archived.get("closed", 0)
    observations = archived.get("observations", 0)
    first = archived.get("first")
    for (encoded,) in db.execute("SELECT event FROM journal ORDER BY id"):
        e = json.loads(encoded)
        if first is None:
            first = e["ts"]
        observations += 1
        entries += int(e["action"] == "paper_buy")
        exits += int(e["action"] == "paper_sell")
        closed += int(e["action"] == "paper_sell" and e["position"] is None)
        if "equity" not in e:
            continue
        equity = Decimal(e["equity"])
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return dict(
        peak=str(peak),
        drawdown=str(drawdown),
        entries=entries,
        exits=exits,
        closed=closed,
        observations=observations,
        first=first,
    )


def account_report(db, c, now):
    row = db.execute("SELECT state FROM desk WHERE id=1").fetchone()
    if not row:
        return {"status": "AWAITING_FIRST_QUOTE", "paper_orders": 0}
    s = json.loads(row[0])
    initial = Decimal(c["cash_usd"])
    stats = journal_stats(db, c)
    first = stats["first"]
    net = Decimal(s["last_equity"]) - initial
    status = "TRIAL_ENDED" if now >= first + 30 * DAY else "COLLECTING"

    def utc(ts):
        return datetime.fromtimestamp(ts, UTC).isoformat()

    return {
        "status": status,
        "pairs": ["BONK/USDC", "WIF/USDC"],
        "mode": "forward paper",
        "first_quote_utc": utc(first),
        "last_quote_utc": utc(s["clock"]),
        "last_quote_by_mint": {k: utc(v["ts"]) for k, v in s["last"].items()},
        "trial_end_utc": utc(first + 30 * DAY),
        "observations": stats["observations"],
        "buys": stats["entries"],
        "sell_fills": stats["exits"],
        "closed_trades": stats["closed"],
        "cash_usdc": s["cash"],
        "position": s["position"],
        "pending": s["pending"],
        "marked_liquidation_equity_usdc": s["last_equity"],
        "net_vs_cash_usdc": str(net),
        "return_percent": str(net / initial * 100),
        "max_observed_drawdown_usdc": stats["drawdown"],
        "daily_halt": s["halted"],
        "edge": "NOT_ESTABLISHED",
    }


class QuotesUnavailable(RuntimeError):
    pass


def cycle(c, path, *, live=False):
    validate_config(c)
    if c["tokens"] != {asset: pair[1] for asset, pair in PAIRS.items()}:
        raise ValueError(
            "Forward trial requires the pinned BONK and WIF mints and precision"
        )
    db = open_ledger(path)
    try:
        digest = config_digest(c, "raydium-forward-v1")
        prior = db.execute("SELECT config FROM desk WHERE id=1").fetchone()
        if live:
            live_digest = config_digest(c, "raydium-live-45m-v1")
            if prior and prior[0] == digest:
                # Preserve the account and exits; retire buy intents from the old cadence.
                with db:
                    state = json.loads(
                        db.execute("SELECT state FROM desk WHERE id=1").fetchone()[0]
                    )
                    if state["pending"] and state["pending"]["side"] == "buy":
                        state["pending"] = None
                    db.execute(
                        "UPDATE desk SET config=?,state=? WHERE id=1",
                        (live_digest, json.dumps(state)),
                    )
                prior = (live_digest,)
            digest = live_digest
        if prior and prior[0] != digest:
            raise ValueError("Use a separate ledger for a new configuration")
        report = account_report(db, c, int(time.time()))
        if report["status"] != "TRIAL_ENDED":
            errors = {}
            for asset in c["tokens"]:
                try:
                    q = scout(c, asset)
                    ingest(db, c, digest, q, int(time.time()), live=live)
                except (
                    OSError,
                    ValueError,
                    KeyError,
                    TypeError,
                    ArithmeticError,
                ) as exc:
                    errors[asset] = str(exc)
            if len(errors) == len(c["tokens"]):
                raise QuotesUnavailable(f"All routes unavailable: {errors}")
            report = account_report(db, c, int(time.time()))
            report["unavailable_quotes"] = errors
        return report
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument(
        "--config", type=Path, default=Path("examples/solana-forward.json")
    )
    args = parser.parse_args()
    print(json.dumps(cycle(json.loads(args.config.read_text()), args.db), indent=2))
