# Five-Year MNQ Order-Flow Validation — Current Status and How to Run

**Status: NOT YET BACKTESTED ON 3–5 YEARS OF REAL MARKET DATA.**
The repository does not include licensed historical tick records, and the
owner's **live Tradovate chart subscription does not automatically provide
a downloadable 3–5-year signed-trade archive**. It would be false to report
a win rate or $25K-evaluation pass probability without that history.

## Your live Tradovate data is useful, but different

You already see live bid/ask, VAP, delta, CVD, and possible absorption.
These are enough for a *native on-chart live assistant* via the
[Tradovate indicator](tradovate/MNQPayoutSetupCoach.js). They are not
proof you have every executed trade and aggressor side from 2021–2025
in files suitable for automated replay.

Tradovate's **2025 historical-data article** states: tick charts
up to 1 year, minute data since 2006, and Market Replay back to 2017
when the Replay entitlement is active. Market Replay is a plausible way
to *visually and manually* validate on real past sessions using the
exact MNQ futures expiry, but **it is not a verified bulk-data export
API** for this evaluation account. A Market Replay account or add-on
may be required separately. Do not assume it is included in your
prop-firm evaluation.

Official references:

- https://ninjatrader.my.site.com/tradovate/s/article/Available-Historical-Data-Tradovate?language=en_US
- https://vendor-support.ninjatrader.com/s/article/Market-Replay-Tradovate?language=en_US
- https://support.ninjatrader.com/s/article/Tradovate-API-Access?language=en_US

The Tradovate official API explicitly excludes prop-firm/evaluation
accounts and does not provide market-data access through the ordinary
API subscription. Do not try to bypass its account/data entitlement
or collect data against exchange terms.

## Three-year data gate and backtest

The new [historical_validate.py](mnq_flow/historical_validate.py)
requires **actual executed MNQ trade prints with aggressor-side labels**,
not quote-only tick data and not OHLCV candles.

One or more chronologically ordered local CSV files:

    timestamp,price,size,side,contract
    2023-06-14T09:30:00-04:00,20000.25,1,B,MNQM23
    2023-06-14T09:30:00.100000-04:00,20000.00,2,S,MNQM23

These rows illustrate the **file format only**, and are fabricated
examples, not historical market prints. B means buyer-aggressor, S
means seller-aggressor; traded quantity, time, price, and exact MNQ
expiry must all be from the real data source. Historical **quotes at
the bid and ask do not determine aggressor side with certainty**.

Place **licensed historical CSV files outside the public GitHub
repository**, for example ~/MNQ_History/2021/... through 2025/...,
with filenames sorting chronologically. Never publish the market data
or credentials.

For data from 2022, 2023, and 2024 (or any 3 consecutive complete years):

    python3 -m mnq_flow.historical_validate \
      --ticks-dir ~/MNQ_History \
      --min-years 3 --fee 2.50 --slippage-ticks 1 --reward-multiple 2 \
      --out ~/mnq-history-audit.json

To demand five complete years:

    python3 -m mnq_flow.historical_validate \
      --ticks-dir ~/MNQ_History --min-years 5 \
      --out ~/mnq-history-audit-5y.json

If even one of the required 3–5 calendar years has fewer than
**200 complete 09:30–15:55 ET sessions**, the status is
BLOCKED_HISTORY_INCOMPLETE, performance is null, and the command
exits with code 2. Incomplete sessions and mixed expiries are excluded
or rejected rather than inventing missing data. Holidays, early
closes and halted periods are conservatively excluded. This is a
*coverage heuristic* rather than exchange-calendar proof.

## What the fixed-rule replay actually assumes

It reuses the existing **Python** LiveAnalyzer signals and then simulates:

- Signal only after completed 1m candle; entry at a **later** executed print.
- **One MNQ** contract; stop two 0.25-point ticks outside signal candle.
- Target at a fixed **2:1** reward/risk; stops resolved in timestamp
  order, not by guessing the order of OHLC intrabar touches.
- A hypothetical roundtrip fee of **$2.50** and adverse **1 tick**
  on entry and exit. Replace with accurate fee/fill information.
- Personal limit of **$50 planned risk per trade**, **$100 daily
  stop**, **two trades per day**, and **$150 reserve above trailing floor**.
- Provisional $25K evaluation, **$1,500 target**, **$1,000 EOD trailing
  floor**, **$600 firm daily loss**, and a new hypothetical evaluation
  after each completed pass/failure.
- Separate yearly net results and the **last calendar year as the
  chronological holdout**, with no parameter optimization.

**Important shortcomings before trading decisions:**

1. This Python strategy is **not parity-tested** against the Tradovate
   JavaScript indicator. Matching the live on-chart setups is a separate
   verification step.
2. A target touched by a traded price does **not** prove that a
   real order would fill. Market depth, queue priority, stop-market
   slippage, partial fills, outages, tick feed corrections and latency
   are not fully modeled.
3. The EOD trailing floor is an **assumed implementation**. Check the
   firm's exact high-water-mark, intraday-vs-EOD treatment, max loss
   cap, fee inclusion, daily limit definition, and payout transitions.
4. No true MBO/DOM absorption or iceberg logic is simulated. A
   prints-only rejection flag is a proxy, not the same as order-book
   liquidity absorption.
5. The last-year holdout is time ordered, but it is **not fully
   independent** until all strategy rules are frozen and never
   revised after seeing the holdout results. There is no walk-forward
   optimization or independent statistical significance test yet.
6. The schema gate checks data quality but cannot **authenticate**
   the provenance of an uploaded file. Vendor license and completeness
   documentation remain necessary.

**A valid 3–5-year backtest has not happened just because the test
runner and its synthetic unit tests pass.** Report actual metrics
only after supplying genuine data and passing all quality checks.

## Most practical next step without buying another feed

In your **Tradovate Chrome account**, inspect the account menu for
**Go to Replay** and the account's Market Replay entitlement.
If it is enabled and includes 2021–2025 MNQ contracts, start by
testing a historical session inside the native indicator using the
correct expiration. This validates whether the indicator actually
works on your data, but is not yet an automated 5-year statistical
test. It may require a separate entitlement on a prop-firm account.

For a complete automated 5-year quantitative test, obtain an
authorized bulk export with **actual aggressor-labeled executed MNQ
trades** or an agreed equivalent provider schema. An alternative
dataset containing just minute OHLCV cannot validate delta/CVD/
absorption. I will not fabricate such results.
