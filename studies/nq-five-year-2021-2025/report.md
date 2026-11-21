# Five years of real historical NQ one-minute data: 2021–2025

**Pinned public third-party NinjaTrader exports; not synthetic.**
The files were checked against Git object fingerprints. This does not establish CME-origin authenticity.

## Hypothesis
Does prior 1m intrabar range forecast next 1m intrabar range?
Training: 2021–2023. Frozen holdout: 2024–2025.
Predictor: prior one-minute high-low normalized by open; result: next contiguous minute range in basis points.

Lower threshold 1.4160 bps, upper threshold 6.4696 bps.
Holdout observations after low: 163,762; after high: 88,463.
Eligible paired days: 474.
Median daily high-minus-low conditional next-bar difference: 5.788366397246647 bps.
Exploratory date-bootstrap interval: [5.651735520393263, 5.952361934295508] bps.

| Year | Real bars | Calendar dates | Median 1m range (bps) |
|---|---:|---:|---:|
| 2021 | 344,961 | 326 | 2.484 |
| 2022 | 266,764 | 240 | 4.902 |
| 2023 | 346,468 | 314 | 2.505 |
| 2024 | 345,551 | 318 | 2.351 |
| 2025 | 293,505 | 274 | 2.640 |

Holdout splits: {"2024": {"eligible_dates": 257, "median_effect_bps": 5.8250766872967255, "positive_date_share": 1.0}, "2025": {"eligible_dates": 217, "median_effect_bps": 5.708682784321903, "positive_date_share": 1.0}}

## Critical limits

- Public third-party NinjaTrader files; exchange authenticity and rights not independently verified.
- Quarterly contracts stitched and duplicates deleted by source processing.
- Source timestamps have no recorded time zone; no session-specific claims.
- OHLCV cannot reconstruct POC, VAH, VAL, HVN, LVN, footprint or absorption.
- Consecutive-bar observations are serially correlated; daily bootstrap is descriptive.
- This is one held-out hypothesis, not a trading-system validation.
- No spread, queue, execution costs, trade entries or positions were simulated.

No profitability or actual volume-profile claim is supported.

Source revision: https://github.com/tdtrader76/NQ_Backtest/tree/7ac6bd20d3fa46b25fa6d2db947200ef9860c6ef
Manifest contains all SHA-256 file fingerprints. Raw files are not redistributed.
