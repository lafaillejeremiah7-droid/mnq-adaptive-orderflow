"""Forward paper trial for Pump.fun launches and graduated PumpSwap pools."""

import argparse
import json
import re
import subprocess
import time
from contextlib import closing
from decimal import ROUND_DOWN, Decimal
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from company import config_digest, ingest, open_ledger
from live_paper import checkpoint
from solana_paper import DAY, USDC, account_report

FEED = "https://frontend-api-v3.pump.fun/coins"
ROUTER = "https://api.jup.ag/swap/v1/quote"
STAGES = {
    "launch": ("Pump.fun", "bonding_curve", 120, 900),
    "graduated": ("Pump.fun Amm", "pool_address", 600, 3600),
}
NETWORK = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
TOKEN_PROGRAMS = {
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
}
ADDRESS = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
ERRORS = (ValueError, TypeError, KeyError, OSError, URLError)
SLOTS = 3
CONFIG = json.loads(
    (Path(__file__).parent / "examples/solana-forward.json").read_text()
)
CONFIG.update(tokens={}, max_gap_seconds=90, max_spread_bps="500")


def fetch(url, params, max_age):
    req = Request(
        url + "?" + urlencode(params),
        headers={
            "User-Agent": "SolanaPaperDesk/1.0",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(req, timeout=6) as r:
        stamp = int(parsedate_to_datetime(r.headers["Date"]).timestamp())
        if (
            not -2 <= time.time() - stamp <= max_age
            or int(r.headers.get("Age", 0)) > max_age
        ):
            raise ValueError("stale HTTP response")
        return json.loads(r.read(1_000_001)), stamp


def candidates(rows, stage, now):
    found = {}
    for row in rows:
        if not isinstance(row, dict) or not (
            row.get("chain_id") == NETWORK
            and row.get("program") == row.get("protocol") == "pump"
            and row.get("complete") is (stage == "graduated")
            and row.get("initialized") is True
            and all(row.get(k) is False for k in ("hidden", "is_banned", "nsfw"))
            and row.get("base_decimals") == 6
            and row.get("token_program") in TOKEN_PROGRAMS
            and row.get("transfer_fee_bps") == 0
            and not row.get("transfer_hook_program")
            and all(
                isinstance(row.get(k), str) and ADDRESS.fullmatch(row[k])
                for k in ("mint", "pool_address", "bonding_curve")
            )
            and type(row.get("created_timestamp")) is int
        ):
            continue
        age = now - row["created_timestamp"] // 1000
        if age < -2 or (stage == "launch" and age > 900):
            continue
        found[row["mint"]] = {k: row[k] for k in ("pool_address", "bonding_curve")}
    return found


def leg(src, dst, amount, mint, meta, allowed):
    r, stamp = fetch(
        ROUTER,
        {"inputMint": src, "outputMint": dst, "amount": amount, "slippageBps": 30},
        25,
    )
    if (
        r["inputMint"],
        r["outputMint"],
        r["inAmount"],
        r["swapMode"],
        r["slippageBps"],
    ) != (src, dst, str(amount), "ExactIn", 30):
        raise ValueError("quote mismatch")
    stages = set()
    for step in r["routePlan"]:
        swap = step["swapInfo"]
        if mint in (swap["inputMint"], swap["outputMint"]):
            stage = next(
                (
                    s
                    for s in allowed
                    if (swap["label"], swap["ammKey"])
                    == (STAGES[s][0], meta[STAGES[s][1]])
                ),
                None,
            )
            if (
                not stage
                or (swap["inputMint"] if src == mint else swap["outputMint"]) != mint
            ):
                raise ValueError("wrong Pump venue")
            stages.add(stage)
    out, slot = int(r["otherAmountThreshold"]), r["contextSlot"]
    if (
        len(stages) != 1
        or not 0 < out <= int(r["outAmount"])
        or type(slot) is not int
        or slot <= 0
    ):
        raise ValueError("unverified quote")
    return out, slot, stamp


def quote(mint, meta, stage, held):
    budget = int(Decimal(CONFIG["order_usd"]) * 10**6)
    if held:
        # Only the exit side is actionable. Keep the launch book responsible after migration.
        size = int(Decimal(held["qty"]) * 10**6)
        proceeds, slot2, stamp = leg(
            mint,
            USDC,
            size,
            mint,
            meta,
            ("launch", "graduated") if stage == "launch" else (stage,),
        )
        slot = slot2
        bid = ask = Decimal(proceeds) / size
        available = 0
    else:
        available, slot, t1 = leg(USDC, mint, budget, mint, meta, (stage,))
        size = available
        proceeds, slot2, stamp = leg(mint, USDC, size, mint, meta, (stage,))
        if (
            abs(slot2 - slot) > 60
            or abs(stamp - t1) > 20
            or time.time() - min(stamp, t1) > 25
        ):
            raise ValueError("legs too far apart")
        bid, ask = Decimal(proceeds) / size, Decimal(budget) / available
    if min(slot, slot2) <= meta.get("last_slot", 0):
        raise ValueError("repeated or older quote slot")
    # The paper broker limits quote precision and rounds position size down.
    return max(slot, slot2), {
        "asset": mint,
        "ts": min(stamp, int(time.time())),
        "bid": str(bid.quantize(Decimal("1e-32"), rounding=ROUND_DOWN)),
        "ask": str(ask.quantize(Decimal("1e-32"), rounding="ROUND_UP")),
        "bid_size": str(Decimal(size).scaleb(-6)),
        "ask_size": str(Decimal(available).scaleb(-6)),
    }


def desk(db):
    row = db.execute("SELECT state FROM desk WHERE id=1").fetchone()
    return json.loads(row[0]) if row else {}


def save(path, data):
    tmp = path.with_suffix(".next")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def scan(folder, stage, now):
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / "scan.json"
    scan = (
        json.loads(file.read_text())
        if file.exists()
        else {
            "watch": {},
            "last_scan": 0,
            "feed_rows": 0,
            "eligible_rows": 0,
            "quote_failures": 0,
        }
    )
    watch = scan["watch"]
    cfg = dict(CONFIG, signal_horizon_seconds=STAGES[stage][2])
    digest = config_digest(cfg, "pump-v1-" + stage)
    with closing(open_ledger(folder / "ledger.sqlite")) as db:
        state = desk(db)
        pos, pending = state.get("position"), state.get("pending")
        pinned = {
            x["asset"]
            for x in (pos, pending)
            if x and (x is pos or now - x["ts"] <= 60)
        }
        if now - scan["last_scan"] >= 60:
            scan["last_scan"] = now
            try:
                params = {
                    "offset": 0,
                    "limit": 30,
                    "sort": "created_timestamp"
                    if stage == "launch"
                    else "last_trade_timestamp",
                    "order": "DESC",
                    "includeNsfw": "false",
                }
                if stage == "graduated":
                    params["complete"] = "true"
                rows, _ = fetch(FEED, params, 90)
                if not isinstance(rows, list):
                    raise TypeError("invalid listings")
                eligible = candidates(rows, stage, now)
                scan.update(
                    feed_rows=len(rows), eligible_rows=len(eligible), feed_error=None
                )
                retiring = {
                    m
                    for m, v in watch.items()
                    if m not in pinned
                    and (now - v["added"] >= STAGES[stage][3] or v["misses"] >= 3)
                }
                for m in retiring:
                    del watch[m]
                for m, v in eligible.items():
                    if len(watch) >= SLOTS:
                        break
                    if m not in watch and m not in retiring:
                        watch[m] = dict(v, added=now, misses=0)
            except ERRORS as exc:
                scan["feed_error"] = str(exc)[:160]
        # Persist venue identities before a trade can create a held position.
        save(file, scan)
        # Drop price histories for retired mints. The immutable journal keeps their observations.
        with db:
            if state:
                for field in ("last", "timed_history", "history"):
                    state[field] = {
                        k: v for k, v in state.get(field, {}).items() if k in watch
                    }
                if pending and pending["side"] == "buy" and now - pending["ts"] > 60:
                    state["pending"] = None
                db.execute("UPDATE desk SET state=? WHERE id=1", (json.dumps(state),))
        cfg["tokens"] = dict.fromkeys(watch, 6)
        for m, meta in watch.items():
            position = desk(db).get("position")
            try:
                slot, q = quote(
                    m,
                    meta,
                    stage,
                    position if position and position["asset"] == m else None,
                )
                ingest(db, cfg, digest, q, int(time.time()), live=True)
                meta.update(misses=0, last_quote=q["ts"], last_slot=slot, error=None)
            except ERRORS as exc:
                meta.update(misses=meta["misses"] + 1, error=str(exc)[:160])
                scan["quote_failures"] += 1
        report = account_report(db, cfg, int(time.time()))
        report.pop("pairs", None)
        report.update(
            cohort=stage,
            mode="live paper",
            signal_horizon_seconds=STAGES[stage][2],
            watchlist=list(watch),
        )
        if report.get("position"):
            meta = watch[report["position"]["asset"]]
            report["position_mark_stale"] = bool(
                meta["misses"] or time.time() - meta.get("last_quote", 0) > 25
            )
        save(file, scan)
        return cfg, report


def run(folder, seconds, publish):
    folder.mkdir(parents=True, exist_ok=True)
    start_file = folder / "started.json"
    if not start_file.exists():
        save(start_file, int(time.time()))
    end = json.loads(start_file.read_text()) + 30 * DAY
    stop = time.monotonic() + seconds
    last_save = 0
    while time.monotonic() < stop and time.time() < end:
        start = time.monotonic()
        results = {s: scan(folder / s, s, int(time.time())) for s in STAGES}
        if (
            start - last_save >= 300
            or time.monotonic() + 20 >= stop
            or time.time() + 20 >= end
            or not last_save
        ):
            for s, (c, r) in results.items():
                checkpoint(folder / s, c, r)
            if publish:
                subprocess.run(
                    ["git", "add", "--", "started.json", *STAGES],
                    cwd=folder,
                    check=True,
                )
                if subprocess.run(
                    ["git", "diff", "--cached", "--quiet"], cwd=folder, check=False
                ).returncode:
                    subprocess.run(
                        ["git", "commit", "-qm", "Checkpoint Pump paper scans"],
                        cwd=folder,
                        check=True,
                    )
                subprocess.run(
                    ["git", "push", "origin", "HEAD:pump-paper-results"],
                    cwd=folder,
                    check=True,
                )
            print(
                {s: r.get("observations", 0) for s, (_, r) in results.items()},
                flush=True,
            )
            last_save = start
        time.sleep(max(0, min(stop, start + 20) - time.monotonic()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    run(args.directory, args.seconds, args.publish)
