# Solana paper trading desk

A small team of deterministic bots paper-trades BONK and WIF against USDC using Raydium quotes for Solana mainnet. The 30-day forward experiment begins with 1,000 simulated USDC. [Latest portfolio and P&L](https://github.com/lafaillejeremiah7-droid/mnq-adaptive-orderflow/blob/paper-results/report.json) · [Scheduled runs](https://github.com/lafaillejeremiah7-droid/mnq-adaptive-orderflow/actions/workflows/paper-trial.yml)

| Bot | Responsibility |
| --- | --- |
| Scout | Requests a 10 USDC buy quote and a reverse sell quote for the corresponding token quantity. Validates mint addresses, amounts, timestamps and route. |
| Signal | Looks for a 1% increase over the previous three observations. Records intent and waits for the next quote to simulate the fill. |
| Risk | Limits each entry to 10 USDC and one open position. A 5 USDC daily marked drawdown triggers an exit and pauses entries until the next UTC day. |
| Paper broker | Buys at the modeled ask, sells at the modeled bid, rounds to mint precision and caps fills at quoted size. Exits after a 3% adverse or 5% favorable move. Pending exits can fill in pieces. |
| Accountant | Records decisions, cash, fills and inventory atomically in SQLite. Reports net marked equity versus cash, completed round trips and maximum observed drawdown. |

## Forward trial

The workflow requests one observation about every 15 minutes. GitHub can delay or drop scheduled jobs. Gaps over an hour reset the signal window and expire pending entries. An outage may delay an exit and increase losses. Failed quote requests leave the ledger unchanged. The workflow stores the forward ledger and report on the `paper-results` branch, separate from the application. After 30 days the report freezes at the last available liquidation mark. Use the Actions page to disable further scheduled checks. No wallet, signing key or transaction submission is used.

Both sides use the swap quote's minimum output at 30 bps slippage tolerance. The paper broker also charges 30 bps per side as an extra execution allowance. These assumptions approximate costs. Actual fees, latency, token behavior and fills can differ. HTTP freshness checks bound the age of the provider response; Raydium does not provide the underlying pool observation time in this response. USDC is the accounting unit. A gain in BONK or a synthetic test result alone does not establish a profitable strategy. Inspect the dates, closed trades, net return versus cash, and drawdown in the report. [Quote API](https://docs.raydium.io/api-reference/route-api-v2-endpoints/compute/compute-swap-quote-base-input.md)

## Run locally

Python 3.11+ and the standard library are sufficient.

```sh
python3 -m unittest discover -s tests -v
python3 company.py --config examples/paper.json --db demo.sqlite --replay < examples/quotes.jsonl
python3 solana_paper.py --db forward.sqlite
```

The example is synthetic. The last command advances a separate forward ledger by one observation. Reuse the same ledger on later invocations. The fixed mint pairs, parameters and run mode are bound to that ledger. Starting another trial requires a separate database. For another quote source, `company.py` consumes newline-delimited bid/ask quotes on standard input with UTC epoch seconds, token quantities and USDC prices. Quote arrival times must advance for each asset. Omit `--replay` for current quotes.
