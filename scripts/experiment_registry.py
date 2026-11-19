"""Append-only offline research records. See docs/experiment-registry.md."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time


class RegistryError(ValueError):
    """Invalid research record, missing history, or damaged registry."""


# Digests of the original, explicitly illustrative CSV fixtures. Keep old
# fingerprints when fixtures change so that renamed copies remain identifiable.
ILLUSTRATIVE_DIGESTS = {
    "fd38889af83861e19768e448c1a90d1aa3103b405ecf93ff32b063adddfdba86",
    "49dec818edaf1e6139cc050a69ddec144ae97c40e1ee3f544e896f17b15acad4",
}


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise RegistryError(f"Invalid JSON record: {exc}") from exc


def fields(obj, keys, name):
    if not isinstance(obj, dict) or set(obj) != set(keys.split()):
        raise RegistryError(f"{name} requires exactly these fields: {keys}")


def note(value, field):
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{field} requires nonempty text")


def integer(value, field, minimum=0):
    if type(value) is not int or value < minimum:
        raise RegistryError(f"{field} must be an integer >= {minimum}")


def window(value, name):
    if not isinstance(value, list) or len(value) != 2:
        raise RegistryError(f"{name} must be [start_ms,end_ms)")
    for ts in value:
        integer(ts, name)
    if value[0] >= value[1]:
        raise RegistryError(f"{name} window must have positive duration")
    return value


def verify_artifact(path, expected, kind):
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RegistryError("A lowercase SHA-256 dataset digest is required")
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise RegistryError("Artifact bytes disagree with the recorded SHA-256")
    if kind != "synthetic" and (
        expected in ILLUSTRATIVE_DIGESTS or "illustrative" in path.name.lower()
    ):
        raise RegistryError("Illustrative artifacts must be labeled synthetic")


def validate_spec(spec, dataset_path):
    fields(spec, "experiment_id question model_version git_commit seed dataset data_period "
           "windows features parameters hypotheses baseline acceptance_rule "
           "cost_assumptions drawdown_assumptions", "spec")
    for field in ("experiment_id", "question", "model_version", "baseline", "acceptance_rule",
                  "cost_assumptions", "drawdown_assumptions"):
        note(spec[field], field)
    if not isinstance(spec["git_commit"], str) or not re.fullmatch(
            r"[0-9a-f]{40}|[0-9a-f]{64}", spec["git_commit"]):
        raise RegistryError("git_commit must be a full Git object ID")
    integer(spec["seed"], "seed")
    dataset = spec["dataset"]
    fields(dataset, "id source kind sha256", "dataset")
    note(dataset["id"], "dataset.id")
    note(dataset["source"], "dataset.source")
    if dataset["kind"] not in ("historical", "synthetic", "unverified"):
        raise RegistryError("Unknown dataset kind")
    start, end = window(spec["data_period"], "data_period")
    if end > now_ms():
        raise RegistryError("Historical data period ends in the future")
    windows = spec["windows"]
    fields(windows, "training validation holdout", "windows")
    previous_end = start
    for name in ("training", "validation", "holdout"):
        lo, hi = window(windows[name], name)
        if lo < previous_end or hi > end:
            raise RegistryError(f"{name} window overlaps or falls outside the data period")
        previous_end = hi
    if not isinstance(spec["features"], dict) or not isinstance(spec["parameters"], dict):
        raise RegistryError("features and parameters must be objects")
    for key, definition in spec["features"].items():
        note(key, "feature name")
        note(definition, "feature definition")
    hypotheses = spec["hypotheses"]
    if not isinstance(hypotheses, list) or not hypotheses:
        raise RegistryError("List every planned hypothesis")
    for hypothesis in hypotheses:
        note(hypothesis, "hypothesis")
    if len(set(hypotheses)) != len(hypotheses):
        raise RegistryError("Duplicate planned hypotheses")
    verify_artifact(dataset_path, dataset["sha256"], dataset["kind"])


def metrics(values):
    if not isinstance(values, dict):
        raise RegistryError("metrics must map names to finite numbers")
    for key, value in values.items():
        note(key, "metric name")
        if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
            raise RegistryError(f"{key} requires a finite metric value")


def validate_decision(value, spec):
    fields(value, "status metrics hypotheses_tested holdout_used reviewer findings rejection_reasons",
           "decision")
    if value["status"] not in ("REJECTED", "RETAINED_FOR_RESEARCH"):
        raise RegistryError("Unknown research decision")
    metrics(value["metrics"])
    integer(value["hypotheses_tested"], "hypotheses_tested")
    if type(value["holdout_used"]) is not bool:
        raise RegistryError("holdout_used must be boolean")
    note(value["reviewer"], "reviewer")
    note(value["findings"], "findings")
    reasons = value["rejection_reasons"]
    if not isinstance(reasons, list):
        raise RegistryError("rejection_reasons must be a list")
    for reason in reasons:
        note(reason, "rejection reason")
    if value["status"] == "REJECTED":
        if not reasons:
            raise RegistryError("Rejected trials require a reason")
    elif (reasons or not value["metrics"] or
          not 1 <= value["hypotheses_tested"] <= len(spec["hypotheses"])):
        raise RegistryError("Retained trials require metrics, a planned trial count and no rejection")


def now_ms():
    return time.time_ns() // 1_000_000


SCHEMA = """
CREATE TABLE events (
    experiment_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('registered','decided','observed')),
    recorded_ms INTEGER NOT NULL,
    payload TEXT NOT NULL,
    digest TEXT NOT NULL,
    PRIMARY KEY (experiment_id, seq)
);
CREATE UNIQUE INDEX one_registration_and_decision ON events(experiment_id, kind)
    WHERE kind != 'observed';
CREATE TRIGGER prevent_update BEFORE UPDATE ON events
    BEGIN SELECT RAISE(ABORT, 'registry is append-only'); END;
CREATE TRIGGER prevent_delete BEFORE DELETE ON events
    BEGIN SELECT RAISE(ABORT, 'registry is append-only'); END;
PRAGMA user_version = 1;
"""


def initialize(path):
    """Create a new database, refusing to replace even an empty existing file."""
    path = Path(path)
    try:
        with path.open("xb"):
            pass
    except FileExistsError as exc:
        raise RegistryError("Registry path already exists") from exc
    with closing(sqlite3.connect(path)) as db:
        db.executescript("BEGIN IMMEDIATE;" + SCHEMA + "COMMIT;")


@contextmanager
def connection(path, write=False):
    uri = Path(path).resolve().as_uri() + ("?mode=rw" if write else "?mode=ro")
    try:
        with closing(sqlite3.connect(uri, uri=True, isolation_level=None)) as db:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise RegistryError("Unknown or uninitialized registry schema")
            yield db
            db.commit()
    except sqlite3.Error as exc:
        raise RegistryError(f"Cannot read or append registry: {exc}") from exc


def fingerprint(previous, experiment_id, seq, kind, when, payload):
    entry = [previous, experiment_id, seq, kind, when, payload]
    return hashlib.sha256(canonical(entry).encode("utf-8")).hexdigest()


def read_history(db, experiment_id):
    rows = db.execute("SELECT seq,kind,recorded_ms,payload,digest FROM events "
                      "WHERE experiment_id=? ORDER BY seq", (experiment_id,))
    previous = None
    state = {"experiment_id": experiment_id, "decision": None, "observations": []}
    for expected_seq, (seq, kind, when, encoded, digest) in enumerate(rows):
        try:
            payload = json.loads(encoded)
        except (TypeError, ValueError) as exc:
            raise RegistryError("Invalid JSON in registry history") from exc
        if (seq != expected_seq or
            fingerprint(previous, experiment_id, seq, kind, when, payload) != digest):
            raise RegistryError("Experiment history failed fingerprint verification")
        if kind == "registered" and seq == 0:
            state.update(registered_at=when, spec=payload)
        elif kind == "decided" and seq == 1:
            state["decision"] = {**payload, "recorded_at": when}
        elif kind == "observed" and seq >= 2 and state["decision"]:
            state["observations"].append({**payload, "recorded_at": when})
        else:
            raise RegistryError("Experiment history is incomplete or out of order")
        previous = digest
    if previous is None:
        raise RegistryError(f"No experiment history for {experiment_id!r}")
    return {**state, "head_sha256": previous}


def history(path, experiment_id, expected_head=None):
    with connection(path) as db:
        result = read_history(db, experiment_id)
        if expected_head is not None and expected_head != result["head_sha256"]:
            raise RegistryError("History differs from the retained checkpoint")
        return result


def append(db, experiment_id, kind, payload, state=None):
    seq = 0 if state is None else 1 + int(state["decision"] is not None) + len(state["observations"])
    previous = state["head_sha256"] if state else None
    when = now_ms()
    if state:
        previous_at = state["registered_at"]
        if state["decision"]:
            previous_at = state["decision"]["recorded_at"]
        if state["observations"]:
            previous_at = state["observations"][-1]["recorded_at"]
        if when < previous_at:
            raise RegistryError("Registry clock precedes the last event")
    digest = fingerprint(previous, experiment_id, seq, kind, when, payload)
    db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
               (experiment_id, seq, kind, when, canonical(payload), digest))
    return digest


def register(path, spec, dataset_path):
    validate_spec(spec, dataset_path)
    with connection(path, write=True) as db:
        return append(db, spec["experiment_id"], "registered", spec)


def prior_exposures(db, state):
    """Find reported earlier evaluations that touched this proposed holdout."""
    spec = state["spec"]
    dataset = spec["dataset"]
    start, end = spec["windows"]["holdout"]
    matches = []
    ids = db.execute("SELECT experiment_id FROM events WHERE kind='decided' ORDER BY experiment_id")
    for (other_id,) in ids:
        other = read_history(db, other_id)
        source = other["spec"]["dataset"]
        if dataset["id"] != source["id"] and dataset["sha256"] != source["sha256"]:
            continue
        decision = other["decision"]
        used = ["training", "validation"] if decision["hypotheses_tested"] else []
        if decision["holdout_used"]:
            used.append("holdout")
        for name in used:
            lo, hi = other["spec"]["windows"][name]
            if start < hi and lo < end:
                matches.append({"experiment_id": other_id, "window": name})
    return matches


def decide(path, experiment_id, decision):
    with connection(path, write=True) as db:
        state = read_history(db, experiment_id)
        if state["decision"]:
            raise RegistryError("Decision already recorded")
        validate_decision(decision, state["spec"])
        exposures = prior_exposures(db, state) if decision["holdout_used"] else []
        record = {**decision, "prior_holdout_exposures": exposures}
        if exposures and decision["status"] == "RETAINED_FOR_RESEARCH":
            record.update(status="REJECTED", submitted_status=decision["status"],
                          rejection_reasons=["Final holdout overlaps a previously evaluated window"])
        return append(db, experiment_id, "decided", record, state)


def observe(path, experiment_id, observation, artifact_path):
    fields(observation, "period source kind sha256 sample_size metrics findings", "observation")
    start, end = window(observation["period"], "observation")
    if observation["kind"] not in ("forward_paper", "forward_live", "synthetic", "unverified"):
        raise RegistryError("Unknown observation kind")
    verify_artifact(artifact_path, observation["sha256"], observation["kind"])
    integer(observation["sample_size"], "sample_size", 1)
    metrics(observation["metrics"])
    note(observation["source"], "observation source")
    note(observation["findings"], "observation findings")
    with connection(path, write=True) as db:
        state = read_history(db, experiment_id)
        if state["decision"] is None:
            raise RegistryError("An independent observation requires a prior decision")
        earliest = state["decision"]["recorded_at"] + 1
        if state["observations"]:
            earliest = max(earliest, state["observations"][-1]["period"][1])
        if start < earliest or end > now_ms():
            raise RegistryError("Observation must be subsequent, disjoint and already completed")
        seen = {item["sha256"] for item in state["observations"]}
        seen.add(state["spec"]["dataset"]["sha256"])
        if observation["sha256"] in seen:
            raise RegistryError("Previously registered evidence cannot be reused as a new observation")
        return append(db, experiment_id, "observed", observation, state)


def list_experiments(path):
    with connection(path) as db:
        ids = db.execute("SELECT DISTINCT experiment_id FROM events ORDER BY experiment_id")
        summaries = []
        for (experiment_id,) in ids:
            state = read_history(db, experiment_id)
            result = state["decision"] or {}
            summaries.append({"experiment_id": experiment_id, "status": result.get("status", "PENDING"),
                              "hypotheses_tested": result.get("hypotheses_tested"),
                              "head_sha256": state["head_sha256"]})
        return summaries


def json_file(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RegistryError(f"Duplicate JSON key {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("list")
    reg = commands.add_parser("register")
    reg.add_argument("spec")
    reg.add_argument("dataset")
    dec = commands.add_parser("decide")
    dec.add_argument("experiment_id")
    dec.add_argument("decision")
    obs = commands.add_parser("observe")
    obs.add_argument("experiment_id")
    obs.add_argument("observation")
    obs.add_argument("artifact")
    show = commands.add_parser("show")
    show.add_argument("experiment_id")
    show.add_argument("--expected-head")
    args = parser.parse_args()
    path = args.database
    try:
        if args.command == "init":
            initialize(path)
            result = {"initialized": str(path)}
        elif args.command == "list":
            result = list_experiments(path)
        elif args.command == "register":
            result = register(path, json_file(args.spec), args.dataset)
        elif args.command == "decide":
            result = decide(path, args.experiment_id, json_file(args.decision))
        elif args.command == "observe":
            result = observe(path, args.experiment_id, json_file(args.observation), args.artifact)
        else:
            result = history(path, args.experiment_id, args.expected_head)
        print(json.dumps(result, indent=2, sort_keys=True))
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(2, f"Registry error: {exc}\n")


if __name__ == "__main__":
    main()
