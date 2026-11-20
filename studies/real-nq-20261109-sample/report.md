# Historical NQZ6 volume profile and price reactions

**This is an actual downloaded, checksum-verified vendor tick sample, not synthetic unit-test data.**
Its CME provenance and completeness have not been verified independently.

Date: 2026-11-09; contract: NQZ6; one trading day.

Full UTC window: 710,815 trade records and 766,017 contracts.
RTH 09:30-16:00 ET: 488,749 trade records and 526,348 contracts.
Opening 09:30-10:00 ET frozen POC 27540.00, VAH 27784.25, VAL 27517.75.
Opening profile: 104,312 contracts, VWAP 27595.856.
HVNs: [27540.0, 27761.5, 27545.25, 27559.0, 27590.0]
LVNs: [27318.25, 27395.75, 27404.75, 27407.75, 27424.0]

## Price reaction after levels were frozen

One level touch when price prints within 1 tick after previously being outside; the first 8-tick excursion within 300 seconds determines rejection/cross.

| Level | Touches | Rejections | Crosses | Unresolved | Censored |
|---|---:|---:|---:|---:|---:|
| HVN | 1 | 0 | 1 | 0 | 0 |
| VAH | 1 | 0 | 1 | 0 | 0 |

## Earlier half-hour profile tested in following half-hour

All 12 comparisons share the same date: not 12 independent trading days.

| Level | Touches | Rejections | Crosses | Unresolved | Censored |
|---|---:|---:|---:|---:|---:|
| HVN | 34 | 13 | 21 | 0 | 0 |
| LVN | 35 | 18 | 17 | 0 | 0 |
| POC | 9 | 6 | 3 | 0 | 0 |
| VAH | 9 | 5 | 4 | 0 | 0 |
| VAL | 6 | 6 | 0 | 0 | 0 |

## Research limitations

- One day only; 12 rolling windows are strongly dependent.
- The source vendor asserts CME origin; exchange authenticity is not independently verified.
- Vendor terms restrict raw-sample redistribution and commercial use.
- No quotes/MBO, queue, spreads or realistic transaction-cost simulation.
- Unknown aggressor direction: no trusted absorption conclusions.
- A touch from printed trades is not evidence that a limit order filled.
- No prospective holdout or significance estimate.

No evidence of a profitable strategy or predictive edge is established.

Source: https://historicalfuturesdata.com/samples/pack/es-nq-tick-sample-2026-11-09.zip
Manifest: https://historicalfuturesdata.com/samples/pack/manifest.json
Archive SHA256: 0393ec579d453d016b5a838392349a0e6f21f3ddd211f3e7c24bb5c8cb63fc72
Tick Parquet SHA256: 89a50dc88c4beacafd95b8cc4e2f7ee9000af498549dcb0910aa08feed82dba0
