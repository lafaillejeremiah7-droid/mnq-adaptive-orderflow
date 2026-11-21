"""Complete NQ/MNQ profile benchmark including Python/C++ binding overhead.

Measures same in-memory Trade list and exactly identical final profile dictionaries.
Uses synthetic data and optionally the SHA-pinned single-day vendor sample.
"""
import argparse
import json
import os
import platform
import random
import statistics
import time
from pathlib import Path

from company.market_profile import Trade, volume_profile


def synthetic_trades(n=250_000, seed=20261120):
    rng = random.Random(seed)
    ts = 1738593000 * 1_000_000_000
    price = 84000
    trades = []
    for i in range(n):
        price = max(1, price + rng.choice((-2, -1, 0, 0, 1, 2)))
        trades.append(Trade(ts + i * 50_000_000, "NQH5", price,
                            rng.randint(1, 12), rng.choice(("B", "A", "N")), i))
    return trades


def compare(trades, rounds, seed):
    expected = volume_profile(trades, .70, backend="python")
    samples = {"python": [], "cpp": []}
    rng = random.Random(seed)
    for round_id in range(rounds + 1):
        labels = list(samples)
        rng.shuffle(labels)
        for engine in labels:
            start = time.perf_counter()
            actual = volume_profile(trades, .70, backend=engine)
            seconds = time.perf_counter() - start
            if actual != expected:
                raise AssertionError("native profile disagrees with Python reference: " + engine)
            if round_id:
                samples[engine].append(seconds)
    p = statistics.median(samples["python"])
    c = statistics.median(samples["cpp"])
    return {
        "records": len(trades),
        "full_profile_identical": True,
        "python_median_seconds": p, "cpp_median_seconds": c,
        "cpp_speedup": p/c,
        "timing_seconds": samples,
        "profile_research_summary": {
            "poc_ticks": expected["poc_ticks"],
            "vah_ticks": expected["vah_ticks"],
            "val_ticks": expected["val_ticks"],
            "unique_prices": len(expected["volume_at_price"]),
            "trade_delta_known": expected["known_trade_delta"],
        },
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vendor", action="store_true")
    p.add_argument("--rounds", type=int, default=5)
    p.add_argument("--out", type=Path, default=Path("studies/cpp-profile-acceleration"))
    args = p.parse_args()
    if not 3 <= args.rounds <= 12:
        p.error("rounds must be in 3..12")
    samples = {"synthetic_250k": compare(synthetic_trades(), args.rounds, 20261120)}
    if args.vendor:
        from scripts.real_nq_vendor_sample import load_vendor_file, parse
        historical, provenance = parse(load_vendor_file())
        samples["historical_vendor_rth"] = {
            **compare(historical, args.rounds, 20261121),
            "vendor_reported_rth_rows": provenance["rth_tick_records"],
            "vendor_cme_provenance_independently_verified": False,
            "vendor_date": "2026-11-09",
        }
    result = {
        "scope": "Complete company.market_profile.volume_profile outputs with C++ counters",
        "machine": {
            "python": platform.python_version(),
            "architecture": platform.machine(),
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
        },
        "rounds": args.rounds,
        "samples": samples,
        "research_only": True,
        "execution_performance_validated": False,
        "notes": [
            "Single GitHub runner, no CPU pinning, benchmark intervals or hardware replication.",
            "Both implementations share Python's value area, node and delta formatting logic.",
            "Timings exclude loading vendor ZIP/Parquet, source integrity verification and input Trade preparation.",
            "C++ import and Python binding overhead are included in every C++ call.",
            "Historical vendor sample is one day; exchange authenticity not independently established.",
            "No claim about NQ market direction, profitability, or overall model improvement.",
        ],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/"summary.json").write_text(
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False)+"\n")
    lines = [
        "# Integrated C++ NQ/MNQ profile acceleration", "",
        "Complete Python and C++-accelerated profile outputs matched exactly.", "",
        "| Dataset | Trades | Python median | C++ median | Speedup |",
        "|---|---:|---:|---:|---:|",
    ]
    for label,info in samples.items():
        lines.append("| {} | {:,} | {:.4f}s | {:.4f}s | {:.2f}× |".format(
            label, info["records"], info["python_median_seconds"],
            info["cpp_median_seconds"], info["cpp_speedup"]))
    lines += ["", "## Caveats", ""]
    lines.extend("- "+note for note in result["notes"])
    lines += ["", "Benchmarks demonstrate performance, not a valid tradable edge.", ""]
    (args.out/"report.md").write_text("\n".join(lines))
    print(json.dumps({name: {"records": x["records"], "speedup": x["cpp_speedup"]}
                      for name,x in samples.items()}))


if __name__ == "__main__":
    main()
