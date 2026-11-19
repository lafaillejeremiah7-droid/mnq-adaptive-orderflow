# MNQ opening-range breakout · rejected

One frozen breakout policy lost $1,646 after costs over 199 holdout trades. Staying flat returned $0. This is an offline price-only test of a proposed rule. The four forecasting policies and discretionary order-flow setups would require their own tests.

| Chronological segment | Eligible sessions | Trades | Gross P&L | Net P&L | Net per trade |
| --- | ---: | ---: | ---: | ---: | ---: |
| Development | 598 | 585 | $907.50 | −$1,140.00 | −$1.95 |
| Validation | 200 | 199 | $80.00 | −$616.50 | −$3.10 |
| Holdout, Oct 7 2024 through Oct 8 2025 | 200 | 199 | −$949.50 | −$1,646.00 | −$8.27 |
| All, Oct 12 2020 through Oct 8 2025 | 998 | 983 | $38.00 | −$3,402.50 | −$3.46 |

The policy buys the first close above the opening half-hour range or sells the first close below it. It enters at the next bar's open and takes at most one trade per session. Each modeled trade uses one MNQ, a 20-point stop and a 40-point target. Round-trip costs are assumed at $2.50 fees plus $1.00 slippage. Increasing slippage to $3.00 produces a $2,044 holdout loss. The holdout had 59 net winners. Its maximum session-close drawdown was $1,774.50. Account liquidation rules could have terminated the path earlier.

The one-sided block-bootstrap lower bound for holdout expectancy was −$15.40 per trade. The evaluator used three-session circular blocks, 3,999 draws, seed 247 and a 2.5% lower tail for each of two endpoints. The policy lost money even before costs on the holdout. This run supplies no basis for promotion. Reusing this holdout for rule selection would make it development data. [Frozen protocol](mnq-opening-range-protocol.txt) · [Numerical results](mnq-opening-range-results.json)

## Inputs and reproducibility

The input is a third-party public archive of contract-level GLBX.MDP3-format OHLCV minute bars. All 6,934 MNQ-folder CSVs matched the Git blob IDs at source revision `7ac6bd20d3fa46b25fa6d2db947200ef9860c6ef`. Of these, 5,387 are outright contract-day files and 1,547 are spreads. The uploader's folder is labeled “base de datos a corregir.” Exchange-level authenticity, corrections, as-published vintages and complete trading-calendar coverage have not been independently verified. Raw bars are outside this repository. [Pinned source tree](https://github.com/tdtrader76/NQ_Backtest/tree/7ac6bd20d3fa46b25fa6d2db947200ef9860c6ef)

The protocol was committed at `07b44bf` before scoring, as a retrospective study. The test selected contracts using opening-range volume, converted UTC to Eastern with daylight saving, skipped 7 observed weekdays with incomplete openings and 38 with incomplete selected sessions, and used every remaining eligible session. Dates entirely absent from the archive cannot be evaluated. Excluding incomplete sessions can bias the sample. The OHLC model assumes a next-open fill without manual latency, models adverse stop gaps and charges both-touch bars as stop-first. The account was unverified. No live position size follows from the simulation.

Using Python 3.11+ in this repository, point the runner at the extracted `datos brutos/base de datos a corregir/MNQ` directory of the pinned source.

```sh
python3 -m scripts.mnq_opening_range "/path/to/datos brutos/base de datos a corregir/MNQ"
python3 -m unittest discover -s tests_py -q
```
