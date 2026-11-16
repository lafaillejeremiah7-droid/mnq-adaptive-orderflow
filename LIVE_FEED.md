# Automatic Live MNQ — No Per-Trade Data Entry

**New live path:** The bot can subscribe directly to one licensed CME Databento trades stream and automatically compute completed 1m/5m/15m profiles, value-area POC/VAH/VAL, buy/sell-initiated volume, delta, RTH cumulative delta and a trade-print rejection/absorption proxy. It shows a current experimental candidate in the browser UI, without asking you to type the indicator values.

**This is not yet activated:** the GitHub repository has no credentials or market-data entitlement to your feed. Tests use synthetic examples. To get *actual live MNQ prices*, the running Chromebook must connect to an authorized provider.

## Prerequisite: one-time licensed data access

- A Databento account with **licensed live CME Globex GLBX.MDP3 access** that includes MNQ trades; access can involve exchange and vendor fees. Verify entitlement and pricing **before subscribing**.
- The Python package **databento** and Python 3.11+ on your Linux Chromebook.
- An API key configured only in your **local environment**, never committed to GitHub, never pasted into a chat.
- Your existing Tradovate/NinjaTrader *chart subscription* is **not automatically** a Databento API entitlement. This implementation is an independent feed adapter.

Sources:
- Databento live client and trade subscription: https://databento.com/docs/quickstart/live
- Price encoding (fixed point, 1e-9) and side: https://databento.com/docs/schemas/trades
- Continuous futures symbol example and roll behavior: https://databento.com/docs/conventions/symbology

## Chromebook setup

From Linux Terminal:

    cd ~/mnq-adaptive-orderflow
    git pull --ff-only
    sudo apt install -y python3-venv
    python3 -m venv .venv
    .venv/bin/python -m pip install databento
    cp sample/evaluation_25k_example.json account.json

Do not overwrite your account.json if you already have real journal or risk settings without checking. The example reflects your submitted 25K evaluation screenshot ($1,500 target, $1,000 EOD trailing maximum loss, $600 firm daily loss limit, no consistency and 10 micros maximum). The personal risk limit is stricter: start with 1 MNQ, planned loss <= $50 and daily stop $100.

**In the first Terminal only:** enter the API key once without putting it into shell history:

    read -rsp "Databento API key: " DATABENTO_API_KEY; echo
    export DATABENTO_API_KEY

Start the real CME trade-print stream:

    .venv/bin/python -m mnq_flow.live_stream

It subscribes to **GLBX.MDP3 / trades / MNQ.v.0** (Databento's volume-leading continuous MNQ contract at subscription). It resolves to one actual contract instrument ID; if the mapping changes, signals stop rather than silently mixing expiries. Restart at contract rollover.

When started during 9:30–16:00 ET on a regular weekday, the client requests the day's RTH prints since 9:30 ET using Databento's supported intraday replay, then catches up to live. This avoids manual chart entry. The replay might incur data charges; confirm pricing. Outside RTH it streams but only evaluates the RTH strategy when trade prints arrive during the session.

For a quieter Terminal:

    .venv/bin/python -m mnq_flow.live_stream --signals-only

## See automatic live data in Chrome

Open a **second** Linux Terminal in the same folder and run:

    python3 -m mnq_flow.coach_ui

Then go to:

    http://127.0.0.1:8766

The "Automatic live MNQ feed" panel automatically refreshes every five seconds, showing the most recently completed 1m candle, 5m delta, 15m bias, RTH CVD, POC, VAH, VAL, absorption proxy, and an experimental setup indication. No per-trade typing is required **to read market data**. The manual risk section remains optional.

This dashboard is local to your Chromebook and will not receive new data if Linux is suspended or the live feed process stops.

## Key limitations: no false claims

- **No independent live test has run on your authorized CME feed.** GitHub CI tests verify record decoding, subscription adapter syntax, state updates, and simulated records, not a live provider connection.
- **Trade-print absorption proxy only.** Genuine order-book absorption / iceberg inference requires a licensed MBO/depth stream and a separately validated order-state model, which is not included.
- **Feed quality check:** unknown aggressor signs, out-of-order prints, data gaps, changed contract mappings, and stale data invalidate current candidates. The bot will show degraded/offline rather than represent unreliable signals as live.
- **Payout/risk awareness is not automatic:** the bot can read the *market*, not your prop-firm's drawdown floor, account equity, broker positions or actual fills. To combine signal + personal/broker risk in an automatic way, a separately authorized account integration is required. It never submits trades.
- **No guaranteed edge.** 15m bias, 5m delta and 1m absorption at profile levels are hypotheses. This algorithm has not been backtested, and vendor data correctness doesn't establish signal profitability.
- **Exchange hours:** current research core uses normal weekday RTH 9:30–16:00 ET and ignores exchange holidays and early closes. The actual CME market is broader than RTH, and this tool may not match platform-specific indicators.
- **Platform mismatch:** TradingView volume footprint calculations may use intrabar up/down rules and differ from CME aggressor-side prints. Likewise, the underlying bid/ask display in your chart might use a different feed.
- **Safety:** never publish CME market data, account secrets or private records in a public GitHub repo. Do not expose the local HTTP server outside 127.0.0.1.

## What remains to make it the assistant you described

The live data ingestion architecture exists. Next work is a licensed MBO adapter for genuine absorption, a sound backtest with trade costs and realistic fills, and account equity/drawdown synchronization **only if your particular prop firm permits and authorizes it**.

An alternative that avoids buying a second feed is building a NinjaTrader 8 *Windows desktop* C# add-on using OnMarketData() and OnMarketDepth(), if you actually use that platform and have an authorized feed. That approach does not run inside Chromebook Chrome directly. A TradingView Pine footprint alert pathway is also possible for eligible Premium/Ultimate subscribers, but an alert/webhook relay and the indicator's exact code are needed.
