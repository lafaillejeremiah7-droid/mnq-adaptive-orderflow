# Employee #1 — NQ/MNQ Volume Profile and Level Reaction Lab

## What this build implements

- Real **trade-by-trade** (not candle) volume-at-price using 0.25-point tick bins and summed executed contract sizes.
- Completed-session POC: highest traded-volume tick. Exact ties select the tick nearest volume-weighted average price, then the lower price.
- Value area: start at POC and expand contiguously by the larger immediately adjacent volume bin until at least the requested fraction (default 70%) is covered. Ties choose the bin closer to VWAP, then the lower bin. VAH/VAL are the included upper/lower tick prices. This algorithm can differ from platform implementations.
- HVN: strictly peaked local tick bins (one-tick neighbors), peak volume at least 50% of POC volume. LVN: nonzero local trough at most 50% of POC volume. Five extreme nodes of each type retained. Empty price bins are counted separately and are **not** mistaken for traded LVNs.
- VWAP and explicitly **known-aggressor** trade delta (B buyer-initiated, A seller-initiated, N unspecified). Unknown side volume is disclosed; prints cannot reconstruct resting-book absorption.
- Price reaction study: compute all levels from the **prior observed completed New York regular trading session**, then observe the *next* session's first actual printed touch of each distinct level. Measure whether price reaches the predeclared threshold back on the approach side (**rejection first**) or beyond the level on the opposite side (**cross first**) within the predeclared horizon. Also report unresolved and censored events.
- Exploratory non-matched control: a seeded, randomly sampled previously traded price bin not within tolerance+4 ticks of a named level, subject to availability. It is **not** a causal or statistically matched baseline.
- Immutable runs with input, protocol and engine hashes; unit tests reject mixed NQ/MNQ contracts, tick misalignment, reversed timestamps, broken hashes and incomplete input.

## Required source data

The engine needs individual, timestamped **executed trades with sizes at each price**. Minute OHLCV cannot reveal exactly which price traded how many contracts; distributing candle volume over prices invents data. Order book depth requires a separate market-by-price or market-by-order dataset. A one-minute-bar source is deliberately rejected.

Canonical UTF-8 CSV header:

    timestamp_ns,contract,price,size,side,sequence

`timestamp_ns`: UTC nanoseconds since UNIX epoch; `contract`: one explicit `NQH5`, `MNQH5`, etc. quarterly contract, no spreads or mixed symbols; `price`: positive decimal 0.25-tick price; `size`: positive integer traded contracts; `side`: `B` buy aggressor, `A` sell aggressor, `N` unknown; `sequence`: exchange/vendor event sequence (used to order equal timestamps). The file must be sorted by (timestamp_ns, sequence) ascending. The current research implementation loads a bounded file (maximum 5 million rows, configured lower by default). Partition larger samples by session and preserve coverage.

### Optional Databento export adapter (no paid calls)

The offline adapter accepts an already **downloaded** `GLBX.MDP3` *trades* schema CSV exported from a Databento `DBNStore.to_df(pretty_px=True, map_symbols=True)` DataFrame with visible `symbol`, `ts_event`, `sequence`, `price`, `size` and `side` columns. It requires display-scaled prices, not the raw integer 1e-9 price representation. Some DataFrame exports require naming the datetime index `ts_event` before writing CSV. It rejects book-update schemas and mixed instruments.

    python -m company.databento_trade_csv --input /path/to/db_trades_export.csv --contract NQH5 --output /path/to/nqh5_canonical.csv

**Databento docs:** https://databento.com/docs/schemas/trades and https://databento.com/docs/api-historical (data availability, symbol mapping, and feed permissions). No client credentials, paid historical calls, auto-download, or new trading integrations are included. Use legally obtained, exchange-licensed data.

### Freeze a research question

Create a JSON protocol with the keys below. Obtain the exact data SHA with `sha256sum /path/to/nqh5_canonical.csv`. A documented starting protocol:

```json
{
  "id": "nqh5-prior-rth-poc-reactions",
  "question": "How often do first touches of yesterday’s POC/VAH/VAL/HVN/LVN reject rather than cross?",
  "falsifier": "The observed rejection-first share does not exceed matched controls on untouched data.",
  "data_source": "Name provider, symbol, schema, coverage dates and export version",
  "data_sha256": "REPLACE_WITH_64_CHAR_SHA256_OF_EXACT_CSV_BYTES",
  "data_kind": "historical",
  "contract": "NQH5",
  "rth_start": "09:30",
  "rth_end": "16:00",
  "value_area_fraction": 0.70,
  "touch_tolerance_ticks": 1,
  "excursion_ticks": 8,
  "horizon_seconds": 300,
  "min_profile_trades": 500,
  "min_eval_trades": 500,
  "min_session_pairs": 20,
  "max_gap_calendar_days": 4,
  "seed": 42,
  "max_trades": 1000000
}
```

Then run:

    python -m company.market_profile --spec /path/to/protocol.json --trades /path/to/nqh5_canonical.csv --out-root research-runs
    python -m unittest discover -s tests -v

Results save under `research-runs/<id>/protocol.json`, `result.json`, and `research_note.md`. `result.json` provides profile levels and price-at-volume counts by historical date, each next-day event with timestamp/approach/outcome and the aggregate rates. The source file remains on your machine rather than being uploaded to public GitHub.

## Interpretation and experimental design

The study's time origin is the first trade **actually printed** at or within tolerance of a named level *after a trade outside tolerance*; a jump over the level without a print is not considered a touch. Future observations are considered only after the touch and for up to the declared horizon. The first excursion of N ticks in the approach direction is rejection-first; first excursion of N ticks through the level is cross-first. Censored events are reported separately; each *unique physical* level is touched at most once per next-day session (coincident POC/VAH/VAL prices are deduplicated). The result retains first-passage time, observed follow-up count, and maximum signed excursions up to the horizon. Follow-up movement is descriptive, not evidence of a fill.

Both the initial volume profile and the comparison must use **the appropriate NQ or MNQ contract**. A prior observed weekday is not necessarily the immediate prior exchange trading session if the dataset has omissions. Up to four calendar days between observed sessions are permitted to include weekends; validate exchange holidays and data continuity separately.

**No automatic edge claim:** unregistered hypothesis searches, very large numbers of correlated tests, missing or thin trade coverage, sample reuse, lookahead, vendor differences, and unmodeled spread/slippage can all create false discoveries. The level comparison is a descriptive event study; it does not estimate P&L, Sharpe, strategy expectancy, a probabilistic forecast or a statistically significant causal effect. Reject or mark inconclusive rather than invent proof.

## Planned extensions (not implemented here)

- Developing as-of-session profile, anchored ranges, Globex profile templates, multi-contract rollover and intermarket basis-adjusted comparisons.
- Matched placebo levels, session-block bootstrap, multiple-testing adjustment, cross-regime walk-forward and prospective validation.
- Price-level trade delta, footprint, cumulative delta, and absorption hypotheses with appropriate trades/quotes and market-by-order book reconstruction.
- Further stochastic models (Markov, Bayesian, HMM, realized volatility, Hawkes, regression, Monte Carlo) only after defining a distinct falsifiable purpose and verifying required source fields.

Reference for conventional volume profiles: https://www.tradingview.com/support/solutions/43000502040-volume-profile-indicators-basic-concepts/
Reference for trade fields: https://databento.com/docs/schemas/trades
