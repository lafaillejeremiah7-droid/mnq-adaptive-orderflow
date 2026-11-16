# MNQ Payout Coach — Advisory CLI

This is a risk-first assistant, not a brokerage API, not autonomous trading, and not a verified path to profitability. It never places orders. **BLOCK** means reject the proposed position under configured guardrails; **REVIEW_ONLY** means risk checks passed but not that the setup is profitable.

## Run

Python 3.11+; no packages to install. Start from the project root.

1. Copy sample/payout_config_flex50k_example.json to account.json.
2. Edit account.json for the actual account firm, stage, limits and fees; the sample is **not a verification of your personal account rules**.
3. Run:
    
    python3 -m mnq_flow.payout_coach status

4. Record a closed trade after fees:
    
    python3 -m mnq_flow.payout_coach record --date 2026-11-12 --net 220 --setup poc_reclaim

5. Check an illustrative proposed trade (replace every figure with accurate broker data):

    python3 -m mnq_flow.payout_coach check --side long --entry 20100 --stop 20075 --contracts 2 --equity 50200 --floor 48800 --open-contracts 0 --broker-day-net 0 --broker-trades 0 --broker-losses 0 --snapshot snapshots.jsonl

The check requires a **fresh** 1m/5m/15m engine candidate snapshot no older than 3 minutes. To produce a real snapshot you must first supply valid MNQ **trade prints** to the research engine. A sample/demo snapshot is not evidence that a trade should be taken.

The risk gate includes:
- Monday–Thursday 10 a.m.–3 p.m. Eastern window.
- 1–2 trades/day and two-consecutive-loss personal stop.
- Stop distance × $2/point per MNQ contract, plus configurable fees/slippage.
- Personal daily and per-trade dollar limits and reserve above manually entered **current prop dashboard drawdown floor**.
- Reconciliation of journal and broker realized P&L / trade count.

A static floor cannot safely represent an EOD trailing drawdown. The program cannot know real broker equity, validate a stop fill, or automatically stop you from executing orders.

## First payout status

With stage = evaluation, status reports progress toward a user-configured target and consistency check. It cannot claim payout eligibility in evaluation.

With stage = funded, status counts distinct winning days and **provisionally** calculates maximum first-payout request as min(50% of recorded positive net P&L, payout cap), subject to 5 qualifying days and request minimum. It does **not** model subsequent payout resets, account reviews, processing deductions, fund drawdown recalculations, account-specific plan changes or provider interventions.

The example draws from AquaFutures published Flex payout terms for the 50K account: 5 qualifying days with $200 minimum net profit each; maximum 50% available profit requested capped at $2,000; minimum request $500; trader split 90%, before processing fees. Verify exact plan and current account agreement. Source: https://intercom.help/aquafutures-help-center/en/articles/16941660-payout-policy

The sample roundtrip fee and slippage inputs are examples, not broker quotations. The real account may be a different Flex variant with different evaluation rules.

Never commit account.json or personal trades.jsonl to this public repository; gitignore excludes them. This bot cannot watch the screen on a Chromebook or connect to Tradovate market data without an appropriate, licensed feed and integration.
