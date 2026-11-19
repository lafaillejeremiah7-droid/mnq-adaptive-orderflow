# MNQ Agent — OCaml 5

A clean-slate, functional-first foundation for an MNQ futures trading **research and risk assistant**.

## Status

The repository contains a deterministic market-print aggregator, volume-at-price profile calculations, cumulative signed trade volume, and a strict **advisory-only** risk gate. It does **not** connect to Tradovate, independently verify a licensed live feed, recognize real order-book absorption, implement a validated entry strategy, or submit orders. An optional Databento **price-only** bridge is available below, but has not been authenticated or exercised against live CME market data here. No positive expectancy or payout probability has been established.

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
- `lib/price_stream.ml`: independent OHLC-only bar input; excludes delta, volume profile, and order book.
- `bin/main.ml --price-stream`: standalone price-derived regime monitor; no broker or order-flow integration.
- `test/test_core.ml`: deterministic tests; GitHub Actions runs them.

## Risk defaults (personal, not firm rules)

- Up to **$100** estimated loss per trade, including a configurable cost/slippage allowance.
- Up to **$200** personal daily realized loss.
- **2 trades maximum per day**, **2 consecutive losses maximum**, and at most 2 MNQ contracts.
- A configurable reserve above the broker-provided current drawdown floor.

These are **starter defaults**, not verification of your actual funded-account rules. The current equity, drawdown floor, daily P&L, open positions and trade counts must eventually come from a verified broker source. A trailing drawdown cannot be safely reconstructed from a fixed initial allowance. Stop fills can slip beyond estimates.

## Next milestone

Authenticate and validate the optional independent CME price feed and an account-state adapter; reconcile timestamps, session resets, rollovers, and exchange holidays; then validate price-based statistical hypotheses with fees and slippage on genuine out-of-sample data. Order-flow analysis remains with the user and is not consumed by the price-only monitor. Do not use experimental signals as automatic trading orders.

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

## Independent price-only Nasdaq futures feed (experimental)

**Input is CME MNQ (or NQ) futures prices, not the Nasdaq-100 NDX cash index.** These are different markets. This optional adapter does **not** request or analyze volume profile, cumulative delta, order-flow buying/selling pressure, absorption, or market depth. The user performs those analyses independently. The agent calculates only price-derived market regimes, volatility, historical price behavior and risk when appropriate.

`scripts/databento_price_only.py` uses Databento's `GLBX.MDP3` with **`ohlcv-1m`** and the continuous symbol `MNQ.c.0`. It prints timestamp plus four OHLC prices as 0.25-point integer ticks. `bin/main.ml --price-stream` consumes that narrow format and runs `Quant.on_closed_bar`, printing research-only regime and volatility readings after 21 contiguous bars. There is no Tradovate integration. Prices are **not** streamed into the older aggressor-trade/volume-profile feature pipeline. Price-only records carry *unknown* buy/sell quantities; the adapter uses zero placeholder fields solely to match the existing OHLC record type, and the quant path never uses them.

Requires **a Databento account with licensed CME live-data access**, an API key, and Python 3.10+ plus the Databento SDK. Subscription and exchange entitlements may cost money. The connector is not live until you configure these yourself; we cannot provide the key. Do not commit keys to GitHub.

```sh
python3 -m pip install databento
export DATABENTO_API_KEY='YOUR_PRIVATE_KEY'
python3 scripts/databento_price_only.py --symbol MNQ.c.0 | dune exec ./bin/main.exe -- --price-stream
```

Run from the cloned repository after installing OCaml 5 and Dune 3. Use `--symbol NQ.c.0` instead if you explicitly want E-mini prices. A rolling contract mapping will **not** automatically update a live subscription when the front month changes; restart/reconcile it and rebuild the warmup after rollovers. The current strict contiguous-minute policy stops on a gap (such as a session break or an interval without a bar) rather than silently bridging or fabricating missing prices. The monitor is not yet a resilient unattended live service. Market sessions, holidays, and auto-backfill still need implementing.

This feature outputs regime/volatility observations, not trading signals or verified probabilities. Real-time feed access, authenticated entitlement, and price freshness have not been demonstrated in this repository. The price-based model has not been validated on unseen MNQ data, and this path does not interact with the broker account or fix stop-loss execution.

Sources: [Databento live quickstart](https://databento.com/docs/quickstart/live), [Live subscription/symbology](https://databento.com/docs/api-live/client/subscribe), [Continuous futures caveat](https://databento.com/docs/api-live/basics).
