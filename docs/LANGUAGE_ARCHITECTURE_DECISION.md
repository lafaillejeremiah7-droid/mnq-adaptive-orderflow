# Quant Researcher: Python, Rust, C++, and Polars technology decision

**Date:** 2026-11-20  
**Updated decision:** **Retain Python for the scientist, use Polars for appropriate tabular ETL, and use opt-in C++ for the measured historical trade-aggregation hotspot.** Rust remains a tested comparator, not a required runtime. Do not rewrite the entire researcher.

## Measurements

Source: [reproducible benchmark summary](../studies/language-benchmark/summary.json) and [human-readable report](../studies/language-benchmark/report.md).

Two separate datasets were tested:
1. 250,000 deterministically generated **synthetic** trade rows across prices, sizes, aggressor-side labels, and timestamp-minutes.
2. 488,749 **vendor-reported historical NQZ6 trades** from November 9, 2026, RTH; original ZIP and Parquet checksums verified by the existing importer. Exchange provenance NOT independently authenticated, one trading date only.

On one GitHub-hosted x86_64 runner (CPython 3.11.18, g++ 15.2, rustc 1.100), five measured process executions per dataset after warm-up produced these medians:

| Implementation | Synthetic 250k | Vendor-reported 488,749 |
|---|---:|---:|
| Python loops | 0.260 s | 0.464 s |
| Python + Polars (Rust-backed) | 0.125 s | 0.149 s |
| Rust stdlib native CLI | 0.042 s | 0.079 s |
| C++20 native CLI | 0.027 s | 0.048 s |

All four implementations returned **exactly identical integer-valued outputs on every trial**, including rows, volume, buy/sell/unknown totals, weighted price, POC, VAH, VAL and a minute-delta checksum. The task is parse a canonical five-column integer-tick CSV and calculate the 70% contiguous value area; it is much narrower than the full company.market_profile implementation.

No vendor raw data is included in the repository. Only source-hash, correctness, timing, hardware/compiler, and aggregate statistics are committed.

### What the measurements do and do not establish

- C++ was fastest in this single sequential CSV workload. Compared with Rust, the historical input saved about **31 milliseconds** (0.079s vs 0.048s) per invocation. This alone is insufficient justification for introducing C++ memory-safety/maintenance risks into the whole research system.
- Rust ran about **5.9 times faster than the pure-Python loop** on the historical sample. This is evidence for a native hot-path opportunity, not proof that replacing Python as a language improves research quality.
- Polars ran about **3.1 times faster than the pure-Python loop** in the historical sample without requiring a custom native binary. Python startup and Polars import/CSV parsing are included in every result.
- Comparisons do not include NumPy, Numba, database engines, streaming Arrow/Parquet readers, Python-Rust FFI overhead, compilation time, machine-learning training, statistical estimation, execution queue simulation, data cleaning, or actual research productivity.
- Workload and hardware variation, compiler versions, parallelism and memory must be measured before a production-level claim. The run uses one GitHub-hosted VM, randomized invocation order and five timed trials, not multiple production machines.
- Native binaries only implement the benchmark's narrow summary, **not** all of volume_profile: no full volume-at-price dictionary, minute-by-minute tape, HVN/LVN, first passage, book data or roll logic. They are not approved as drop-in replacements.

## Approved architecture

- **Python**: hypotheses, statistical models, NumPy/SciPy/scikit-learn/PyTorch where applicable, validation, notebooks, experiment orchestration, risk research and reports.
- **Polars through Python**: first-choice opt-in for validated multi-file and tabular ETL; it uses an underlying Rust execution engine. Profile quality, exact semantic match and source provenance must still be verified.
- **C++20, selectively implemented**: The optional company._nq_cpp extension accelerates trade-volume counters inside company.market_profile. The POC, value area, nodes, delta formatting and reactions remain governed by shared Python code. See docs/CPP_ACCELERATION.md for build instructions and complete output parity evidence.
- **Rust**: Keep the measured standalone CLI benchmark available for future comparisons, without adding a mandatory Rust runtime to the research pipeline.
- **SQL/Parquet**: storage/query formats, not substitutes for the reasoning language; not evaluated in this benchmark.

**Native substitution remains opt-in.** The actual research code supports --profile-backend cpp, while --profile-backend auto selects native aggregation only for 20,000+ trades when compiled; Python remains default. No live trading or execution code has been enabled.

## Reproduction

With Python 3.11, a working C++20 compiler, rustc, access to the vendor sample, and optional packages:

    python -m pip install pyarrow==20.0.0 polars==1.34.0
    python -m unittest tests.test_language_benchmark -v
    python -m benchmarks.lang_perf.run --vendor --polars --rounds 5

Read the raw-comparison output in studies/language-benchmark/summary.json and report.md. The GitHub workflow at .github/workflows/language-benchmark.yml runs this test and publishes **aggregate findings only**. Never redistribute restricted raw historical data.

## Remaining scientific priority

Authentic, licensed multi-year NQ/MNQ tick data and point-in-time feature lineage matter more than any language speedup. A faster test engine processing invalid, incomplete or leaking source data only produces wrong conclusions faster.

## Reference implementation docs

- Rust-backed Polars: https://docs.pola.rs/
- Python/Rust bindings: https://pyo3.rs/
- High-performance NumPy in Python: https://numpy.org/doc/stable/user/basics.performant_code.html

## New integrated C++ full-profile benchmark

The standalone CSV numbers above do not reflect the full Python research path. The separately measured full-profile Python/C++ implementation provides roughly 2.0–2.35x historical vendor-sample speedups within its two GitHub-hosted runs. See [C++ integration and measured caveats](CPP_ACCELERATION.md). The sample is one day and does not validate an alpha signal.
