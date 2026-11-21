# NQ/MNQ aggregation benchmark: Python, Rust and C++

One narrow, deterministic task. **All integer outputs match exactly**.
Timing: five measured subprocess runs per language after one untimed warm-up.
Order randomized within rounds; CSV disk I/O included, compile time excluded.

| Dataset | Trades | Python median | Rust median | C++ median | Rust speedup | C++ speedup |
|---|---:|---:|---:|---:|---:|---:|
| synthetic_250k | 250,000 | 0.3256s | 0.0451s | 0.0299s | 7.22× | 10.90× |
| historical_vendor | 488,749 | 0.5779s | 0.0870s | 0.0529s | 6.65× | 10.91× |

## Interpretation

Pure Python remains the orchestration and statistical research language.
Native Rust/C++ should be used only for measured, independently validated bottlenecks; compare with optimized NumPy/Polars/Numba before embedding.
A benchmark speedup does not demonstrate higher forecast accuracy, statistical validity or trading profitability.

## Limitations

- Single shared GitHub runner; no CPU pinning, multiple hosts or capacity testing.
- Python baseline uses Python loops, not optimized NumPy, Polars or Numba.
- This compares a narrow profile hot path, NOT the full Python research engine.
- Only one vendor-reported trading day is used; exchange origin not authenticated.
- Compilers are excluded from elapsed time; no integrated Python-Rust FFI cost.
- Side N in vendor data is unknown aggressor, not observed delta.
- No model-training, data licensing, execution or profitable edge evaluated.

Raw vendor records are never committed; only aggregate summaries and hashes appear here.
