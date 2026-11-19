# MNQ Agent — OCaml 5

A clean-slate, functional-first foundation for an MNQ futures trading **research and risk assistant**.

## Status

**Offline research only.** All real-time and delayed-price polling scripts, stream commands, and associated tests were deliberately removed. This repository does not fetch or display the current NQ/MNQ market price. Historical replay and a separate, opt-in historical-data importer remain available.

The repository contains a deterministic market-print aggregator, volume-at-price profile calculations, cumulative signed trade volume, and a strict **advisory-only** risk gate. It does **not** connect to Tradovate, independently verify a licensed live feed, recognize real order-book absorption, implement a validated entry strategy, or submit orders. Historical OHLC research and offline replay are supported. No live or delayed NQ futures price feed is installed; the optional QQQ gamma snapshot adapter is on-demand. No positive expectancy or payout probability has been established.

The core accepts **actual aggressor-side trade prints**; ordinary OHLCV bars cannot reliably reconstruct bid/ask delta or footprint data. Cumulative delta and profile are labeled **since stream start**, not RTH-session values, until a validated session calendar and warmup mechanism are added.

## Build

Requires OCaml 5.x and Dune 3.x:

```sh
dune build
dune runtest
dune exec ./bin/main.exe
```

## Architecture

- `lib/market.ml`: strictly ordered prints, completed 1-minute bars, fail-closed missing-minute detection.
- `lib/profile.ml`: volume-at-price and deterministic 70% value area.
- `lib/features.ml`: market-derived features and a snapshot that excludes the next minute's first print.
- `lib/risk.ml`: trade count, loss, drawdown-floor, position, freshness, and signal gates. **REVIEW_ONLY is not permission to execute.**
- `lib/price_stream.ml`: offline historical OHLC bar parser; excludes delta, volume profile, and order book.
- `bin/main.ml --price-replay`: offline price-derived regime summary; no market-data streaming.
- `test/test_core.ml`: deterministic tests; GitHub Actions runs them.

## Risk defaults (personal, not firm rules)

- Up to **$100** estimated loss per trade, including a configurable cost/slippage allowance.
- Up to **$200** personal daily realized loss.
- **2 trades maximum per day**, **2 consecutive losses maximum**, and at most 2 MNQ contracts.
- A configurable reserve above the broker-provided current drawdown floor.

These are **starter defaults**, not verification of your actual funded-account rules. The current equity, drawdown floor, daily P&L, open positions and trade counts must eventually come from a verified broker source. A trailing drawdown cannot be safely reconstructed from a fixed initial allowance. Stop fills can slip beyond estimates.

## Next milestone

Obtain properly licensed historical price bars and validate price-based statistical hypotheses with fees, slippage and genuine out-of-sample data. Live-price and delayed-price integrations have been removed. Order-flow analysis remains with the user and is not consumed by the price-only monitor. Do not use experimental signals as automatic trading orders.

## Quant research gates (experimental)

`lib/quant.ml` adds an advisory-only calculation pipeline:

1. **Contiguous closed-minute bars only.** After 21 consecutive one-minute bars, a 20-move efficiency ratio and two smoothed true-range measures (5 and 20 minutes) classify a provisional regime: uptrend, downtrend, range, or volatility spike. A missing/duplicate bar fails closed; features are not calculated on the first trade of the next minute. A regime older than 120 seconds or future-dated at review time fails closed.
2. **Historical target-before-stop outcomes.** The research estimator selects only resolved prior examples from the *same regime, direction, target distance, and stop distance*. It requires at least 100 labeled examples by default in `test/test_quant.ml` (callers explicitly provide `min_samples`). Any example resolving at or after the evaluation timestamp is excluded to reduce look-ahead leakage.
3. **Conservative expectancy.** The lower one-sided 95% Wilson bound on the observed target-first fraction is used to calculate estimated net expectancy after assumed fees and slippage. The pre-existing broker account/risk gate must pass first. Missing historical labels, insufficient sample count, volatility spikes, or non-positive expectancy produce `Wait`, not permission to trade.

These are **research heuristics**, not trained/calibrated predictive probabilities, statistically independent samples, or demonstrated profitability. The 100-example minimum and regime thresholds are initial software defaults, not optimized or validated against MNQ. Labeling must use historical trade prints with an explicit first-touch rule for the same fixed target/stop horizon, and must avoid leakage from simultaneous or overlapping observations. The raw historical examples and broker snapshots are **not** present in this repository.

**No live orders, no Tradovate integration, and no live trade suggestions** are enabled by this change. Next, obtain permissioned data and run chronological train/validation/test evaluation with walk-forward splits, fees, spread, realistic slippage, and calibration and drawdown diagnostics before considering the model for live decision support.

### First-touch labeling (research-only)

`lib/labeling.ml` labels completed 1-minute future bars after a hypothetical entry as target-first, stop-first, or time-limit. It deliberately **rejects** candles that hit both stop and target in the same minute, because OHLC cannot reconstruct which traded first. It also fails closed on missing, duplicate, or invalid bars. Incomplete horizons are excluded rather than mislabeled. It does **not** establish that an order at the assumed entry price would have filled.

Quant evidence now requires the same **direction, regime, target distance, stop distance, and vertical horizon** for every historical example. A time-limit is counted as a non-target; this conservative shortcut does not estimate the actual time-exit P/L, which would require a fill-aware simulator and separate dataset.

## External methodology references (ideas only; code not copied)

- [quantowl](https://github.com/landtml/quantowl): triple-barrier event labeling, purging/embargo to address overlapping look-ahead windows, and backtest overfitting tests. The first-touch labeler follows this general methodology, not its implementation.
- [hftbacktest](https://github.com/nkaz001/hftbacktest): event-driven fill simulation with spread, queue position and transport/order latency. It is a useful model for backtest realism, but its crypto-specific data adapters cannot be assumed to work with MNQ or Tradovate.
- [River](https://github.com/online-ml/river): streaming prediction, delayed supervision, and concept drift monitoring. Add only after historical probability calibration is demonstrated.
- [Owl](https://github.com/owlbarn/owl): OCaml-native numerical computing, useful if a larger ML or regression model is later justified. No new dependency added now.
- [arch](https://github.com/bashtage/arch): conditional volatility estimation and backtests for more advanced volatility baselines.
- [ruptures](https://github.com/deepcharles/ruptures): offline structural-break detection, a research baseline rather than a live look-ahead-free detector.
- [vectorbt](https://github.com/polakowo/vectorbt): large batch strategy experiments, useful for an optional offline Python research pipeline.
- [QuantStats](https://github.com/ranaroussi/quantstats): performance, drawdown and Monte Carlo reporting after replay data and trade histories exist.
- [NautilusTrader](https://github.com/nautechsystems/nautilus_trader): event-driven parity between offline simulation and live code paths; substantial integration complexity, not needed in Phase 1.

**Next validation milestone:** obtain appropriately licensed MNQ tick/quote data and broker order records, reproduce observed real stop/limit/market fill behavior, then run strict chronological walk-forward tests with purge windows for overlapping labels. Until then all quant signals remain research-only and no observed forecast reliability is claimed.

## Offline MNQ price replay (research-only, no trading integration)

There is a separate path for historical **price-only** analysis. It does not use Tradovate, volume profile, cumulative delta, buying/selling pressure, absorption, positions, or trading-account funds.

The `--price-replay` mode accepts a chronologically increasing CSV with **no header**:

```text
1699999980000,80000,80010,79996,80006
1700000040000,80006,80016,80001,80014
```

Fields: `minute_start_utc_ms,open_ticks,high_ticks,low_ticks,close_ticks`; all price fields are **integer 0.25-point ticks**, not displayed index points. The example numbers above are illustrative, not genuine market data. Historical gaps start new contiguous segments with a fresh 21-bar warmup; duplicate or out-of-order timestamps are rejected. No synthetic bars are inserted.

To replay an already obtained, appropriately licensed MNQ price CSV:

```sh
cat mnq_prices.csv | dune exec ./bin/main.exe -- --price-replay
```

This prints the number of bars, gaps/segments, classified bars, and counts of uptrend/downtrend/range/volatility-spike observations. **These are descriptive numbers only**—not predictive accuracy, estimated trade win rate, or strategy P/L. Segments with fewer than 21 consecutive bars provide zero classified observations.

### Optional historical CME data import

The data importer uses Databento `GLBX.MDP3` `ohlcv-1m` continuous `MNQ.c.0`. You must own a Databento key and have historical access to the relevant CME dataset. **Data queries may incur provider charges**. The script requires an explicit opt-in flag and limits each request to **at most seven calendar days** to reduce accidental large historical bills. It does not make any request without those prerequisites.

```sh
python3 -m pip install databento
export DATABENTO_API_KEY='YOUR_PRIVATE_DATABENTO_KEY'
python3 -m scripts.databento_historical_prices \\
  --symbol MNQ.c.0 \\
  --start 2026-11-09 --end 2026-11-12 \\
  --output mnq_prices.csv --allow-provider-charges
cat mnq_prices.csv | dune exec ./bin/main.exe -- --price-replay
```

Ensure your API key is not saved in GitHub, shell history, public notebooks or chat messages. Both the Python conversion and the OCaml parser are testable offline without provider access.

The historical importer writes the CSV only after successful completion, refuses to overwrite an existing file, and does not fill missing minutes or bridge discontinuities from weekend closures and futures contract rollovers.

**Remaining work before the quantitative engine is useful for decisions:** genuine backtest data, rollover-aware mapping, realistic fills, purged chronological validation for overlapping labels, calibration checks, and an independently verified broker-state adapter. The historical replay does not attempt these claims or place orders.

API references: [Databento historical timeseries](https://databento.com/docs/api-historical/timeseries/timeseries-get-range?lang=python), [iterating DBN records](https://databento.com/docs/api-historical/helpers/dbn-store-iter?lang=python), [continuous futures mapping](https://databento.com/docs/examples/symbology/continuous).


## Offline QQQ put/call walls mapped to NQ futures (no live-price feed)

The Python research module at scripts/qqq_option_walls.py calculates **QQQ options walls** and converts those option strikes into approximate **NQ/MNQ futures price levels** using time-aligned QQQ and NQ price snapshots. It uses **only QQQ options**, never NDX options. There are **no external HTTP requests, subscriptions, credentials, browser integrations, trading signals, or order entry** in this feature.

Two definitions are supported:

- --metric gex (default): largest **unsigned call-side** and **unsigned put-side** gamma exposure *magnitude* by QQQ strike. For each standard QQQ option, exposure per 1% QQQ move is approximated by: gamma × open interest × 100 shares × QQQ price² × 0.01. Aggregates by strike separately across calls and puts. It does not infer whether dealers are net long or short gamma, and is **not a signed dealer GEX, gamma flip, or guaranteed support/resistance prediction**.
- --metric oi: largest call and put **open interest** by strike, irrespective of gamma. These are **OI concentration levels, not gamma walls**. You must select this mode explicitly if you do not have option gamma; missing gamma never silently becomes an OI wall.

Provide a QQQ options CSV with headers:

`expiration,option_type,strike,open_interest,gamma`

Each record corresponds to a standard QQQ call or put contract with its expiration (YYYY-MM-DD), strike in QQQ dollars, open interest (contracts), and option gamma per $1 move in QQQ. A multiplier column is optional but, when supplied, must equal 100. Missing or nonstandard option contracts, duplicate contract rows, negative inputs, and incomplete gamma data are rejected.

The example CSV at examples/ILLUSTRATIVE_qqq_option_chain.csv is **invented test data, not observed market data**. Do not treat its levels as current.

### Example: calculate with your own actual snapshot

After updating your cloned GitHub repo, obtain a QQQ option-chain snapshot and time-aligned QQQ and NQ futures reference prices. Use UTC ISO-8601 timestamps of **the actual observations**; do not use current clock time for old data. An **illustrative** command is:

```bash
python3 -m scripts.qqq_option_walls \
  --chain examples/ILLUSTRATIVE_qqq_option_chain.csv \
  --metric gex --expiration 2026-11-20 \
  --chain-asof 2026-11-18T15:00:00Z \
  --qqq-price 600 --qqq-asof 2026-11-18T15:00:00Z \
  --nq-price 24000 --nq-asof 2026-11-18T15:00:00Z
```

For these **synthetic inputs only**, the gamma-weighted QQQ call wall is 610 → approximately 24,400.00 NQ; the put wall is 590 → approximately 23,600.00 NQ. When selecting --metric oi for the same example, the largest OI levels are different. You can omit --expiration to aggregate across all expirations in the CSV. This code does not independently source options chains or reference prices.

**Conversion:**

`NQ_equivalent = QQQ_strike × (NQ_reference_price / QQQ_reference_price)`

The result is rounded to the nearest legal NQ futures tick (0.25 index points). QQQ/NQ reference timestamps must be within **five minutes** of each other, and must occur within **30 minutes after the options snapshot**, rather than before it, to prevent accidental historical look-ahead. These are conservative initial data-quality gates, not a proof that basis or tracking error is negligible. Recompute when either market's price changes. NQ and MNQ use the same index-points price scale, but have different dollar multipliers.

**Interpretation:** QQQ option strikes and NQ futures are related, but their levels are not mechanically identical. The conversion is approximate and depends on the chosen NQ futures contract, futures basis, QQQ tracking, and timing. OI is ordinarily published with a lag, so the supplied gamma and OI values may have different effective timestamps; record their provenance and do not claim real-time dealer positioning.

The output is JSON, with the selected QQQ strike, mapped NQ price, chosen wall weight, and the complete source timestamps. The command is **offline**: historical replay and QQQ options processing remain separate; neither restores the Yahoo or Databento live-price feeds that were removed.

Methodological references: [OCC standard 100-share equity options](https://www.theocc.com/clearance-and-settlement/clearing/equity-options-product-specifications), [QQQ gamma levels explained](https://quantwheel.com/tools/gex/qqq), [NQ/QQQ ratio mapping](https://quantwheel.com/tools/futures-gex/nq).


## Today's QQQ call/put gamma walls — automatic on-demand fetch (free, no key)

Run **python3 -m scripts.qqq_walls_today** from the repository root. This makes a
single, on-demand QQQ-only API request to AlgoX Flow's documented free API.
It retrieves provider-modeled QQQ **call wall, put wall, IV, gamma flip (when supplied),**
and the exact vendor snapshot timestamp. It is not a full raw option-chain
download, does not independently recompute dealer exposures, and does not
claim these levels are live. The provider states nearest-expiration and
partial-chain limitations. It may block or change access; failure is reported.

```bash
cd ~/mnq-adaptive-orderflow
git pull
python3 -m scripts.qqq_walls_today
```

No subscription, broker login, API key, Yahoo feed, NQ futures quote reader,
continuous polling, or execution path is added. It checks the market
snapshot's **US/Eastern calendar date** against today's date, refuses
explicitly stale/future-dated snapshots, and defaults to a maximum 10-hour
snapshot age to accommodate the day's post-close research. It locally caches
a provider response for at least 15 minutes, consistent with the vendor's
recommended request cadence. On weekends and before new same-day data is
available, it reports **UNAVAILABLE** rather than disguising yesterday's
levels as today's.

### Optional QQQ wall to NQ/MNQ-equivalent conversion

The data source does **not** provide an authorized NQ futures quote. To
compute a mapping without restoring a futures price feed, pass a verified
NQ futures reference price **from your own chart**, observed at approximately
the same time as the provider QQQ snapshot. Use the **actual UTC observation
timestamp**, never simply the time the script was started.

```bash
# EXAMPLE VALUES ONLY — replace with a real same-time chart observation
python3 -m scripts.qqq_walls_today \
  --nq-price 24000 \
  --nq-asof 2026-11-18T20:01:00Z
```

For this illustrative example, a source snapshot at
**2026-11-18T20:00:00Z** would be compatible. The script **rejects**
references more than 5 minutes apart; mapping is omitted if no NQ
reference is provided. The formula is
`QQQ strike × (NQ reference / provider QQQ spot)`,
rounded to the nearest 0.25-point NQ tick. NQ and MNQ price levels match
in index points, not dollar value per contract. This mapping is an
**approximation**, not a native NQ options-gamma level; in addition, the
provider's QQQ spot last-trade timestamp is not independently given.

**Provider scope:** This on-demand API supplies vendor-derived wall estimates
and is separate from the more granular, offline
`scripts/qqq_option_walls.py` CSV calculator. We do not
claim fresh full-chain option positions, or that put/call walls must hold.
Before using a historical signal, distinguish the provider's cache time
from the source option data's true observation time.

**Required attribution:** [Options gamma data by AlgoX Flow](https://algoxflow.com).
Free API documentation and usage terms: https://algoxflow.com/api-docs .
