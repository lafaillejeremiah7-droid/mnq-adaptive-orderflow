# Integrated C++ NQ/MNQ profile acceleration

Complete Python and C++-accelerated profile outputs matched exactly.

| Dataset | Trades | Python median | C++ median | Speedup |
|---|---:|---:|---:|---:|
| synthetic_250k | 250,000 | 0.1042s | 0.0487s | 2.14× |
| historical_vendor_rth | 488,749 | 0.1884s | 0.0934s | 2.02× |

## Caveats

- Single GitHub runner, no CPU pinning, benchmark intervals or hardware replication.
- Both implementations share Python's value area, node and delta formatting logic.
- Timings exclude loading vendor ZIP/Parquet, source integrity verification and input Trade preparation.
- C++ import and Python binding overhead are included in every C++ call.
- Historical vendor sample is one day; exchange authenticity not independently established.
- No claim about NQ market direction, profitability, or overall model improvement.

Benchmarks demonstrate performance, not a valid tradable edge.
