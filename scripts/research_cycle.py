"""Run the registered four-policy forecast comparison and preserve its decision."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from scripts import agent_tournament as tournament
from scripts import experiment_registry as registry


ROOT = Path(__file__).resolve().parents[1]
MODEL = "first-touch-tournament-v2"
ACCEPTANCE = "Versioned validation margin and positive paired holdout lower Brier-gain bound"
FEATURES = {"regime": "Supplied regime at detection", "recency": "Order of prior released labels"}
PARAMETERS = {"min_prior": 50, "min_validation": 40, "min_holdout": 40, "min_test_days": 10,
              "validation_margin": 0.003, "embargo_minutes": 0, "block_days": 2}


def git(*args):
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    if result.returncode:
        raise ValueError("The registered source revision is unavailable in this checkout")
    return result.stdout


def check_revision(revision):
    for path in ("scripts/agent_tournament.py", "scripts/research_cycle.py",
                 "scripts/experiment_registry.py"):
        if git("show", revision + ":" + path) != (ROOT / path).read_bytes():
            raise ValueError(f"{path} differs from the registered revision")


def evaluate_spec(spec, data):
    if spec["model_version"] != MODEL or spec["baseline"] != tournament.WORKERS[0].name:
        raise ValueError("Registered model or benchmark differs from the implemented comparison")
    if spec["hypotheses"] != list(tournament.CHALLENGERS) or set(spec["parameters"]) != set(PARAMETERS):
        raise ValueError("Specify the three implemented challengers and all tournament parameters")
    if spec["acceptance_rule"] != ACCEPTANCE or spec["features"] != FEATURES:
        raise ValueError("Registered feature definitions or decision rule differ from this protocol")
    windows = spec["windows"]
    start, middle = windows["training"]
    val_start, end_validation = windows["validation"]
    test_start, end = windows["holdout"]
    if middle != val_start or end_validation != test_start or [start, end] != spec["data_period"]:
        raise ValueError("This runner requires contiguous registered train, validation and holdout windows")
    rows = tournament.load_history_bytes(data, as_of_ms=end-1)
    if any(row.detected_at_ms < start or row.label_time >= end for row in rows):
        raise ValueError("Label lies outside the registered half-open data period")
    kind = "synthetic" if spec["dataset"]["kind"] == "synthetic" else "unverified"
    return tournament.run_tournament(rows, as_of_ms=end-1, validation_start_ms=val_start,
                                     holdout_start_ms=test_start, seed=spec["seed"], evidence_kind=kind,
                                     **spec["parameters"])


def run(db, experiment, path):
    state = registry.history(db, experiment)
    if state["decision"] is not None:
        raise ValueError("Experiment already decided; consult its recorded decision")
    spec = state["spec"]
    check_revision(spec["git_commit"])
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != spec["dataset"]["sha256"]:
        raise ValueError("Input bytes differ from the registered dataset")
    decision = {"metrics": {}, "hypotheses_tested": 0, "holdout_used": False,
                "reviewer": MODEL, "status": "REJECTED", "rejection_reasons": []}
    try:
        result = evaluate_spec(spec, data)
    except ValueError as exc:
        decision["findings"] = "Data or experiment specification failed audit"
        decision["rejection_reasons"] = [str(exc)]
    else:
        final = result.get("final_holdout")
        decision["findings"] = result["reason"]
        if result.get("selection"):
            decision["hypotheses_tested"] = len(tournament.CHALLENGERS)
            decision["metrics"]["selection_brier_gain"] = result["selection"]["validation_brier_improvement"]
        # Scoring or inspecting even part of the final segment consumes its independence.
        decision["holdout_used"] = result.get("samples", {}).get("final_holdout") is not None
        if final:
            decision["metrics"]["holdout_brier_gain"] = final["improvement"]
            decision["metrics"]["holdout_lower_gain"] = final["paired_day_bootstrap_95pct_lower_improvement"]
        if result["status"] == "RESEARCH_CHAMPION_ONLY":
            decision["status"] = "RETAINED_FOR_RESEARCH"
        else:
            decision["rejection_reasons"] = [result["reason"]]
    registry.decide(db, experiment, decision)
    # The registry can veto retention when an evaluation period has been reused.
    return registry.history(db, experiment)["decision"]


def demo(db):
    path = ROOT / "examples/ILLUSTRATIVE_mnq_labeled_setups.csv"
    rows = tournament.load_history(path)
    start, end = rows[0].detected_at_ms, rows[-1].label_time + 1
    val, test = (rows[int(len(rows)*f)].detected_at_ms for f in (.6, .8))
    spec = {
        "experiment_id": "illustrative-forecast-audit", "question": "Do the three challengers beat the geometry baseline?",
        "model_version": MODEL, "git_commit": git("rev-parse", "HEAD").decode().strip(), "seed": 41,
        "dataset": {"id": "bundled-label-fixture", "source": "Repository engineering fixture",
                    "kind": "synthetic", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
        "data_period": [start, end], "windows": {"training": [start, val],
                     "validation": [val, test], "holdout": [test, end]},
        "features": FEATURES,
        "parameters": PARAMETERS, "hypotheses": list(tournament.CHALLENGERS),
        "baseline": tournament.WORKERS[0].name,
        "acceptance_rule": ACCEPTANCE,
        "cost_assumptions": "Forecast scores only; no fills or P&L",
        "drawdown_assumptions": "No account attached; research only",
    }
    check_revision(spec["git_commit"])
    registry.initialize(db)
    registry.register(db, spec, path)
    return run(db, spec["experiment_id"], path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    illustrative = sub.add_parser("demo", help="Run a synthetic comparison in a NEW registry")
    illustrative.add_argument("registry", type=Path)
    registered = sub.add_parser("run", help="Evaluate a registered specification once")
    registered.add_argument("registry", type=Path)
    registered.add_argument("experiment_id")
    registered.add_argument("history", type=Path)
    args = parser.parse_args()
    try:
        result = (demo(args.registry) if args.command == "demo" else
                  run(args.registry, args.experiment_id, args.history))
        print(json.dumps(result, indent=2, allow_nan=False))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Cannot run experiment: {exc}\n")


if __name__ == "__main__":
    main()
