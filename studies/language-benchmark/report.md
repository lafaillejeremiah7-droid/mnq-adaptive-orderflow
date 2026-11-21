# NQ/MNQ aggregation benchmark: Python, Rust and C++

One narrow, deterministic task. **All integer outputs match exactly**.
Timing: five measured subprocess runs per language after one untimed warm-up.
Order randomized within rounds; CSV disk I/O included, compile time excluded.

| Dataset | Trades | Pure Python | Python+Polars | Rust | C++ | Polars speedup | Rust speedup | C++ speedup |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| synthetic_250k | 250,000 | 0.2416s | 0.1149s | 0.0345s | 0.0230s | 2.10× | 7.00× | 10.50× |
| historical_vendor | 488,749 | 0.4253s | 0.1339s | 0.0642s | 0.0380s | 3.18× | 6.63× | 11.20× |

## Interpretation

Pure Python remains the orchestration and statistical research language.
Native Rust/C++ should be used only for measured, independently validated bottlenecks; compare with optimized NumPy/Polars/Numba before embedding.
A benchmark speedup does not demonstrate higher forecast accuracy, statistical validity or trading profitability.

## Limitations

- Single shared GitHub runner; no CPU pinning, multiple hosts or capacity testing.
- Pure Python uses interpreted loops; Polars comparison is opt-in and uses a Rust-backed DataFrame query.
- NumPy and Numba have not been benchmarked; Polars startup/CSV conversion overhead is included.
- This compares a narrow profile hot path, NOT the full Python research engine.
- Only one vendor-reported trading day is used; exchange origin not authenticated.
- Compilers are excluded from elapsed time; no integrated Python-Rust FFI cost.
- Side N in vendor data is unknown aggressor, not observed delta.
- No model-training, data licensing, execution or profitable edge evaluated.

Raw vendor records are never committed; only aggregate summaries and hashes appear here.
