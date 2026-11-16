# 25K Evaluation — MNQ Risk Coach

The values in this file were extracted from **the user's account-plan screenshot**, not from a broker account connection or a confirmed purchase. Do not confuse this evaluation with the older 50K Flex plan in other sample files.

## The plan shown

| Plan field | Screenshot value |
| --- | --- |
| Evaluation starting capital | $25,000 |
| Profit target | $1,500 |
| EOD trailing max drawdown | $1,000 |
| Daily loss limit | $600 |
| Consistency | None |
| Position limit | 1 mini / 10 micro contracts |
| One-time price displayed | $59 (marked down from $99) |
| Reset fee displayed | $60 (marked down from $70) |
| Activation fee displayed | None |

A $1,500 evaluation gain corresponds to 6% of the stated starting balance. With an initially static reference of $24,000 ($25,000 - $1,000), the **real EOD trailing floor may move upward**, so the bot requires the *current exact floor from the prop dashboard*, not a constant $24,000 value.

**Your immediate mission:** pass the evaluation under the account rules; only then work toward the funded-stage payout rules for this exact plan. No evaluation payout is assumed. Winning-day or withdrawal rules for the later funded account are not established by this screenshot.

## Personal trading rules (recommendations, not firm rules)

- Start with **one MNQ contract** while validating execution.
- Personal hard decision limit: **$50 planned risk per trade**, including configured round-trip costs and a slippage buffer.
- Stop for the day at **$100 of realized net losses**, or after two losing trades, whichever occurs first. This does not guarantee that an adverse fill cannot exceed a daily stop.
- Maximum **two attempted trades per day**, Monday–Thursday, 10:00–15:00 Eastern.
- Require **$150 of headroom above the broker-reported trailing drawdown floor** after accounting for planned trade loss.
- Never increase position size to try to pass in one day. Do not rely on revenge trades or martingale recovery.

For one MNQ, a 20-point stop corresponds to **$40 before fees**, since MNQ is $2 per index point. With illustrative $2.50 round-trip costs and a 2-tick ($1.00) slippage allowance, estimated planned risk is **$43.50**, within the $50 limit. Actual fees and adverse slippage can be higher. The sample fee/slippage numbers must be replaced with the broker's.

## Install/update the GitHub Python coach on Chromebook

If the repo is already cloned:

    cd ~/mnq-adaptive-orderflow
    git pull --ff-only

If not cloned:

    git clone https://github.com/lafaillejeremiah7-droid/mnq-adaptive-orderflow.git
    cd mnq-adaptive-orderflow

Copy the exact 25K example:

    cp sample/evaluation_25k_example.json account.json

Only do this if you are **setting up a new journal**. Do not overwrite your real account configuration blindly; compare it first. The file 'account.json' is gitignored and should remain local.

Check the currently recorded evaluation progress:

    python3 -m mnq_flow.payout_coach status

Record one closed trade, with net **realized P&L after all fees**:

    python3 -m mnq_flow.payout_coach record --date 2026-11-12 --net 50 --setup val_rejection

The status command reports the $1,500 profit target and **no consistency condition**. It always reports evaluation payout eligibility as false.

## Recommended: use the small local browser interface

Instead of repeatedly typing long commands, after copying the example to account.json run:

    python3 -m mnq_flow.coach_ui

Open http://127.0.0.1:8766 in Chrome. The page has three parts: evaluation progress, manual setup and risk review, and a closed-trade P&L journal. It does not use screen sharing, camera, OCR, charts, a cloud service or a broker API. It only receives information that you enter. It runs on the Linux environment bound to 127.0.0.1, and requires you to keep the Terminal running. Stop with Ctrl+C. It has not been tested on your exact Chromebook.

Enter **current broker equity, trailing floor, trade count and net daily P&L** correctly; incorrect manual inputs can invalidate the risk decision. The local journal must match the broker's daily trade count and realized P&L or the coach blocks new candidates. The browser UI has no authentication because it is explicitly loopback-only; do not expose the port to a network or port-forward it.

## Analyze a setup you can already see on your platform

Since you see value area, POC, delta, cumulative delta and absorption on your existing charts, you can supply your observations directly. No feed integration is needed for this manual check. Example only (NOT live market prices or a recommendation):

    python3 -m mnq_flow.manual_coach \
      --side long --bias up --level val --reaction rejection \
      --absorption bullish --delta-5m positive --cvd rising \
      --trigger-1m --entry 20100 --stop 20080 --contracts 1 \
      --equity 25000 --floor 24000 --open-contracts 0 \
      --broker-day-net 0 --broker-trades 0 --broker-losses 0

The output is **BLOCK** or **REVIEW_ONLY**. Review only means the manually described candidate and risk constraints agree; **it is not a trade signal with proven edge**. The initial strict checklist requires 15m alignment, level reaction, absorption, 5m delta, CVD and a 1m trigger. The actual performance of this hypothesis has not been tested. Reversal setups can involve delta divergence; the strict initial checklist may reject otherwise valid setups.

The firm daily max loss is an official ceiling; this bot uses a much stricter $100 *personal* daily stop. It includes the firm $600 cap in the risk-budget gate as a second boundary. The actual plan may compute daily limits including unrealized P&L or other platform-specific timing. Always obey the firm's live dashboard first.

## What this build cannot do yet

- **It does not see your TradingView or brokerage chart.** Manual market observations are trusted as supplied.
- **It does not connect to your account** for actual equity, trailing floor, open positions, winning days, or fills. You must verify and type those figures.
- **It cannot enforce a broker-level stop**, block you from clicking Buy/Sell, or guarantee an eventual $1,500 net profit.
- **It is not a backtested trading strategy**, and it has no proof of positive expectancy or profitable edge.
- The sample account model assumes MNQ only. One NQ mini equals 10 MNQ micros for the index exposure, but fees and exchange margin differ. A position-size limit must be respected across both contract types.
- Contract expiry, holidays, platform rule updates, daily resetting limits, and live fees must be checked separately.

The next milestone is a **local lightweight form/UI** so you can click your chart observations instead of typing a long command, and then collecting enough actual trade-journal data for a realistic drawdown-aware evaluation backtest.

Do not commit account numbers, broker credentials, private P&L journals, or copyrighted trade feeds into this public repository.
