"""Combine offline research evidence and the independent OCaml account gate."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from scripts import agent_tournament as tournament
from scripts import experiment_registry as registry
from scripts import policy_validation as policy


ROOT = Path(__file__).resolve().parents[1]


def risk_review(snapshot, as_of_ms):
    if snapshot is None:
        return {
            "status": "DATA_UNVERIFIED", "reason": "No account snapshot or firm rule supplied",
            "provenance": "missing", "review_contracts": 0,
            "account": dict.fromkeys((
                "account_stage", "nominal_balance_cents", "marked_equity_cents",
                "realized_pnl_cents", "unrealized_pnl_cents", "high_water_reference_cents",
                "drawdown_floor_cents", "remaining_headroom_cents", "open_risk_cents",
                "daily_headroom_cents", "maximum_contracts", "remaining_trades",
            )),
            "sizing": None,
        }
    binary = ROOT / "_build/default/bin/risk_review.exe"
    if not binary.is_file():
        raise ValueError("Build the OCaml risk executable with 'dune build bin/risk_review.exe'")
    result = subprocess.run(
        [str(binary), "--as-of-ms", str(as_of_ms), str(snapshot)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise ValueError(f"Risk review failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def review(as_of_ms, *, history=None, ledger=None, snapshot=None,
           registry_path=None, experiment_id=None):
    if type(as_of_ms) is not int or not 0 <= as_of_ms <= time.time_ns() // 1_000_000:
        raise ValueError("Assessment time must be a past or present UTC epoch millisecond")
    if (registry_path is None) != (experiment_id is None):
        raise ValueError("Supply both the registry and experiment ID")
    risk = risk_review(snapshot, as_of_ms)
    scores = None
    performance = None
    artifacts = {}
    market = {"source": None, "instrument": None, "contract": None,
              "quality_verdict": "DATA_UNVERIFIED", "missing": ["Point-in-time setup labels"]}
    if history is not None:
        data = history.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        kind = "synthetic" if (digest in registry.ILLUSTRATIVE_DIGESTS or
                               "illustrative" in history.name.lower()) else "unverified"
        rows = tournament.load_history_bytes(data, as_of_ms=as_of_ms)
        market = {"source": history.name, "source_kind": kind, "sha256": digest,
                  "instrument": rows[0].instrument, "contract": rows[0].contract,
                  "quality_verdict": "PASSED_STRUCTURAL_CHECKS", "events": len(rows)}
        if registry_path is None:
            scores = tournament.run_tournament(rows, as_of_ms=as_of_ms, evidence_kind=kind)
            market.update(scores["market_data"])
        artifacts[digest] = "labels"
    if ledger is not None:
        spec, digest = policy.read_ledger(ledger)
        performance = policy.evaluate(spec, as_of_ms=as_of_ms)
        performance["ledger_sha256"] = digest
        artifacts[digest] = "ledger"
    registered = None
    if registry_path is not None:
        state = registry.history(registry_path, experiment_id)
        source = state["spec"]["dataset"]
        artifact = artifacts.get(source["sha256"])
        if artifact is None:
            raise ValueError("Registered experiment requires its matching label or ledger bytes")
        if source["kind"] == "synthetic":
            if artifact == "labels":
                market["source_kind"] = "synthetic"
            elif performance["source_kind"] != "synthetic":
                raise ValueError("Ledger provenance conflicts with synthetic registration")
        if state["registered_at"] > as_of_ms:
            raise ValueError("Experiment registration postdates assessment")
        decision = state["decision"]
        if decision and decision["recorded_at"] > as_of_ms:
            decision = None
        registered = {
            "experiment_id": experiment_id, "artifact": artifact, "dataset": source,
            "registered_at_ms": state["registered_at"], "recorded_decision": decision,
            "forward_observations": [o for o in state["observations"] if o["recorded_at"] <= as_of_ms],
        }
    no_forecasts = {w.name: {"forecast": None, "validation_predictions": 0,
                             "abstention": "No labeled history supplied"} for w in tournament.WORKERS}
    independent = {**(scores["independent_review"] if scores else {}),
                   "selection_status": scores["status"] if scores else "INSUFFICIENT_EVIDENCE",
                   "selection_reason": scores["reason"] if scores else "No labeled history",
                   "validation_brier": scores.get("validation_brier_by_agent") if scores else None,
                   "holdout": scores.get("final_holdout") if scores else None,
                   "policy_performance": performance, "experiment_history": registered,
                   "edge_verdict": "EDGE_NOT_ESTABLISHED"}
    if registered and registered["artifact"] == "labels":
        decision = registered["recorded_decision"]
        independent.update(selection_status=decision["status"] if decision else "PENDING",
                           selection_reason=decision["findings"] if decision else "Awaiting review")
        for value in no_forecasts.values():
            value["abstention"] = "Registry view displays the recorded decision without rescoring"
    status = risk["status"]
    verdict = {"NO_VALIDATED_EDGE": "EDGE_NOT_ESTABLISHED",
               "RESEARCH_REVIEW_ONLY": "EDGE_NOT_ESTABLISHED"}.get(status, status)
    return {
        "as_of_ms": as_of_ms, "account_status": {k: v for k, v in risk.items() if k != "sizing"},
        "market_data": market, "agent_findings": scores["agent_findings"] if scores else no_forecasts,
        "independent_review": independent,
        "position_sizing": {"review_contracts": risk["review_contracts"],
                            "details": risk["sizing"]},
        "final_verdict": verdict, "trade_decision": "NO_TRADE", "permitted_live_contracts": 0,
    }


def display(value):
    if value is None:
        return "Unknown"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def markdown(report):
    moment = datetime.fromtimestamp(report["as_of_ms"] / 1000, tz=timezone.utc)
    lines = ["# MNQ/NQ offline research review", "", moment.isoformat(),
             "", f"**{report['final_verdict']} · {report['trade_decision']} · 0 live contracts**"]
    def section(name, values):
        lines.extend(["", "## " + name, ""])
        for key, value in values.items():
            if isinstance(value, dict) and value:
                lines.extend(["", "### " + key.replace("_", " ").capitalize(), ""])
                for field, item in value.items():
                    lines.append(f"- {field.replace('_', ' ')} — {display(item)}")
            else:
                lines.append(f"- {key.replace('_', ' ')} — {display(value)}")
    section("Account status", report["account_status"])
    section("Market data", report["market_data"])
    section("Agent findings", report["agent_findings"])
    section("Independent review", report["independent_review"])
    section("Position sizing", report["position_sizing"])
    section("Final verdict", {"assessment": report["final_verdict"], "decision": report["trade_decision"],
                              "permitted live contracts": report["permitted_live_contracts"]})
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-ms", type=int)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--experiment-id")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()
    try:
        as_of = time.time_ns() // 1_000_000 if args.as_of_ms is None else args.as_of_ms
        report = review(as_of, history=args.history, ledger=args.ledger, snapshot=args.snapshot,
                        registry_path=args.registry, experiment_id=args.experiment_id)
        sys.stdout.write(markdown(report) if args.format == "markdown" else
                         json.dumps(report, allow_nan=False, indent=2) + "\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Cannot produce research review: {exc}\n")


if __name__ == "__main__":
    main()
