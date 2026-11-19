# Solana paper trading desk

A small team of deterministic bots paper-trades BONK and WIF against USDC using Raydium quotes for Solana mainnet. The 30-day forward experiment begins with 1,000 simulated USDC. [Latest portfolio and P&L](https://github.com/lafaillejeremiah7-droid/mnq-adaptive-orderflow/blob/paper-results/report.json) · [Scheduled runs](https://github.com/lafaillejeremiah7-droid/mnq-adaptive-orderflow/actions/workflows/paper-trial.yml)

| Bot | Responsibility |
| --- | --- |
| Scout | Requests a 10 USDC buy quote and a reverse sell quote for the corresponding token quantity. Validates mint addresses, amounts, timestamps and route. |
| Signal | Looks for a 1% increase over a 45-minute price window in live mode. Records intent and waits for the next quote to simulate the fill. |
| Risk | Limits each entry to 10 USDC and one open position. A 5 USDC daily marked drawdown triggers an exit and pauses entries until the next UTC day. |
| Paper broker | Buys at the modeled ask, sells at the modeled bid, rounds to mint precision and caps fills at quoted size. Exits after a 3% adverse or 5% favorable move. Pending exits can fill in pieces. |
| Accountant | Records decisions, cash, fills and inventory atomically in SQLite. Reports net marked equity versus cash, completed round trips and maximum observed drawdown. |

## Forward trial

The hosted worker polls both pairs on a 15-second target cadence. New signals and exits are checked on every usable quote; the next quote for the same mint can fill an order. The live signal compares the current mid with an observation 45 minutes earlier (allowing up to one minute of reference age). A new live window warms up before opening a position. Old buy intents expire after 60 seconds. Existing stops, pending exits, cash and inventory carry across worker restarts.

GitHub Actions schedules overlapping 65-minute worker windows twice hourly. A concurrency lock permits only one writer. Runner startup, API errors and scheduling delays can cause gaps. Watch the active job log for quote timestamps, fills, position and net P&L. The public portfolio updates on fills, at worker handoff and approximately every five minutes. Archived batches in `paper-results/journal/` contain the observed bid/ask and paper decisions. An outage may delay an exit and increase losses. Failed quote requests leave the ledger unchanged. The workflow stores the forward ledger and report on the `paper-results` branch, separate from the application. After 30 days the report freezes at the last available liquidation mark. Use the Actions page to disable further scheduled checks. No wallet, signing key or transaction submission is used.

Both sides use the swap quote's minimum output at 30 bps slippage tolerance. The paper broker also charges 30 bps per side as an extra execution allowance. These assumptions approximate costs. Actual fees, latency, token behavior and fills can differ. HTTP freshness checks bound the age of the provider response; Raydium does not provide the underlying pool observation time in this response. USDC is the accounting unit. A gain in BONK or a synthetic test result alone does not establish a profitable strategy. Inspect the dates, closed trades, net return versus cash, and drawdown in the report. [Quote API](https://docs.raydium.io/api-reference/route-api-v2-endpoints/compute/compute-swap-quote-base-input.md)

## Run locally

Python 3.11+ and the standard library are sufficient.

```sh
python3 -m unittest discover -s tests -v
python3 company.py --config examples/paper.json --db demo.sqlite --replay < examples/quotes.jsonl
python3 live_paper.py --directory forward
```

The example is synthetic. The last command runs a local live paper loop until interrupted or the trial ends. Reuse the same directory to resume. The fixed mint pairs, parameters and run mode are bound to that ledger. Starting another trial requires a separate database. For another quote source, `company.py` consumes newline-delimited bid/ask quotes on standard input with UTC epoch seconds, token quantities and USDC prices. Quote arrival times must advance for each asset. Omit `--replay` for current quotes.

### Pump.fun live paper trial

The scanner requests up to 30 recent Solana Pump.fun launches and up to 30 recently active graduated tokens per minute. It follows up to three mints per group on a target 20-second polling cycle. Launches must be at most 15 minutes old when admitted. Each group starts with its own simulated 1,000 USDC and can hold one position of up to 10 USDC. The trial runs for 30 days. GitHub Actions scheduling and provider availability can leave gaps.

A 1% rise in the quoted midpoint over two minutes for a launch or ten minutes for a graduate creates a buy intent. The next fresh quote must arrive within 60 seconds with a spread of at most 5%. Jupiter must quote both directions through the mint’s listed Pump.fun bonding curve or its PumpSwap pool. Prices use minimum quoted output at 30 basis points of slippage per direction, plus a modeled 30 basis point fee per fill. A 3% stop, 5% target or 5 USDC daily loss triggers a sell intent. Its fill requires a subsequent quote for the position size. A launch position may exit through its verified graduated pool. Missing exits leave inventory open at its last mark. No wallet or signing key is used.

[Launch report](../../blob/pump-paper-results/launch/report.json) · [Graduated report](../../blob/pump-paper-results/graduated/report.json) · [Scan state and archived observations](../../tree/pump-paper-results)
