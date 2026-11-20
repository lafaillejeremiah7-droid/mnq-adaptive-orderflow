"""Adversarial model-review gate. Never self-certifies production readiness.

Reads immutable research artifacts and independently checks the evaluation
contract, claims, uncertainty and limitations. The result is a machine audit
and reviewer checklist, not a substitute for an unaffiliated human validator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from company.research_lab import check_protocol


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def audit(protocol_bytes: bytes, result: dict) -> dict:
    """Refuse tampered artifacts, then list substantive scientific blockers."""
    protocol = json.loads(protocol_bytes)
    check_protocol(protocol)
    if not isinstance(result, dict):
        raise ValueError("result must be an object")
    if result.get("protocol_sha256") != fingerprint(protocol_bytes):
        raise ValueError("protocol artifact fails recorded checksum")
    if result.get("experiment_id") != protocol["id"]:
        raise ValueError("experiment identity mismatch")
    if result.get("data_sha256") != protocol["source_sha256"]:
        raise ValueError("data input SHA does not match registered protocol")
    if result.get("researcher") != protocol["researcher"]:
        raise ValueError("researcher identity mismatch")
    if result.get("data_kind") != protocol["source_kind"]:
        raise ValueError("source kind mismatch")
    points = result.get("out_of_sample")
    if not isinstance(points, dict):
        raise ValueError("out-of-sample results missing")
    for key in ("model_RMSE_bps", "baseline_train_mean_RMSE_bps",
                "OOS_MSE_improvement_over_baseline_bps2"):
        if type(points.get(key)) not in (int, float) or not math.isfinite(points[key]):
            raise ValueError("invalid holdout score: " + key)
    dates = points.get("independent_date_blocks_assumed_for_interval")
    if type(dates) is not int or dates < 1:
        raise ValueError("invalid holdout date count")
    if not isinstance(result.get("folds"), list) or not result["folds"]:
        raise ValueError("missing chronological fold evidence")
    if len(result["folds"]) != protocol["test_folds"]:
        raise ValueError("unexpected number of folds")
    for fold in result["folds"]:
        if not isinstance(fold, dict) or fold.get("transform_train_only") is not True:
            raise ValueError("fold has no training-only transform evidence")
        if fold.get("embargo_seconds") != protocol["embargo_seconds"]:
            raise ValueError("reported embargo differs from protocol")
        if not isinstance(fold.get("train_events"), int) or fold["train_events"] < 1:
            raise ValueError("invalid fold training size")
    flags = result.get("point_in_time_guards", {})
    if not isinstance(flags, dict) or flags.get("train_labels_finished_before_purged_test_start") is not True:
        raise ValueError("label purge evidence missing")
    blockers = []
    warnings = []
    def block(code, reason):
        blockers.append({"code": code, "reason": reason})
    def warn(code, reason):
        warnings.append({"code": code, "reason": reason})
    if protocol["source_kind"] != "historical":
        block("SYNTHETIC_ONLY", "Unit-test or simulated rows cannot validate a real market effect")
    if protocol["source_rights"] != "verified_documentation":
        block("DATA_RIGHTS_UNVERIFIED", "Publisher and exchange entitlements not documented")
    if protocol["data_previously_examined"]:
        block("HOLDOUT_ALREADY_SEEN", "This sample has already been examined for hypotheses")
    if not flags.get("precomputed_features_proven_to_have_no_future_information"):
        block("RAW_FEATURE_LINEAGE_UNVERIFIED", "CSV timestamps do not certify upstream point-in-time computation")
    if not flags.get("data_completeness_audited_against_exchange"):
        block("EXCHANGE_COMPLETENESS_UNVERIFIED", "No verified exchange source reconciliation or roll quality audit")
    if points["OOS_MSE_improvement_over_baseline_bps2"] <= 0:
        block("NO_BASELINE_IMPROVEMENT", "Model does not beat train-only mean on preregistered test loss")
    if dates < 60:
        block("INSUFFICIENT_INDEPENDENT_DATES", "Fewer than 60 date blocks; minimum screening threshold")
    ci = points.get("day_block_MSE_improvement", {}).get("ci95")
    if not isinstance(ci, list) or len(ci) != 2 or any(type(x) not in (int,float) or not math.isfinite(x) for x in ci):
        raise ValueError("invalid daily uncertainty interval")
    if ci[0] <= 0:
        block("UNCERTAIN_EFFECT", "Date-bootstrap lower bound does not exclude no improvement")
    p_adj = points.get("bonferroni_p_for_registered_family")
    if p_adj is None or type(p_adj) not in (int, float) or not math.isfinite(p_adj) or p_adj > 0.05:
        block("UNCONVINCING_MULTITEST_EVIDENCE", "Registered-family sign-test criterion not met")
    if protocol["retraining"] == "expanding":
        warn("SEQUENTIAL_RETRAINING", "Later fold training incorporates earlier evaluation dates; describe as sequential walk-forward")
    strategy = result.get("cost_sensitivity")
    if not isinstance(strategy, dict):
        raise ValueError("missing execution diagnostic")
    if strategy.get("status") == "unavailable_overlapping_labels":
        block("OVERLAPPING_OUTCOMES", "Returns over overlapping observation periods cannot be summed")
    elif strategy.get("status") != "gross_and_cost_sensitivity_only":
        block("EXECUTION_COST_UNKNOWN", "No cost-aware diagnostic even at the sensitivity level")
    elif strategy.get("indicative_net_cumulative_bps", -math.inf) <= 0:
        block("NO_POSITIVE_INDICATIVE_NET", "Hypothetical net result is non-positive under declared friction")
    if not result.get("model_executability_verified"):
        block("NO_EXECUTION_VALIDATION", "No realistic spreads, order queue, partial fills, latency and slippage")
    if not result.get("regime_generalization_verified"):
        block("NO_EXTERNAL_REGIME_REPLICATION", "Insufficient independent cross-regime replication")
    if not result.get("independent_review_completed"):
        block("NO_INDEPENDENT_VALIDATOR", "A researcher cannot independently approve its own work")
    if points.get("sign_test_assumption"):
        warn("SERIAL_DATE_DEPENDENCE", "Daily sign-test p-value assumes exchangeable independent dates")
    return {
        "experiment_id": protocol["id"],
        "review_type": "automated_adversarial_screen_not_human_review",
        "protocol_sha256": fingerprint(protocol_bytes),
        "engine_sha256_from_result": result.get("engine_sha256"),
        "blockers": blockers, "warnings": warnings,
        "screen_passed": len(blockers) == 0,
        "independent_human_validation_completed": False,
        "authorization_to_trade": False,
        "production_ready": False,
        "independent_review_required": True,
        "next_steps": [
            "An unrelated reviewer checks feature creation, exchange timestamps, contract rolls and source rights.",
            "A separate validator reproduces results from exact source and protocol hashes.",
            "Repeat on new market regimes and a genuinely untouched prospective period.",
            "Add realistic quotes, execution engine, fees, slippage, latency, and transaction costs.",
            "Admit negative or inconclusive findings; do not tune the same holdout.",
        ],
    }


def run(study_folder, output=None):
    folder = Path(study_folder)
    bytes_ = (folder/"protocol.json").read_bytes()
    result = json.loads((folder/"result.json").read_text())
    review = audit(bytes_, result)
    target = Path(output) if output is not None else folder/"adversarial_review.json"
    with target.open("x") as writer:
        json.dump(review, writer, indent=2, sort_keys=True)
        writer.write("\n")
    return review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = run(args.study, args.output)
    except (ValueError, OSError, TypeError, KeyError, json.JSONDecodeError) as err:
        parser.exit(2, "review failed: " + str(err) + "\n")
    print(json.dumps({
        "screen_passed": report["screen_passed"],
        "production_ready": report["production_ready"],
        "blockers": [x["code"] for x in report["blockers"]],
    }))


if __name__ == "__main__":
    main()
