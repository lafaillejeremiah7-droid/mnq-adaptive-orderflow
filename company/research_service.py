"""Durable, local, research-only queued experiment runner.

SQLite ensures a single worker claims each job atomically, logs checksums,
persists failure, and requires explicit recovery. Worker processes may be
run interactively or by an external service manager. No broker integration,
data entitlement, independent model approval or live execution is provided.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from company import independent_validation, research_lab, research_pipeline, research_verify

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    protocol_path TEXT NOT NULL,
    data_path TEXT NOT NULL,
    out_root TEXT NOT NULL,
    protocol_sha256 TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued','running','completed','failed','interrupted')),
    attempt INTEGER NOT NULL DEFAULT 0,
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    artifact_path TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(state,created_utc,id);
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def open_store(db_path):
    """Always release SQLite connections, including on failed jobs."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.executescript(SCHEMA)
        with connection:
            yield connection
    finally:
        connection.close()


def enqueue(db_path, protocol_path, data_path, out_root):
    protocol_path = Path(protocol_path).resolve(strict=True)
    data_path = Path(data_path).resolve(strict=True)
    out_root = Path(out_root).resolve()
    spec_bytes = protocol_path.read_bytes()
    source_bytes = data_path.read_bytes()
    spec = json.loads(spec_bytes)
    research_lab.check_protocol(spec)
    if digest(source_bytes) != spec["source_sha256"]:
        raise ValueError("queue input does not match registered source SHA-256")
    with open_store(db_path) as conn:
        try:
            conn.execute(
                "INSERT INTO jobs(id, protocol_path, data_path, out_root, "
                "protocol_sha256,source_sha256,state,created_utc,updated_utc) "
                "VALUES(?,?,?,?,?,?,'queued',?,?)",
                (spec["id"], str(protocol_path), str(data_path), str(out_root),
                 digest(spec_bytes), digest(source_bytes), now(), now()),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("study ID already queued or processed; no duplicate runs") from exc
    return spec["id"]


def get_jobs(db_path, job_id=None):
    with open_store(db_path) as conn:
        if job_id is None:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_utc,id").fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchall()
    return [dict(row) for row in rows]


def worker_once(db_path):
    """Claim one queued experiment with a SQLite exclusive write transaction."""
    with open_store(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM jobs WHERE state='queued' ORDER BY created_utc,id LIMIT 1"
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            job = dict(row)
            conn.execute(
                "UPDATE jobs SET state='running',attempt=attempt+1,updated_utc=? WHERE id=?",
                (now(), job["id"]),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    try:
        source = Path(job["data_path"]).read_bytes()
        pbytes = Path(job["protocol_path"]).read_bytes()
        if digest(source) != job["source_sha256"] or digest(pbytes) != job["protocol_sha256"]:
            raise ValueError("queued source/protocol changed after registration")
        folder = research_pipeline.run(
            Path(job["protocol_path"]), Path(job["data_path"]), Path(job["out_root"])
        )
        software_replay = research_verify.verify(folder, Path(job["data_path"]))
        if not software_replay["research_replay_matches"]:
            raise RuntimeError("replay verification did not match")
        numeric = independent_validation.verify_files(folder, Path(job["data_path"]))
        with (folder / "numeric_validation.json").open("x") as outfile:
            json.dump(numeric, outfile, indent=2, sort_keys=True)
            outfile.write("\n")
        report = json.loads((folder / "adversarial_review.json").read_text())
        if report.get("production_ready") is not False or report.get("authorization_to_trade") is not False:
            raise RuntimeError("review has invalid safety certification flags")
        outcome = {
            "id": job["id"], "state": "completed", "artifact_path": str(folder),
            "automated_screen_passed": report["screen_passed"],
            "independent_human_validation": False, "production_ready": False,
        }
        with open_store(db_path) as conn:
            updated = conn.execute(
                "UPDATE jobs SET state='completed',updated_utc=?,artifact_path=?,error=NULL "
                "WHERE id=? AND state='running'",
                (now(), str(folder), job["id"]),
            )
            if updated.rowcount != 1:
                raise RuntimeError(
                    "job claim changed while executing; preserve artifacts for investigation"
                )
        return outcome
    except Exception as exc:
        # Never silently overwrite artifacts from an interrupted/failed run.
        with open_store(db_path) as conn:
            conn.execute(
                "UPDATE jobs SET state='failed',updated_utc=?,error=? "
                "WHERE id=? AND state='running'",
                (now(), f"{type(exc).__name__}: {exc}"[:2000], job["id"]),
            )
        return {"id": job["id"], "state": "failed", "error": f"{type(exc).__name__}: {exc}"}


def recover_interrupted(db_path, *, confirm_no_active_workers=False):
    """Only an operator who has stopped all workers may recover running jobs."""
    if not confirm_no_active_workers:
        raise ValueError("stop all workers and explicitly confirm no active workers")
    with open_store(db_path) as conn:
        cur = conn.execute(
            "UPDATE jobs SET state='interrupted',updated_utc=?,"
            "error='worker interrupted; inspect immutable run artifacts before retry' "
            "WHERE state='running'",
            (now(),),
        )
        return cur.rowcount


def retry(db_path, job_id):
    with open_store(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["state"] not in ("failed", "interrupted"):
                raise ValueError("retry requires an existing failed/interrupted study")
            if (Path(row["out_root"]) / job_id).exists():
                raise ValueError("partial immutable artifacts exist; inspect them and use a new study ID")
            conn.execute(
                "UPDATE jobs SET state='queued',updated_utc=?,error=NULL WHERE id=?",
                (now(), job_id),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("research-runs/jobs.sqlite3"))
    commands = parser.add_subparsers(dest="command", required=True)
    submit = commands.add_parser("enqueue", help="register a frozen research job")
    submit.add_argument("--protocol", type=Path, required=True)
    submit.add_argument("--data", type=Path, required=True)
    submit.add_argument("--out", type=Path, required=True)
    worker = commands.add_parser("worker", help="run a local worker once or repeatedly")
    worker.add_argument("--poll-seconds", type=int, default=0,
                        help="0 = once; positive = continue polling indefinitely")
    jobs = commands.add_parser("status", help="display saved study states")
    jobs.add_argument("--id")
    recover = commands.add_parser("recover", help="recover only after stopping all workers")
    recover.add_argument("--confirm-no-active-workers", action="store_true")
    redo = commands.add_parser("retry", help="retry a failed job only if no artifacts exist")
    redo.add_argument("--id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "enqueue":
            output = {"queued": enqueue(args.db, args.protocol, args.data, args.out)}
        elif args.command == "worker":
            if not 0 <= args.poll_seconds <= 3600:
                raise ValueError("poll_seconds must be between 0 and 3600")
            if args.poll_seconds:
                while True:
                    completed = worker_once(args.db)
                    if completed is not None:
                        print(json.dumps(completed, sort_keys=True), flush=True)
                    else:
                        time.sleep(args.poll_seconds)
            output = {"job": worker_once(args.db)}
        elif args.command == "status":
            output = {"jobs": get_jobs(args.db, args.id)}
        elif args.command == "recover":
            output = {"interrupted_jobs": recover_interrupted(
                args.db, confirm_no_active_workers=args.confirm_no_active_workers
            )}
        else:
            retry(args.db, args.id)
            output = {"queued": args.id}
    except (ValueError, OSError, TypeError, KeyError, sqlite3.Error) as exc:
        parser.exit(2, "research service rejected: " + str(exc) + "\n")
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
