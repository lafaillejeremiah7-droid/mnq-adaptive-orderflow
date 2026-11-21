"""Independent-formula numeric cross-check of recorded research predictions.

Checks predictions against source labels and recomputes loss using a separate
Decimal implementation. This is NOT independent model fitting, validation of
upstream features, an unseen holdout, human effective challenge or trade approval.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIELDS = {"decision_at_utc", "label_end_at_utc", "date", "actual_bps",
          "model_prediction_bps", "baseline_prediction_bps"}


def _utc(value):
    if not isinstance(value, str):
        raise ValueError("numeric audit timestamps must be text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("numeric audit timestamp malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("numeric audit requires UTC timestamps")
    return parsed


def _decimal(value):
    if type(value) is not float and type(value) is not int and type(value) is not str:
        raise ValueError("numeric audit requires finite numbers")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("numeric audit has invalid value") from exc
    if not number.is_finite():
        raise ValueError("numeric audit has nonfinite value")
    return number


def audit(protocol, result, source):
    if not isinstance(protocol, dict) or not isinstance(result, dict):
        raise ValueError("protocol and result must be objects")
    if not isinstance(source, bytes) or hashlib.sha256(source).hexdigest() != protocol.get("source_sha256"):
        raise ValueError("raw input checksum mismatch")
    if result.get("data_sha256") != protocol["source_sha256"]:
        raise ValueError("research result input checksum mismatch")
    events = result.get("evaluation_events")
    if not isinstance(events, list) or not events:
        raise ValueError("no persisted evaluation predictions to validate")
    if len(events) != result.get("out_of_sample", {}).get("events"):
        raise ValueError("reported evaluation event count mismatch")
    source_rows = csv.DictReader(io.StringIO(source.decode("utf-8-sig"), newline=""))
    if source_rows.fieldnames is None or not set(("decision_at_utc", "contract", "forward_return_bps", "label_end_at_utc")).issubset(source_rows.fieldnames):
        raise ValueError("missing independent source reference fields")
    targets = {}
    for line in source_rows:
        if line["contract"] != protocol.get("contract"):
            raise ValueError("source contract mismatch")
        at = _utc(line["decision_at_utc"])
        if at in targets:
            raise ValueError("source decisions are not unique")
        targets[at] = (_utc(line["label_end_at_utc"]), _decimal(line["forward_return_bps"]))
    start, stop = _utc(protocol["test_start_utc"]), _utc(protocol["test_end_utc"])
    fold_dates = result.get("folds")
    if not isinstance(fold_dates, list) or len(fold_dates) != protocol.get("test_folds"):
        raise ValueError("fold summary mismatch")
    previous = None
    count_by_date = defaultdict(list)
    squared_model = Decimal(0)
    squared_baseline = Decimal(0)
    abs_model = Decimal(0)
    for event in events:
        if not isinstance(event, dict) or set(event) != FIELDS:
            raise ValueError("invalid evaluation event schema")
        decision, end = _utc(event["decision_at_utc"]), _utc(event["label_end_at_utc"])
        if not start <= decision < stop or not decision < end <= stop:
            raise ValueError("evaluation event violates registered test time")
        if previous is not None and decision <= previous:
            raise ValueError("predictions must have unique chronological decisions")
        previous = decision
        if event["date"] != decision.date().isoformat():
            raise ValueError("evaluation date mismatch")
        if decision not in targets or targets[decision][0] != end:
            raise ValueError("prediction missing source label or end timestamp")
        y, pred, baseline = (
            _decimal(event["actual_bps"]),
            _decimal(event["model_prediction_bps"]),
            _decimal(event["baseline_prediction_bps"]),
        )
        if abs(y - targets[decision][1]) > Decimal("1e-8"):
            raise ValueError("persisted evaluation target differs from raw source")
        error_m = (y - pred) ** 2
        error_b = (y - baseline) ** 2
        squared_model += error_m
        squared_baseline += error_b
        abs_model += abs(y - pred)
        count_by_date[event["date"]].append(error_b - error_m)
    date_list = sorted(count_by_date)
    if len(date_list) < protocol["min_test_dates"]:
        raise ValueError("insufficient evaluation dates in prediction artifact")
    fold_counts = [0] * len(fold_dates)
    for day, values in count_by_date.items():
        matched = [i for i, fold in enumerate(fold_dates)
                   if fold["test_first_date"] <= day <= fold["test_last_date"]]
        if len(matched) != 1:
            raise ValueError("evaluation day belongs to zero/multiple folds")
        fold_counts[matched[0]] += len(values)
    if fold_counts != [fold["test_events"] for fold in fold_dates]:
        raise ValueError("fold event counts disagree with persisted predictions")
    count = Decimal(len(events))
    mse_m = squared_model / count
    mse_b = squared_baseline / count
    mae_m = abs_model / count
    improvement = mse_b - mse_m
    reported = result["out_of_sample"]
    comparisons = {
        "model_RMSE_bps": float(mse_m.sqrt()),
        "baseline_train_mean_RMSE_bps": float(mse_b.sqrt()),
        "model_MAE_bps": float(mae_m),
        "OOS_MSE_improvement_over_baseline_bps2": float(improvement),
    }
    for key, expected in comparisons.items():
        observed = reported.get(key)
        if type(observed) not in (float, int) or not math.isfinite(observed):
            raise ValueError("reported numeric statistic invalid: " + key)
        if not math.isclose(observed, expected, rel_tol=1e-10, abs_tol=1e-8):
            raise ValueError("reported numeric statistic does not match independent recomputation: " + key)
    pos = sum(sum(values) > 0 for values in count_by_date.values())
    neg = sum(sum(values) < 0 for values in count_by_date.values())
    n = pos + neg
    if n:
        k = min(pos, neg)
        # Exact two-sided binomial tail, independent of research_lab implementation.
        import math as _math
        p = min(1., sum(_math.comb(n, j) for j in range(k + 1)) / (2 ** (n - 1)))
        adjusted = min(1., p * protocol["hypotheses_in_family"])
    else:
        p = adjusted = None
    saved = reported.get("day_sign_p_uncorrected")
    saved_adjusted = reported.get("bonferroni_p_for_registered_family")
    if (saved is None) != (p is None) or (saved_adjusted is None) != (adjusted is None):
        raise ValueError("sign test missing or inconsistent")
    if p is not None and (not math.isclose(saved, p, abs_tol=1e-12)
                          or not math.isclose(saved_adjusted, adjusted, abs_tol=1e-12)):
        raise ValueError("independent date sign-test check failed")
    return {
        "status": "internal_independent_formula_crosscheck",
        "observations": len(events),
        "dates": len(date_list),
        "fold_events": fold_counts,
        "recomputed_statistics": comparisons,
        "recomputed_uncorrected_day_sign_p": p,
        "recomputed_registered_family_adjusted_p": adjusted,
        "raw_label_reconciliation": True,
        "independent_formula_reconciliation": True,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "independent_human_validation": False,
        "independent_upstream_feature_verification": False,
        "independent_exchange_authentication": False,
        "production_ready": False,
        "limitations": [
            "Prediction values come from the original research engine; model fitting has not been independently reimplemented.",
            "Time-series day dependence can invalidate a binomial sign test.",
            "Declared hypothesis-family size can omit prior abandoned searches.",
            "This does not prove original feature timestamps or vendor data correctness.",
        ],
    }


def verify_files(study, source):
    folder = Path(study)
    protocol = json.loads((folder / "protocol.json").read_text())
    result = json.loads((folder / "result.json").read_text())
    return audit(protocol, result, Path(source).read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        response = verify_files(args.study, args.source)
        if args.output:
            with args.output.open("x") as destination:
                json.dump(response, destination, indent=2, sort_keys=True)
                destination.write("\n")
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        parser.exit(2, "numeric validation rejected: " + str(exc) + "\n")
    print(json.dumps({"status": response["status"],
                      "observations": response["observations"],
                      "production_ready": False}))


if __name__ == "__main__":
    main()
