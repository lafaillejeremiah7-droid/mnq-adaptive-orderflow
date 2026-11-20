"""Research governance & point-in-time experimental validation.

Employee #1: deterministic, offline, one-contract, one-hypothesis quantitative
research engine. It rejects future-feature timestamps; purges overlapping labels;
compares fixed ridge to a train-only mean baseline; evaluates contiguous
date-held-out folds; reports day-cluster uncertainty, cost assumptions, and a
multiple-test budget. This is a research harness, NOT independent validation.

Usage: python -m company.research_lab --protocol config.json --data events.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE_COLS = ("decision_at_utc", "feature_available_at_utc", "label_end_at_utc",
             "contract", "forward_return_bps")
KEYS = frozenset((
    "id", "researcher", "question", "hypothesis", "falsifier",
    "data_source", "source_sha256", "source_kind", "source_rights",
    "contract", "features", "train_end_utc", "test_start_utc",
    "test_end_utc", "embargo_seconds", "max_label_horizon_seconds",
    "test_folds", "retraining", "min_train_dates", "min_test_dates",
    "min_test_events", "ridge_lambda", "decision_threshold_bps",
    "cost_per_side_bps", "hypotheses_in_family", "seed",
    "max_records", "data_previously_examined",
))
CONTRACT = re.compile(r"(?:NQ|MNQ)[HMUZ]\d{1,4}\Z")
FEATURE = re.compile(r"x_[a-z][a-z0-9_]{0,39}\Z")
SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,69}\Z")


def utc_timestamp(value):
    if not isinstance(value, str) or not value:
        raise ValueError("expected explicit UTC ISO-8601 timestamp")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("malformed UTC timestamp") from error
    if instant.tzinfo is None or instant.utcoffset() is None or instant.utcoffset().total_seconds() != 0:
        raise ValueError("UTC timezone offset required; naive/local timestamps forbidden")
    if not 2000 <= instant.year <= 2099:
        raise ValueError("timestamp year outside supported bounds")
    return instant.astimezone(timezone.utc)


def finite_number(text, key, limit=1e7):
    try:
        number = float(text)
    except (ValueError, TypeError) as error:
        raise ValueError("invalid numeric field: " + key) from error
    if not math.isfinite(number) or abs(number) > limit:
        raise ValueError("nonfinite or implausible numeric field: " + key)
    return number


def check_protocol(p):
    if not isinstance(p, dict) or set(p) != KEYS:
        raise ValueError("protocol has missing or unexpected keys")
    if not isinstance(p["id"], str) or not SLUG.fullmatch(p["id"]):
        raise ValueError("invalid experiment identifier")
    for key in ("researcher", "question", "hypothesis", "falsifier", "data_source"):
        if not isinstance(p[key], str) or not p[key].strip():
            raise ValueError("missing " + key)
    if not isinstance(p["source_sha256"], str) or not re.fullmatch("[a-f0-9]{64}", p["source_sha256"]):
        raise ValueError("invalid source SHA-256")
    if p["source_kind"] not in ("historical", "synthetic"):
        raise ValueError("invalid source kind")
    if p["source_rights"] not in ("verified_documentation", "unverified"):
        raise ValueError("missing documented source-rights status")
    if not isinstance(p["contract"], str) or not CONTRACT.fullmatch(p["contract"]):
        raise ValueError("one explicitly dated CME NQ/MNQ contract is required")
    fs = p["features"]
    if not isinstance(fs, list) or not 1 <= len(fs) <= 6 or any(not isinstance(x, str) or not FEATURE.fullmatch(x) for x in fs) or len(set(fs)) != len(fs):
        raise ValueError("1-6 unique x_* feature names required")
    a, b, c = [utc_timestamp(p[k]) for k in ("train_end_utc", "test_start_utc", "test_end_utc")]
    if not a < b < c:
        raise ValueError("train_end < test_start < test_end required")
    for k, minimum, maximum in (
        ("embargo_seconds", 0, 60*60*24*7),
        ("max_label_horizon_seconds", 1, 60*60*24),
        ("test_folds", 2, 12),
        ("min_train_dates", 3, 100000),
        ("min_test_dates", 4, 100000),
        ("min_test_events", 8, 1000000),
        ("hypotheses_in_family", 1, 100000),
        ("seed", 0, 2**32-1),
        ("max_records", 100, 1000000),
    ):
        if type(p[k]) is not int or not minimum <= p[k] <= maximum:
            raise ValueError("invalid integer configuration " + k)
    for k, minimum, maximum in (
        ("ridge_lambda", 0.001, 100000.0),
        ("decision_threshold_bps", 0.0, 5000.0),
        ("cost_per_side_bps", 0.0, 500.0),
    ):
        if type(p[k]) not in (int, float) or not math.isfinite(p[k]) or not minimum <= p[k] <= maximum:
            raise ValueError("invalid numeric configuration " + k)
    if p["retraining"] not in ("frozen", "expanding"):
        raise ValueError("retraining must be frozen or expanding")
    if type(p["data_previously_examined"]) is not bool:
        raise ValueError("data_previously_examined must be boolean")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def parse_events(raw, protocol):
    """Timestamp semantics must be provided by upstream vendor ETL, never guessed."""
    check_protocol(protocol)
    if sha(raw) != protocol["source_sha256"]:
        raise ValueError("input bytes fail source checksum")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    except UnicodeError as error:
        raise ValueError("dataset must be UTF-8") from error
    cols = list(BASE_COLS) + protocol["features"]
    if reader.fieldnames != cols:
        raise ValueError("CSV columns do not match registered point-in-time data contract")
    rows = []
    previous = None
    for line in reader:
        if len(rows) >= protocol["max_records"]:
            raise ValueError("maximum record budget exceeded; partition inputs")
        if set(line) != set(cols) or any(v is None or v == "" for v in line.values()):
            raise ValueError("malformed row or missing field")
        decision = utc_timestamp(line["decision_at_utc"])
        ready = utc_timestamp(line["feature_available_at_utc"])
        label_end = utc_timestamp(line["label_end_at_utc"])
        if previous is not None and decision <= previous:
            raise ValueError("decision timestamps must be strictly increasing")
        previous = decision
        if ready > decision:
            raise ValueError("feature availability is in the future: lookahead")
        if label_end <= decision:
            raise ValueError("label_end must follow decision")
        if (label_end - decision).total_seconds() > protocol["max_label_horizon_seconds"]:
            raise ValueError("label overlaps unregistered future horizon")
        if line["contract"] != protocol["contract"]:
            raise ValueError("unexpected contract or mixed futures contracts")
        target = finite_number(line["forward_return_bps"], "forward_return_bps", 10000)
        features = [finite_number(line[k], k) for k in protocol["features"]]
        rows.append({
            "decision": decision, "ready": ready, "end": label_end,
            "date": decision.date().isoformat(), "x": features, "y": target,
        })
    if not rows:
        raise ValueError("empty dataset")
    return rows


def solve_linear(matrix, rhs):
    """Small ridge normal equations; pivoting and explicit singularity rejection."""
    n = len(rhs)
    a = [list(map(float, row)) + [float(rhs[i])] for i, row in enumerate(matrix)]
    for pivot in range(n):
        chosen = max(range(pivot, n), key=lambda i: abs(a[i][pivot]))
        a[chosen], a[pivot] = a[pivot], a[chosen]
        if abs(a[pivot][pivot]) < 1e-12:
            raise ValueError("ill-conditioned regression")
        divisor = a[pivot][pivot]
        for col in range(pivot, n+1):
            a[pivot][col] /= divisor
        for other in range(n):
            if other == pivot:
                continue
            scale = a[other][pivot]
            for col in range(pivot, n+1):
                a[other][col] -= scale * a[pivot][col]
    return [row[-1] for row in a]


def fit_ridge(train, ridge_lambda):
    if not train:
        raise ValueError("empty training set")
    nfeat = len(train[0]["x"])
    mean_x = [statistics.mean(r["x"][j] for r in train) for j in range(nfeat)]
    std_x = []
    for j in range(nfeat):
        variance = statistics.mean((r["x"][j] - mean_x[j])**2 for r in train)
        std_x.append(max(math.sqrt(variance), 1e-12))
    y_mean = statistics.mean(r["y"] for r in train)
    xtx = [[0.0]*nfeat for _ in range(nfeat)]
    xty = [0.0]*nfeat
    for row in train:
        x = [(row["x"][j]-mean_x[j])/std_x[j] for j in range(nfeat)]
        y = row["y"] - y_mean
        for j in range(nfeat):
            xty[j] += x[j]*y
            for k in range(nfeat):
                xtx[j][k] += x[j]*x[k]
    for j in range(nfeat):
        xtx[j][j] += ridge_lambda
    coefficients = solve_linear(xtx, xty)
    return {
        "train_mean_target": y_mean, "feature_mean": mean_x,
        "feature_std": std_x, "coefficients": coefficients,
    }


def predict(model, features):
    return model["train_mean_target"] + sum(
        model["coefficients"][j] * (v-model["feature_mean"][j])/model["feature_std"][j]
        for j, v in enumerate(features)
    )


def median_block_bootstrap(values, seed):
    if not values:
        return {"number_of_days": 0, "daily_median": None, "ci95": None}
    rng = random.Random(seed)
    sims = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(2000))
    return {
        "number_of_days": len(values),
        "daily_median": statistics.median(values),
        "ci95": [sims[49], sims[1949]],
    }


def exact_sign_p(values):
    pos = sum(x > 0 for x in values)
    neg = sum(x < 0 for x in values)
    n = pos+neg
    if n == 0:
        return None
    k = min(pos, neg)
    return min(1.0, 2.0 * sum(math.comb(n, i) for i in range(k+1)) / (2**n))


def score_predictions(observations, seed, hypothesis_family):
    if not observations:
        raise ValueError("no holdout predictions")
    days = defaultdict(lambda: {"delta": [], "pairs": []})
    mse_ridge = mse_mean = mae_ridge = 0.0
    for row in observations:
        y, model_pred, baseline = row["y"], row["pred"], row["baseline"]
        error_model = (y-model_pred)**2
        error_mean = (y-baseline)**2
        mse_ridge += error_model
        mse_mean += error_mean
        mae_ridge += abs(y-model_pred)
        days[row["date"]]["delta"].append(error_mean-error_model)
        days[row["date"]]["pairs"].append(row)
    by_day = [statistics.mean(day["delta"]) for _, day in sorted(days.items())]
    p = exact_sign_p(by_day)
    n = len(observations)
    return {
        "events": n, "independent_date_blocks_assumed_for_interval": len(days),
        "model_RMSE_bps": math.sqrt(mse_ridge/n),
        "baseline_train_mean_RMSE_bps": math.sqrt(mse_mean/n),
        "model_MAE_bps": mae_ridge/n,
        "OOS_MSE_improvement_over_baseline_bps2": (mse_mean-mse_ridge)/n,
        "day_block_MSE_improvement": median_block_bootstrap(by_day, seed),
        "day_sign_p_uncorrected": p,
        "bonferroni_p_for_registered_family": min(1.0, p*hypothesis_family) if p is not None else None,
        "sign_test_assumption": "Days are treated as exchangeably independent; serial dependence may invalidate p",
        "significance_does_not_prove_tradeability": True,
    }


def trading_diagnostics(observations, threshold, cost, seed):
    """Purely indicative; requires NONOVERLAPPING labels for a coherent position path.

    A single-unit position acts on each next period's observed return. Buy/sell
    friction is charged for absolute change of position including daily flatten.
    No quote spread, queue, participation or fill model is inferred from OHLCV.
    """
    ordered = sorted(observations, key=lambda r: r["decision"])
    for before, after in zip(ordered, ordered[1:]):
        if before["end"] > after["decision"]:
            return {
                "status": "unavailable_overlapping_labels",
                "reason": "Cannot add returns from positions whose outcome intervals overlap",
                "execution_validated": False,
            }
    dates = defaultdict(list)
    for obs in ordered:
        dates[obs["date"]].append(obs)
    per_day, trades, turnover, gross_total, cost_total = [], 0, 0, 0.0, 0.0
    for _, entries in sorted(dates.items()):
        position = 0
        gross = friction = 0.0
        for event in entries:
            desired = 1 if event["pred"] > threshold else -1 if event["pred"] < -threshold else 0
            change = abs(desired-position)
            friction += change*cost
            turnover += change
            if desired:
                trades += 1
            gross += desired*event["y"]
            position = desired
        friction += abs(position)*cost
        turnover += abs(position)
        gross_total += gross
        cost_total += friction
        per_day.append(gross-friction)
    equity = peak = max_drawdown = 0.0
    for x in per_day:
        equity += x
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak-equity)
    avg = statistics.mean(per_day)
    sd = statistics.stdev(per_day) if len(per_day) > 1 else 0.0
    return {
        "status": "gross_and_cost_sensitivity_only",
        "days": len(per_day), "active_predictions": trades,
        "turnover_one_side_units": turnover,
        "gross_cumulative_bps_on_one_unit": gross_total,
        "charged_friction_bps": cost_total,
        "indicative_net_cumulative_bps": sum(per_day),
        "worst_indicative_drawdown_bps": max_drawdown,
        "indicative_annualized_daily_sharpe": (avg/sd*math.sqrt(252)) if sd > 0 else None,
        "date_block_median_net_bps": median_block_bootstrap(per_day, seed),
        "independent_executability_or_exchange_queues_verified": False,
        "limitations": "Returns are hypothetical, no actual fills, quote spreads, latency, market impact, outages or partial orders.",
    }


def experiment(protocol, raw):
    """Run with immutable source checksum and train-only transform/model selection."""
    rows = parse_events(raw, protocol)
    train_end = utc_timestamp(protocol["train_end_utc"])
    test_start = utc_timestamp(protocol["test_start_utc"])
    test_end = utc_timestamp(protocol["test_end_utc"])
    embargo = protocol["embargo_seconds"]
    eval_rows = [r for r in rows if test_start <= r["decision"] < test_end]
    dates = sorted({r["date"] for r in eval_rows})
    if len(dates) < max(protocol["min_test_dates"], protocol["test_folds"]):
        raise ValueError("insufficient distinct holdout dates")
    if len(eval_rows) < protocol["min_test_events"]:
        raise ValueError("insufficient holdout event count")
    if len(dates) < protocol["test_folds"] * 2:
        raise ValueError("each chronological fold must have at least two holdout dates")
    predictions = []
    folds = []
    for index in range(protocol["test_folds"]):
        lo = len(dates)*index//protocol["test_folds"]
        hi = len(dates)*(index+1)//protocol["test_folds"]
        group = set(dates[lo:hi])
        test = [r for r in eval_rows if r["date"] in group]
        cutoff = test[0]["decision"]
        from datetime import timedelta
        purge_cutoff = cutoff - timedelta(seconds=embargo)
        # In frozen mode, no holdout data ever enters fitting.
        train = [r for r in rows if r["decision"] < train_end and r["end"] <= purge_cutoff] if protocol["retraining"] == "frozen" else [
            r for r in rows if r["decision"] < cutoff and r["end"] <= purge_cutoff
        ]
        if len({r["date"] for r in train}) < protocol["min_train_dates"]:
            raise ValueError("fold has too few usable training dates after label purging")
        if len(test) < 2:
            raise ValueError("fold has too few holdout observations")
        model = fit_ridge(train, protocol["ridge_lambda"])
        mean = model["train_mean_target"]
        for r in test:
            predictions.append({
                "date": r["date"], "decision": r["decision"], "end": r["end"],
                "y": r["y"], "pred": predict(model, r["x"]), "baseline": mean,
            })
        folds.append({
            "index": index, "test_first_date": min(group), "test_last_date": max(group),
            "train_events": len(train), "train_dates": len({r["date"] for r in train}),
            "test_events": len(test), "training_last_label_end_utc": max(r["end"] for r in train).isoformat(),
            "test_first_decision_utc": cutoff.isoformat(),
            "embargo_seconds": embargo,
            "ridge_coefficients_scaled": model["coefficients"],
            "transform_train_only": True,
        })
    summary = score_predictions(predictions, protocol["seed"], protocol["hypotheses_in_family"])
    strategy = trading_diagnostics(predictions, protocol["decision_threshold_bps"],
                                   protocol["cost_per_side_bps"], protocol["seed"]+1)
    return {
        "researcher": protocol["researcher"],
        "experiment_id": protocol["id"],
        "data_kind": protocol["source_kind"],
        "data_sha256": sha(raw), "raw_events": len(rows),
        "hypothesis": protocol["hypothesis"], "falsifier": protocol["falsifier"],
        "model": "training-standardized ridge least squares with fixed lambda",
        "baseline": "train-only mean target",
        "target": "forward basis-point return over source-declared outcome interval",
        "folds": folds,
        "out_of_sample": summary,
        "cost_sensitivity": strategy,
        "point_in_time_guards": {
            "declared_feature_availability_before_decision": True,
            "train_labels_finished_before_purged_test_start": True,
            "train_only_feature_scaling": True,
            "data_completeness_audited_against_exchange": False,
            "precomputed_features_proven_to_have_no_future_information": False,
        },
        "previously_examined_data": protocol["data_previously_examined"],
        "third_party_data_rights": protocol["source_rights"],
        "regime_generalization_verified": False,
        "model_executability_verified": False,
        "independent_review_completed": False,
        "production_ready": False,
        "evidence_status": "research_only_requires_independent_review",
        "model_risks": [
            "CSV timestamp declarations cannot prove feature/label construction has no future information.",
            "Declared data rights and CME source identity are not independently authenticated.",
            "Dates can have serial dependence, clustering and structural changes.",
            "Hypothesis family size is researcher-declared; omitted prior tests invalidate correction.",
            "Walk-forward retraining mode reuses previously evaluated dates for later training by design.",
            "Hypothetical returns and friction assumptions are not fills or proof of attainable Sharpe.",
            "A recorded protocol hash does not prove it was preregistered before seeing outcomes.",
        ],
    }


def run(protocol_path, data_path, out_root):
    registered_bytes = Path(protocol_path).read_bytes()
    protocol = json.loads(registered_bytes)
    result = experiment(protocol, Path(data_path).read_bytes())
    result["protocol_sha256"] = sha(registered_bytes)
    result["engine_sha256"] = sha(Path(__file__).read_bytes())
    folder = Path(out_root)/protocol["id"]
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.mkdir(exist_ok=False)
    (folder/"protocol.json").write_bytes(registered_bytes)
    (folder/"result.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
    summ = result["out_of_sample"]
    note = [
        "# Institutional-style Quant Research: " + protocol["id"], "",
        "**Status: RESEARCH ONLY. No live execution or independent model approval.**", "",
        "Question: " + protocol["question"],
        "Hypothesis: " + protocol["hypothesis"],
        "Falsifier: " + protocol["falsifier"], "",
        "Data SHA-256: " + result["data_sha256"],
        "Protocol SHA-256: " + result["protocol_sha256"],
        "Chronological test folds: " + str(len(result["folds"])),
        "Test observations: " + str(summ["events"]),
        "Model RMSE (bps): " + str(summ["model_RMSE_bps"]),
        "Baseline RMSE (bps): " + str(summ["baseline_train_mean_RMSE_bps"]),
        "OOS MSE improvement (bps squared): " + str(summ["OOS_MSE_improvement_over_baseline_bps2"]),
        "Date-block confidence interval: " + str(summ["day_block_MSE_improvement"]["ci95"]),
        "Registered-family Bonferroni-adjusted sign p: " + str(summ["bonferroni_p_for_registered_family"]),
        "Cost diagnostic status: " + result["cost_sensitivity"]["status"], "",
        "## Unresolved model risks", "",
        *["- " + item for item in result["model_risks"]], "",
        "No claim of profitability or surpassing a professional quant is established.", "",
    ]
    (folder/"research_note.md").write_text("\n".join(note))
    return folder


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("research-runs/institutional"))
    args = p.parse_args()
    try:
        output = run(args.protocol, args.data, args.out)
    except (ValueError, KeyError, OSError, TypeError, csv.Error) as error:
        p.exit(2, "experiment rejected: " + str(error) + "\n")
    print(json.dumps({"research_artifacts": str(output), "status": "research_only"}))


if __name__ == "__main__":
    main()
