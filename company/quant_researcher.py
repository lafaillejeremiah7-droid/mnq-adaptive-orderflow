"""MNQ Quant Researcher, employee #1: reproducible descriptive research."""
import argparse
import csv
import hashlib
import io
import json
import math
import random
import re
import statistics
from collections import defaultdict
from decimal import InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from quantlab import ticks, timestamp

EASTERN = ZoneInfo("America/New_York")
FIELDS = ["timestamp", "contract", "open", "high", "low", "close"]
KEYS = {"id", "question", "hypothesis", "falsifier", "data_source",
        "data_kind", "data_sha256", "contract", "start", "end", "window_a",
        "window_b", "min_dates", "seed"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def clock(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("expected New York local HH:MM")
    h, m = map(int, value.split(":"))
    return h * 60 + m


def window(item):
    if not isinstance(item, dict) or set(item) != {"label", "start", "end"}:
        raise ValueError("each window needs label, start and end")
    if not isinstance(item["label"], str) or not item["label"].strip():
        raise ValueError("missing window label")
    a, b = clock(item["start"]), clock(item["end"])
    if not 1 <= b - a <= 120:
        raise ValueError("window must be 1 to 120 minutes")
    return a, b


def validate(spec):
    if not isinstance(spec, dict) or set(spec) != KEYS:
        raise ValueError("invalid research protocol keys")
    if not isinstance(spec["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", spec["id"]):
        raise ValueError("invalid research id")
    for k in ("question", "hypothesis", "falsifier", "data_source"):
        if not isinstance(spec[k], str) or not spec[k].strip():
            raise ValueError("missing " + k)
    if spec["data_kind"] not in {"synthetic", "historical"}:
        raise ValueError("data_kind must be synthetic or historical")
    if not isinstance(spec["data_sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", spec["data_sha256"]):
        raise ValueError("missing SHA-256")
    if not isinstance(spec["contract"], str) or not re.fullmatch(r"MNQ[HMUZ]\d{1,4}", spec["contract"]):
        raise ValueError("expected one MNQ quarterly contract")
    if timestamp(spec["end"]) <= timestamp(spec["start"]):
        raise ValueError("invalid date interval")
    if type(spec["min_dates"]) is not int or spec["min_dates"] < 3:
        raise ValueError("min_dates must be integer >= 3")
    if type(spec["seed"]) is not int or not 0 <= spec["seed"] < 2**32:
        raise ValueError("invalid random seed")
    a, b = window(spec["window_a"]), window(spec["window_b"])
    if max(a[0], b[0]) < min(a[1], b[1]):
        raise ValueError("comparison windows overlap")


def exact_sign_p(diffs):
    plus, minus = sum(x > 0 for x in diffs), sum(x < 0 for x in diffs)
    n = plus + minus
    if not n:
        return None
    return min(1.0, 2 * sum(math.comb(n, k) for k in range(min(plus, minus) + 1)) / 2**n)


def paired_ci(diffs, seed):
    rng = random.Random(seed)
    medians = sorted(statistics.median(rng.choices(diffs, k=len(diffs))) for _ in range(2000))
    return [medians[50], medians[1949]]


def analyze(spec, raw):
    validate(spec)
    if sha(raw) != spec["data_sha256"]:
        raise ValueError("source data checksum mismatch")
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeError as error:
        raise ValueError("CSV must be UTF-8") from error
    records = csv.DictReader(io.StringIO(decoded, newline=""))
    if records.fieldnames != FIELDS:
        raise ValueError("CSV needs timestamp,contract,open,high,low,close")
    a, b = window(spec["window_a"]), window(spec["window_b"])
    start, end = timestamp(spec["start"]), timestamp(spec["end"])
    dates = defaultdict(lambda: [[], []])
    last = None
    count = 0
    for row in records:
        if set(row) != set(FIELDS) or any(value is None for value in row.values()):
            raise ValueError("malformed CSV row")
        now = timestamp(row["timestamp"])
        if last is not None and now <= last:
            raise ValueError("timestamps must be strictly increasing")
        last = now
        if row["contract"] != spec["contract"]:
            raise ValueError("mixed or incorrect futures contract")
        o, h, l, c = [ticks(row[key]) for key in ("open", "high", "low", "close")]
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError("inconsistent OHLC")
        count += 1
        if not start <= now < end:
            continue
        local = now.astimezone(EASTERN)
        if local.weekday() > 4:
            continue
        minute = local.hour * 60 + local.minute
        day = local.date().isoformat()
        if a[0] <= minute < a[1]:
            dates[day][0].append(h - l)
        if b[0] <= minute < b[1]:
            dates[day][1].append(h - l)
    if count == 0:
        raise ValueError("no CSV observations")
    pairs, excluded = {}, {}
    for day, (first, second) in sorted(dates.items()):
        if len(first) != a[1] - a[0] or len(second) != b[1] - b[0]:
            excluded[day] = {"a_bars": len(first), "b_bars": len(second)}
            continue
        x = sum(first) / (4 * len(first))
        y = sum(second) / (4 * len(second))
        pairs[day] = {"window_a_mean_points": x, "window_b_mean_points": y,
                      "paired_difference_points": x - y}
    diffs = [value["paired_difference_points"] for value in pairs.values()]
    sufficient = len(diffs) >= spec["min_dates"]
    median = statistics.median(diffs) if diffs else None
    return {
        "employee_id": "quant-researcher-001",
        "research_id": spec["id"],
        "contract": spec["contract"],
        "data_kind": spec["data_kind"],
        "data_source": spec["data_source"],
        "data_sha256": sha(raw),
        "unit_of_analysis": "one paired New York trading date",
        "units": "MNQ index points per one-minute bar",
        "n_input_bars": count,
        "n_complete_dates": len(diffs),
        "excluded_dates": excluded,
        "daily_pairs": pairs,
        "window_a_larger": sum(x > 0 for x in diffs),
        "window_b_larger": sum(x < 0 for x in diffs),
        "ties": sum(x == 0 for x in diffs),
        "median_paired_difference_points": median,
        "exploratory_bootstrap_95pct_ci": paired_ci(diffs, spec["seed"]) if sufficient else None,
        "sign_test_p_if_dates_independent": exact_sign_p(diffs) if sufficient else None,
        "status": "descriptive_only" if sufficient else "insufficient_data",
        "hypothesis_supported_in_sample": (median > 0) if sufficient else None,
        "independent_holdout": False,
        "tradable_edge_validated": False,
        "limitations": [
            "OHLC does not show delta, order flow, absorption, liquidity or realistic fills.",
            "Statistical interval is exploratory; sign test assumes independent dates.",
            "Input date range might be previously inspected; the CLI cannot prove preregistration.",
            "Vendor provenance, contract rolls and exchange holidays are not independently verified.",
            "No forecast, execution-cost study or out-of-sample trading edge was evaluated.",
        ],
    }


def run(spec_path, data_path, root):
    protocol = Path(spec_path).read_bytes()
    spec = json.loads(protocol)
    result = analyze(spec, Path(data_path).read_bytes())
    result["protocol_sha256"] = sha(protocol)
    result["engine_sha256"] = sha(Path(__file__).read_bytes())
    output = Path(root) / spec["id"]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    (output / "protocol.json").write_bytes(protocol)
    (output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    report = [
        "# Quant Researcher: " + spec["id"],
        "",
        "Question: " + spec["question"],
        "Hypothesis: " + spec["hypothesis"],
        "Falsifier: " + spec["falsifier"],
        "Status: " + result["status"] + " — not a validated trading edge.",
        "Complete paired dates: " + str(result["n_complete_dates"]),
        "Median A minus B (MNQ points): " + str(result["median_paired_difference_points"]),
        "Exploratory 95% date-bootstrap CI: " + str(result["exploratory_bootstrap_95pct_ci"]),
        "Two-sided sign-test p (if dates independent): " + str(result["sign_test_p_if_dates_independent"]),
        "Input checksum: " + result["data_sha256"],
        "",
        "## Limitations",
        *["- " + item for item in result["limitations"]],
        "",
        "Independent review of data, assumptions and results required.",
    ]
    (output / "research_note.md").write_text("\n".join(report) + "\n")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, default=Path("research-runs"))
    arguments = parser.parse_args()
    try:
        destination = run(arguments.spec, arguments.data, arguments.out_root)
    except (OSError, ValueError, TypeError, KeyError, InvalidOperation, csv.Error) as error:
        parser.exit(2, "research rejected: " + str(error) + "\n")
    print(json.dumps({"employee_id": "quant-researcher-001", "output": str(destination)}))


if __name__ == "__main__":
    main()
