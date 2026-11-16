# MNQ Adaptive Order-Flow Research

**Automatic live MNQ:** [Live feed setup](LIVE_FEED.md) streams licensed CME trade prints and calculates POC, VAH/VAL, CVD, delta and 1m/5m/15m candidates without typing chart observations. This requires a separate authorized market-data entitlement and is not activated by default.

**For your current 25K evaluation:** start with [EVALUATION_25K.md](EVALUATION_25K.md). That plan shows a $1,500 target, $1,000 EOD trailing drawdown, $600 daily loss limit, and **no consistency rule**. The prior 50K configurations are not your selected account.

A **Python research and replay engine** for Micro E-mini Nasdaq-100 futures (MNQ) prints. It computes **1m / 5m / 15m** volume-at-price (VAP), volume POC, 70% value area (VAH/VAL), aggressive buy/sell volume, delta, RTH cumulative volume delta (CVD), and a history-calibrated *trade-print absorption proxy*.

**Current status: functional research prototype, not a live trading bot or validated profitable strategy. No brokerage connection and no order placement.**

## Data needed

Input is a **chronologically sorted CSV of executed trades** with the following columns:

| Column | Example | Definition |
| --- | --- | --- |
| timestamp | 2026-11-12T14:30:00Z | ISO 8601 with UTC offset |
| price | 20100.25 | Actual executed price aligned to 0.25 tick |
| size | 3 | Number of contracts |
| side | B or S | **Aggressor**: B = buyer-initiated; S = seller-initiated |
| contract (optional) | MNQZ26 | Exact MNQ contract expiry; one expiry per file |

**Do not invent aggressor classifications.** OHLCV candles and ordinary candlestick bars do not provide a reliable basis for exact cumulative volume delta. A platform that classifies trades using tick rules may differ from a feed with reliable aggressor-side flags. True resting-order absorption/icebergs require order-book or MBO depth events; this project's absorption **proxy** only detects concentration of aggressive prints near extremes and rejection in price.

Obtain historical trade data from an appropriately licensed provider. Do not publish redistributed proprietary CME market data into this public repo.

## Run on Chromebook Linux or another Python 3.11+ system

No external Python dependencies are needed.

~~~bash
git clone https://github.com/lafaillejeremiah7-droid/mnq-adaptive-orderflow.git
cd mnq-adaptive-orderflow

# Run synthetic example; prints latest completed 1-minute snapshot.
python3 -m mnq_flow sample/trades.csv

# Save one snapshot per completed minute.
python3 -m mnq_flow sample/trades.csv --out snapshots.jsonl

# Show candidate signals only.
python3 -m mnq_flow sample/trades.csv --candidates

# Validate implementation.
python3 -m unittest discover -s tests -v
~~~

Replace the sample path with an actual MNQ trade CSV to analyze real prints. The included sample is **synthetic demonstration data**, not historical MNQ trades.

## Signal hypothesis and adaptive logic

1. Use prints from 09:30–16:00 ET on weekdays; apply New York DST automatically. CME holiday/early-closing schedules are **not yet integrated**.
2. Create 1m, 5m, and 15m buckets and per-price volume profile. POC is the most-traded price; VAH/VAL expand around POC until at least 70% of total volume is captured. CVD sums signed aggressor volume and resets each RTH session.
3. Use **previous 20 completed 1m bars** to calibrate how unusual extreme-price aggressive volume is. Require at least 10 prior minutes. High sell-initiated volume at the low followed by an upward close gives a bullish proxy; high buy-initiated volume at the high followed by a downward close gives a bearish proxy.
4. Establish 15m bias from the two most recently **completed** 15m closes. Confirm a long candidate with positive delta from the last completed 5m bar, or the inverse for short candidates.
5. Require the 1m trigger to be near one of the prior-session POC/VAH/VAL, developing RTH POC/VAH/VAL **before the trigger minute**, or the most recently closed 5m/15m value-area levels. Distance tolerance adapts from prior 1m ranges, bounded at 4–16 ticks.
6. Only flag candidates from **10:00 to before 15:00 ET**. The result includes a 2-tick-outside-extreme invalidation *reference*, not a tested stop or fill prediction.

The engine only outputs snapshots after a 1m bar is verifiably closed by later data; still-forming 5m/15m bars are not used. A final partial bar is omitted unless later prints confirm its completion.

## Output fields

Each completed minute includes:
- 1m OHLC, buy/sell volume, delta and 70% volume profile.
- Most recent *closed* 5m and 15m profiles, OHLC and delta.
- RTH cumulative volume delta and developing RTH POC/VAH/VAL.
- Previous completed RTH session's profile.
- 15m bias, absorption-proxy flags, nearest reference level and distance.
- Signal: none, long_candidate or short_candidate, plus optional invalidation reference.

## Contract reference

CME specifies **$2 per Nasdaq-100 index point**, a **0.25-point minimum tick**, and **$0.50 per tick** for MNQ.

Source: https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html

## Known limitations

- **No real-time market feed.** The program analyzes user-supplied CSV files; it does not connect to TradingView, NinjaTrader, Quantower, Bookmap, broker APIs or exchanges.
- **No actual DOM absorption model.** An aggressive-print rejection proxy is not evidence that a particular passive trader was absorbing.
- **Not backtested.** No realistic transaction fees, exchange fees, spread, slippage, partial fills, drawdown, out-of-sample calibration, or walk-forward validation yet. Signals are research hypotheses.
- **No holiday calendar or early close exceptions**, data-quality filters, missing-trade reconciliation, continuous-contract rolling or futures settlement handling.
- A single input CSV must use one contract expiry; if the contract changes, split files rather than silently combine different expirations.
- Profile tie rules and 70% expansion can differ slightly from platform implementations.
- Adaptive describes the rolling threshold and tolerance only; there is no machine learning model or automatic retraining.

**Next development milestone:** Connect a licensed trade-print feed, add order-book-based absorption, write leak-free next-bar execution backtests with realistic cost assumptions, and assess performance out of sample before considering alerts or automated execution.
