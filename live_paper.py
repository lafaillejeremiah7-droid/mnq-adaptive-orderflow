"""Continuously sample live Solana quotes and fill paper orders on subsequent quotes."""

import argparse
from contextlib import closing
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import time

from company import open_ledger
from solana_paper import QuotesUnavailable, cycle, journal_stats


def checkpoint(folder, c, report):
    """Archive the batch before pruning SQLite. Publish report and history together."""
    with closing(open_ledger(folder / "ledger.sqlite")) as db, db:
        db.execute("BEGIN IMMEDIATE")
        data = "\n".join(
            row[0] for row in db.execute("SELECT event FROM journal ORDER BY id")
        )
        if data:
            raw = (data + "\n").encode()
            stamp = report["last_quote_utc"][:10]
            digest = hashlib.sha256(raw).hexdigest()
            target = folder / "journal" / stamp / (digest + ".jsonl.gz")
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(raw, mtime=0))
            tmp.replace(target)
            totals = journal_stats(db, c)
            db.execute(
                "INSERT OR REPLACE INTO archived_stats VALUES(1,?)",
                (json.dumps(totals),),
            )
            db.execute("DELETE FROM journal")
    tmp = folder / "report.next"
    tmp.write_text(json.dumps(report, indent=2) + "\n")
    tmp.replace(folder / "report.json")


def publish(folder):
    def git(*args, check=True):
        return subprocess.run(["git", *args], cwd=folder, check=check)

    git("add", "ledger.sqlite", "report.json", "journal")
    if git("diff", "--cached", "--quiet", check=False).returncode:
        git("commit", "-qm", "Checkpoint live paper portfolio")
    for attempt in range(3):
        if git("push", "origin", "HEAD:paper-results", check=False).returncode == 0:
            return
        time.sleep(2**attempt)
    raise RuntimeError("Could not publish checkpoint")


def run(folder, config, seconds=None, push=False):
    folder.mkdir(parents=True, exist_ok=True)
    stop = time.monotonic() + seconds if seconds else float("inf")
    last_save = float("-inf")
    last_fills = 0
    delay = 15
    report = None
    while time.monotonic() < stop:
        started = time.monotonic()
        try:
            report = cycle(config, folder / "ledger.sqlite", live=True)
        except QuotesUnavailable as exc:
            delay = min(120, 2 * delay)
            print(f"Quotes unavailable. Retrying in {delay}s: {exc}", flush=True)
        else:
            delay = 15
            report.update(
                mode="live paper",
                target_poll_seconds=delay,
                signal_horizon_seconds=900 * config["lookback"],
            )
            if report["status"] == "TRIAL_ENDED":
                break
            fills = report["buys"] + report["sell_fills"]
            print(
                json.dumps(
                    {
                        k: report[k]
                        for k in (
                            "last_quote_utc",
                            "observations",
                            "buys",
                            "sell_fills",
                            "position",
                            "pending",
                            "net_vs_cash_usdc",
                            "unavailable_quotes",
                        )
                    }
                ),
                flush=True,
            )
            if started - last_save >= 300 or fills != last_fills:
                checkpoint(folder, config, report)
                if push:
                    publish(folder)
                last_save, last_fills = started, fills
        time.sleep(max(0, min(started + delay, stop) - time.monotonic()))
    if report:
        checkpoint(folder, config, report)
        if push:
            publish(folder)
    else:
        raise RuntimeError("No live quotes received during this run")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument(
        "--config", type=Path, default=Path("examples/solana-forward.json")
    )
    parser.add_argument(
        "--seconds", type=int, help="End this worker after a bounded session"
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Checkpoint to the paper-results checkout",
    )
    args = parser.parse_args()
    if args.seconds is not None and args.seconds < 1:
        parser.error("--seconds must be positive")
    run(args.directory, json.loads(args.config.read_text()), args.seconds, args.publish)
