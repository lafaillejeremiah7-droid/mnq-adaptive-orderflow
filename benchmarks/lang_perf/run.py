"""Reproducible benchmark of Python, Rust and C++ on NQ trade aggregation.

Runs two comparisons: deterministic synthetic 250k trades and SHA-pinned,
vendor-reported NQZ6 RTH print sample (488k records). No raw data committed.
This is a *narrow hot-path* benchmark, not a complete research pipeline trial.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from benchmarks.lang_perf.reference import HEADER, aggregate

ROOT = Path(__file__).resolve().parent


def synthetic(path: Path, n=250_000):
    """Produce reproducible, exchange-tick-aligned, deliberately synthetic rows."""
    with path.open("w", encoding="ascii", newline="") as f:
        f.write(HEADER + "\n")
        for i in range(n):
            ts = 1760000000000000000 + i * 50_000_000
            price = 108000 + ((((i*7919) ^ (i >> 3)) % 1201) - 600)
            qty = 1 + (i*17) % 11
            side = ("A", "B", "N")[i % 3]
            f.write(f"{ts},{price},{qty},{side},{i}\n")


def vendor_sample(path: Path):
    # The existing vendor importer checks both the ZIP and inner Parquet SHA256.
    # Reformat *in memory / private CI disk* to a comparable input, not Git.
    from scripts.real_nq_vendor_sample import load_vendor_file, parse
    raw = load_vendor_file()
    trades, coverage = parse(raw)
    with path.open("w", encoding="ascii", newline="") as f:
        f.write(HEADER + "\n")
        for t in trades:
            f.write(f"{t.timestamp_ns},{t.price_ticks},{t.size},{t.side},{t.sequence}\n")
    return {
        "vendor_sample": "NQZ6 2026-11-09, RTH, vendor-reported ticks",
        "vendor_origin_independently_verified_CME": False,
        "vendor_rth_trade_records": coverage["rth_tick_records"],
        "vendor_parquet_sha256": "89a50dc88c4beacafd95b8cc4e2f7ee9000af498549dcb0910aa08feed82dba0",
    }


def execute(command):
    before = time.perf_counter()
    run = subprocess.run(command, text=True, capture_output=True,
                         timeout=120)
    if run.returncode:
        raise RuntimeError(f"Benchmark command {command[0]} failed: {run.stderr.strip()[:2500]}")
    return time.perf_counter()-before, json.loads(run.stdout)


def measure(path: Path, commands: dict, rounds: int, seed: int):
    expected = aggregate(path)
    samples = {name: [] for name in commands}
    rng = random.Random(seed)
    for rep in range(rounds+1):
        names = list(commands)
        rng.shuffle(names)
        for name in names:
            timing, result = execute([*commands[name], str(path)])
            if result != expected:
                raise AssertionError(f"{name} disagrees with Python reference: {result}")
            if rep > 0:
                samples[name].append(timing)
    stats = {
        name: {
            "median_seconds": statistics.median(values),
            "min_seconds": min(values),
            "max_seconds": max(values),
            "repeated_runs": rounds,
        } for name, values in samples.items()
    }
    python_seconds = stats["python"]["median_seconds"]
    for value in stats.values():
        value["speedup_vs_python"] = python_seconds/value["median_seconds"]
    return {
        "rows": expected["rows"],
        "correctness": "all exact integer-valued summaries match on every run",
        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "expected_summary": expected,
        "results": stats,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--polars", action="store_true", help="also test Python with Rust-backed Polars")
    parser.add_argument("--vendor", action="store_true",
                        help="benchmark the SHA-pinned one-day vendor sample too")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("studies/language-benchmark"))
    args = parser.parse_args()
    if not 3 <= args.rounds <= 15:
        parser.error("rounds must be from 3 to 15")
    with tempfile.TemporaryDirectory(prefix="nq-lang-") as temp:
        root = Path(temp)
        cpp = root/"cpp_kernel"
        rust = root/"rust_kernel"
        subprocess.run(["g++", "-std=c++20", "-O3", "-DNDEBUG",
                        str(ROOT/"native.cpp"), "-o", str(cpp)], check=True)
        subprocess.run(["rustc", "--edition=2021", "-O", "-C",
                        "target-cpu=x86-64", str(ROOT/"native.rs"), "-o", str(rust)],
                       check=True)
        commands = {
            "python": [sys.executable, str(ROOT/"reference.py")],
            "rust": [str(rust)],
            "cpp": [str(cpp)],
        }
        if args.polars:
            commands["polars"] = [sys.executable, "-m", "benchmarks.lang_perf.polars_baseline"]
        fake = root/"synthetic.csv"
        synthetic(fake)
        results = {"synthetic_250k": measure(fake, commands, args.rounds, 20261120)}
        if args.vendor:
            real = root/"vendor.csv"
            provenance = vendor_sample(real)
            results["historical_vendor"] = {
                **measure(real, commands, args.rounds, 20261121), **provenance
            }
        versions = {}
        for tool, command in (
            ("rust", ["rustc", "--version"]),
            ("cpp", ["g++", "--version"]),
        ):
            versions[tool] = subprocess.check_output(command, text=True).splitlines()[0]
    result = {
        "scope": "CSV integer-tick price/size/side aggregation plus POC and 70% value-area only",
        "benchmark_type": "new process including CSV parse and I/O, excluding compile time",
        "polars_available": args.polars,
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "logical_cpus": os.cpu_count(),
            "python": platform.python_version(),
            **versions,
        },
        "datasets": results,
        "limits": [
            "Single shared GitHub runner; no CPU pinning, multiple hosts or capacity testing.",
            "Pure Python uses interpreted loops; Polars comparison is opt-in and uses a Rust-backed DataFrame query.",
            "NumPy and Numba have not been benchmarked; Polars startup/CSV conversion overhead is included.",
            "This compares a narrow profile hot path, NOT the full Python research engine.",
            "Only one vendor-reported trading day is used; exchange origin not authenticated.",
            "Compilers are excluded from elapsed time; no integrated Python-Rust FFI cost.",
            "Side N in vendor data is unknown aggressor, not observed delta.",
            "No model-training, data licensing, execution or profitable edge evaluated.",
        ],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/"summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    lines = [
        "# NQ/MNQ aggregation benchmark: Python, Rust and C++", "",
        "One narrow, deterministic task. **All integer outputs match exactly**.",
        "Timing: five measured subprocess runs per language after one untimed warm-up.",
        "Order randomized within rounds; CSV disk I/O included, compile time excluded.", "",
        "| Dataset | Trades | Pure Python | Python+Polars | Rust | C++ | Polars speedup | Rust speedup | C++ speedup |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, sample in results.items():
        times = sample["results"]
        polars_median = "{:.4f}s".format(times["polars"]["median_seconds"]) if "polars" in times else "not tested"
        polars_speedup = "{:.2f}×".format(times["polars"]["speedup_vs_python"]) if "polars" in times else "n/a"
        lines.append(
            "| {} | {:,} | {:.4f}s | {} | {:.4f}s | {:.4f}s | {} | {:.2f}× | {:.2f}× |".format(
                name, sample["rows"], times["python"]["median_seconds"], polars_median,
                times["rust"]["median_seconds"], times["cpp"]["median_seconds"],
                polars_speedup, times["rust"]["speedup_vs_python"], times["cpp"]["speedup_vs_python"]
            )
        )
    lines += ["", "## Interpretation", "",
              "Pure Python remains the orchestration and statistical research language.",
              "Native Rust/C++ should be used only for measured, independently validated bottlenecks; compare with optimized NumPy/Polars/Numba before embedding.",
              "A benchmark speedup does not demonstrate higher forecast accuracy, statistical validity or trading profitability.",
              "", "## Limitations", ""]
    lines.extend("- " + limit for limit in result["limits"])
    lines += ["", "Raw vendor records are never committed; only aggregate summaries and hashes appear here.", ""]
    (args.out/"report.md").write_text("\n".join(lines))
    print(json.dumps({key: {
        "rows": value["rows"],
        "python_seconds": value["results"]["python"]["median_seconds"],
        "rust_speedup": value["results"]["rust"]["speedup_vs_python"],
        "cpp_speedup": value["results"]["cpp"]["speedup_vs_python"],
    } for key,value in results.items()}))


if __name__ == "__main__":
    main()
