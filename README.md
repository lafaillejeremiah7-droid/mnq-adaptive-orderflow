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
