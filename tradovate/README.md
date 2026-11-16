# Native Tradovate MNQ Setup Coach (Chrome)

This is the recommended integration for your current 25K prop-firm evaluation. It uses the live chart data your Tradovate browser is already receiving. You do not need to subscribe to Databento, manually enter indicators, share your screen, or type an API key.

**Implementation:** [MNQPayoutSetupCoach.js](MNQPayoutSetupCoach.js) is a native Tradovate JavaScript custom indicator (not an external Python broker integration). It accesses the chart's input bars through the supported methods: d.timestamp(), d.open(), d.high(), d.low(), d.close(), d.bidVolume(), d.offerVolume() and d.profile(). It requests volumeProfiles in the indicator definition.

The inputs come from the same market-data source your existing Tradovate indicators use. **The program does not scrape or directly subscribe to the output values of indicators already displayed on other charts.** It computes its own candidate logic inside Tradovate, using Tradovate chart data. The external Tradovate API is explicitly unavailable for evaluation/prop accounts, so no external Python connection is claimed.

## One-time installation in Tradovate Chrome

1. Open Tradovate Trader in Chrome and log in as usual.
2. Open the **Code Explorer** module from your Tradovate workspace, then select **File > New**.
3. Open [MNQPayoutSetupCoach.js](MNQPayoutSetupCoach.js) in GitHub and copy its entire raw file into the code editor.
4. Save it as **MNQPayoutSetupCoach**.
5. Open an **MNQ 1-minute chart**.
6. In the chart's Indicators panel, add **MNQ Setup Coach (Research Only)** (also searchable by its internal name MNQPayoutSetupCoach).
7. Ensure the chart has loaded the trading session's 1-minute bars since 9:30 a.m. New York time. Keep the Tradovate tab open while using it.

No data entry is required per candle or per trade to analyze the *market*. This code runs in Tradovate, not separately on the Chromebook Linux Terminal. Menu names may differ slightly by version. Eligibility for custom indicators can depend on your plan.

## What it outputs

In a separate indicator pane:

- +1 means **experimental LONG candidate**.
- -1 means **experimental SHORT candidate**.
- 0 means **no candidate with sufficient data**.
- No line means **no reliable data yet** (missing volume profiles, incomplete RTH history, skipped 1-minute bar, wrong product, or insufficient closed higher-timeframe context).

Signals are calculated after a completed 1-minute bar, never from the still-forming bar. The script combines historical 1-minute MNQ candles into 5m and 15m groups itself; it does not need you to select a separate 5m or 15m indicator. It evaluates:

- 1m OHLC/offer/bid volume; 5m aggregate delta; 15m closed-candle bias.
- RTH cumulative delta, resetting at 09:30 ET.
- 70% developing RTH volume-profile POC, VAH, VAL.
- A trade-print price-rejection proxy (not actual order-book iceberg absorption).
- Level proximity with adaptive tolerance and Mon–Thu 10:00–15:00 ET personal time window.

The initial candidate filter is **an unvalidated hypothesis**, not proof of positive expectancy. All rules are changeable in source, but adjusting them without out-of-sample testing risks overfitting.

## What is NOT connected

- The bot **does not** read your 25K evaluation account equity, floating P&L, open positions, actual current drawdown floor, or current daily loss.
- It does not mechanically enforce your $600 firm daily loss limit, $1,000 EOD max drawdown, or $1,500 profit target. Those remain governed by the firm dashboard.
- It does not place or modify orders.
- It is not connected to a standalone Python process, because the native Tradovate chart's internal data is not exposed as an authorized Python streaming API for evaluation accounts.
- True passive absorption/order-book reconstruction is **not possible** from only per-bar bid/ask volume and VAP.

**Technical checks passed only in a simulated indicator environment**, not yet on your own logged-in Tradovate Chrome. Before trusting the indicator, compare its displayed 1m/5m/15m candidates against your existing indicators in replay or a non-trading session.

## Official references

Tradovate native open-source indicator library:
https://github.com/tradovate/custom-indicators

Tradovate's own cumulative delta uses offerVolume minus bidVolume:
https://github.com/tradovate/custom-indicators/blob/master/builtin/cumulativeDelta.js

Documentation on volumeProfiles requirement and d.profile:
https://community.tradovate.com/t/creating-advanced-custom-indicators/3816

Official install instructions:
https://tradovate.zendesk.com/hc/en-us/articles/115011665727-How-do-I-use-custom-indicators-in-Tradovate

Official API access restriction for prop/evaluation accounts:
https://support.ninjatrader.com/s/article/Tradovate-API-Access?language=en_US
