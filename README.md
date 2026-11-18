# MNQ Agent — OCaml 5

A clean-slate, functional-first foundation for an MNQ futures trading **research and risk assistant**.

## Status

The repository contains a deterministic market-print aggregator, volume-at-price profile calculations, cumulative signed trade volume, and a strict **advisory-only** risk gate. It does **not** connect to Tradovate, ingest a licensed live feed, recognize real order-book absorption, implement a validated entry strategy, or submit orders. No positive expectancy or payout probability has been established.

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
- `test/test_core.ml`: deterministic tests; GitHub Actions runs them.

## Risk defaults (personal, not firm rules)

- Up to **$100** estimated loss per trade, including a configurable cost/slippage allowance.
- Up to **$200** personal daily realized loss.
- **2 trades maximum per day**, **2 consecutive losses maximum**, and at most 2 MNQ contracts.
- A configurable reserve above the broker-provided current drawdown floor.

These are **starter defaults**, not verification of your actual funded-account rules. The current equity, drawdown floor, daily P&L, open positions and trade counts must eventually come from a verified broker source. A trailing drawdown cannot be safely reconstructed from a fixed initial allowance. Stop fills can slip beyond estimates.

## Next milestone

Add a permissioned, contract-aware market-data adapter and independently validated account-state adapter; reconcile timestamps, RTH session resets, rollovers, and exchange holidays; then test order-flow hypotheses with fees and slippage on genuine out-of-sample data. Do not use experimental signals as automatic trading orders.

## Quant research gates (experimental)

`lib/quant.ml` adds an advisory-only calculation pipeline:

1. **Contiguous closed-minute bars only.** After 21 consecutive one-minute bars, a 20-move efficiency ratio and two smoothed true-range measures (5 and 20 minutes) classify a provisional regime: uptrend, downtrend, range, or volatility spike. A missing/duplicate bar fails closed; features are not calculated on the first trade of the next minute.
2. **Historical target-before-stop outcomes.** The research estimator selects only resolved prior examples from the *same regime, direction, target distance, and stop distance*. It requires at least 100 labeled examples by default in `test/test_quant.ml` (callers explicitly provide `min_samples`). Any example resolving at or after the evaluation timestamp is excluded to reduce look-ahead leakage.
3. **Conservative expectancy.** The lower one-sided 95% Wilson bound on the observed target-first fraction is used to calculate estimated net expectancy after assumed fees and slippage. The pre-existing broker account/risk gate must pass first. Missing historical labels, insufficient sample count, volatility spikes, or non-positive expectancy produce `Wait`, not permission to trade.

These are **research heuristics**, not trained/calibrated predictive probabilities, statistically independent samples, or demonstrated profitability. The 100-example minimum and regime thresholds are initial software defaults, not optimized or validated against MNQ. Labeling must use historical trade prints with an explicit first-touch rule for the same fixed target/stop horizon, and must avoid leakage from simultaneous or overlapping observations. The raw historical examples and broker snapshots are **not** present in this repository.

**No live orders, no Tradovate integration, and no live trade suggestions** are enabled by this change. Next, obtain permissioned data and run chronological train/validation/test evaluation with walk-forward splits, fees, spread, realistic slippage, and calibration and drawdown diagnostics before considering the model for live decision support.
