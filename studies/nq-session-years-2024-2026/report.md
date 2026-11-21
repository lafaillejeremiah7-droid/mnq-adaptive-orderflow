# NQ opening versus midday range across 2024–2026

Third-party market bars from a Git commit-pinned public file. The file explicitly supplies New York timestamps and sessions.
The source mixes providers and has unadjusted futures roll discontinuities. This is NOT verified CME tick history.

Hypothesis: average one-minute (high-low)/open bps is greater during 09:30–09:59 ET than 12:00–12:29 ET.
Only dates with all 60 required minute bars were included.

Total complete paired dates: 593.
Overall date-paired result: {'n': 593, 'median': 5.143480127564234, 'mean': 5.480078291194084, 'positive_share': 0.9763912310286678, 'bootstrap_95pct': [4.908889375606625, 5.522269632941325]}

| Year | Complete paired dates | Median open-minus-midday (bps) | Opening larger share |
|---|---:|---:|---:|
| 2024 | 137 | 4.5010 | 99.3% |
| 2025 | 257 | 4.5967 | 96.5% |
| 2026 | 199 | 6.7096 | 98.0% |

## Interpretation limits

- Descriptive price-range seasonality does not forecast direction or establish profitable trade entries.
- This series is not an untouched holdout after prior exploratory investigations.
- Dates and intraday observations may be dependent; interval resamples dates as blocks.
- Vendor composition changes, missing volume and front-month rolls limit generalization.
- One-minute OHLCV has no actual volume-at-price, POC/VAH/VAL/HVN/LVN or order-book imbalance.
- No exchange-level authenticity verification, fill model, trading-cost model or broker connection.

Pinned data file: https://github.com/kfccolonel1/BARS/blob/b8f2d8ab36e44c289036ce093bf7c9f04073a7d9/NQ/1min/NQ_1min_continuous.csv.gz
Aggregate report only. Raw vendor files are not redistributed.
