# Employee #1: Optional C++20 acceleration

**Status:** Functional research-only, optional native kernel. Python remains
the default and authoritative implementation. This module does not place
orders, connect a broker, or claim a tradable edge.

## Scope

The optional pybind11 C++ extension in company/_nq_cpp.cpp accelerates only
the aggregation of already prepared historical Trade objects. It computes
traded volume by price tick, buy/sell/unknown volume by tick and minute,
and exact integer-weighted totals. The original Python code still computes
POC, VAH, VAL, HVN/LVN, candle delta, first-touch price reactions and
research findings. No attempt is made to infer quote books or aggressor side
from unidentified trade prints.

Python and C++ paths are compared for **complete profile dictionary equality**
on both NQ and MNQ, varied value-area fractions, unknown sides, gap prices
and large integer weights. The C++ module uses checked signed-64-bit volume
totals and a 128-bit weighted accumulator to avoid silent wraparound.

## Build and usage

On Linux with a C++20 compiler and Python development headers:

    python -m pip install pybind11==3.0.1 setuptools wheel
    python setup.py build_ext --inplace
    python -m unittest discover -s tests -v

Run a registered study using a verified canonical historical trade CSV:

    python -m company.market_profile --spec protocol.json --trades trades.csv --out-root research-runs --profile-backend cpp

Programmatic equivalent:

    from company.market_profile import volume_profile
    result = volume_profile(trades, 0.70, backend="cpp")

The backend options are:

- **python**: authoritative default, with no C++ build required.
- **cpp**: explicit native backend. Fails with a build instruction if missing,
  even if the study contains no eligible session pairs.
- **auto**: native C++ for a group of 20,000+ trade objects if compiled;
  otherwise Python fallback.

Research results record both the requested aggregation mode and the actual
backend used for every evaluated session pair. In auto mode, small batches
still execute Python. Only a study that actually uses the native kernel
includes its C++ source/binary SHA-256 fingerprints; every run fingerprints
the Python research engine. The data admission result is separate. Native binaries are ignored by Git; compile for the correct
Python ABI, OS, architecture and compiler. Current builds are verified on
Linux GCC and Python 3.11/3.12. GNU-style 128-bit integer support limits
portability to Microsoft Visual C++ without additional changes.

## Two implementation and optimization passes

**First pass:** Three native hash tables accumulated volume-by-price,
aggressor-by-price and aggressor-by-minute, with Python reconstruction.

**Second pass:** The price-side and price-volume tables were merged into a
single price-bucket map, per-trade aggressor-side string allocation was
eliminated, bucket capacity was tuned for small and large batches, and
Python conversion overhead for side counters was reduced.

Full profile processing medians (same input Trade objects; excludes CSV /
Parquet decoding and trade-object creation):

| Pass | Data | Python | C++ | Relative speed |
|---|---|---:|---:|---:|
| Initial | 250k synthetic trade records | 104.2 ms | 48.7 ms | 2.14x |
| Initial | 488,749 vendor-reported NQZ6 RTH trades | 188.4 ms | 93.4 ms | 2.02x |
| Optimized | 250k synthetic trade records | 211.3 ms | 86.3 ms | 2.45x |
| Optimized | 488,749 vendor-reported NQZ6 RTH trades | 397.0 ms | 169.0 ms | 2.35x |

The two passes used different GitHub-hosted virtual machines. **Absolute
timings cannot be compared directly across these machines**, and the change
in within-run speedup ratio is suggestive rather than a controlled A/B
estimate of individual optimizations. Exact full-output agreement passed
on both passes.

The vendor sample comes from one checksum-checked day, not authenticated
multi-year CME tick/book records. Source quality and license restrictions
must be independently verified before institutional research.

See the latest committed snapshot in
studies/cpp-profile-acceleration/report.md and the machine-readable
studies/cpp-profile-acceleration/summary.json.

## Verification and reproducibility

The separate C++ GitHub Actions workflow compiles the native extension on
Python 3.11 and 3.12, runs all Python and C++ differential tests, validates
the end-to-end research output and C++ binary fingerprint, and reruns the
full-profile benchmark with real vendor-reported and synthetic samples.
Latest results are uploaded as immutable, per-commit workflow artifacts,
not directly pushed back to the active development branch. This prevents
report publication races while source code changes.

Reproduce benchmark locally after building the C++ kernel:

    python -m pip install pyarrow==20.0.0
    python -m benchmarks.cpp_profile_bench --vendor --rounds 5

Only aggregate timing/results are retained. Never commit restricted raw
market data.

## Limits

- No demonstrated speedup for statistical inference, scientific reasoning,
  risk mathematics, model training, data validation, order replay or trade
  execution. The full research pipeline was not benchmarked.
- C++ still reads Python Trade attributes while holding the GIL; no native
  streaming feed parser or complete Python overhead elimination exists.
- No full software fuzzing, independently reviewed C++ security audit,
  cross-platform build matrix or reproducible packaged wheel.
- No verified multi-year exchange tick/quote/book history or independent
  model validation. The Quant Researcher is not yet institutionally complete.
- Native acceleration is useful only when exact semantic parity and measured
  throughput justify its extra toolchain, compilation and safety burden.

**Architecture:** Python for research/science, Polars for tabular ETL, optional
C++ for proven counter-hot-path processing, Rust retained as an experimental
standalone comparator. Read docs/LANGUAGE_ARCHITECTURE_DECISION.md.
