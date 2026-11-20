# NQ research projects

[Institutional research and independent review](institutional-research.md) connects the nine named organizations to concrete tests for this repository. Run the following from the repo root with Python 3. The original mandate uses POC, VAH, VAL and absorption. Its text gives no expansion for AOC. The auction project implements one of the hypotheses actually described there.

| Project | Input and output |
|---|---|
| Constituent DCF | Two-stage equity valuation using historical Microsoft financials and explicit scenario assumptions. A constituent produces cash flows. An NQ futures contract derives its price from the index and carry. |
| Futures basis | Theoretical price equals spot times exp((financing rate minus dividend yield) times days/365). Inputs are continuously compounded annual rates and synchronized spot/futures observations for the named expiry. The fixture illustrates sensitivity to carry. Costs, discrete dividends and execution can change the result. |
| Failed auction | Classifies one completed minute with a frozen prior profile from the same outright. Requires a break of exactly one value-area boundary, a close strictly inside and net aggressive buying above VAH or selling below VAL. Its output is an observation for subsequent research. |
| CFTC positioning | Reports category longs minus shorts, in contracts and as a percentage of open interest, for the E-mini-specific futures-only market code 209742. The fixture excludes MNQ and the consolidated series. |
| Forecast calibration | Tests whether the previous observed NDX close direction improves a probability forecast for the next close. The baseline uses the pooled historical up frequency. Both receive the same add-one smoothing. Outcomes update the estimates only after prediction. Annual groups report natural calendar periods under continuous expanding estimation. |

```sh
python3 -m projects.nq.models dcf projects/nq/msft-fy2025.json
python3 -m projects.nq.models basis projects/nq/illustrative-basis.json
python3 -m projects.nq.models auction projects/nq/illustrative-auction.json
python3 -m projects.nq.models positioning projects/nq/nq-cftc.csv
curl -fsSL 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQ100&cosd=1985-01-01&coed=2026-11-18' -o /tmp/ndx-closes.csv
python3 -m projects.nq.models calibration /tmp/ndx-closes.csv
```

### Worked results

**Microsoft.** FY2025 reported operating cash of $136,162M less $64,551M of cash capex and $8,962M of net debt repayment gives an equity cash-flow proxy of $62,649M. Net borrowing combines $5,746M net short-term repayment and $3,216M other repayment. We use 7,434M year-end outstanding shares. Five assumed growth rates of 10%, 10%, 8%, 6% and 4%, followed by 3% perpetual growth, give $177.21 per share at a 9% cost of equity. At 8% and 10%, values are $213.12 and $151.56. Terminal value contributes 76.44% in the central scenario. This simplified model holds shares fixed and omits future dilution and separate adjustments for nonoperating assets. It values one company under stated assumptions. An index valuation additionally needs point-in-time constituents, weights and prices. [Microsoft FY2025 annual report](https://www.microsoft.com/investor/reports/ar25/index.html) · [SEC filing](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm)

**NQ positioning.** Six weekly CFTC observations run from October 6 to November 10, 2026. On November 10, asset managers were net long 72,785 contracts (25.21% of open interest). Leveraged funds were net long 13,967 (4.84%). A position is a stock, and its business purpose can include hedging. For source reproduction, select market code 209742 from the Traders in Financial Futures futures-only dataset, and use the long and short columns for the asset-manager and leveraged-money categories. Report dates describe positions as of Tuesday. A point-in-time signal needs actual release dates, especially around holidays. [CFTC source data](https://publicreporting.cftc.gov/resource/gpe5-46if.json?cftc_contract_market_code=209742) · [CFTC reports and schedules](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm)

**Forecasts.** The FRED input began January 2, 1986 and ended November 18, 2026. Original CSV SHA-256 was `55c41cad0f2e18a6727ad305ae4a9ee20bb5d23fd45fa3ec022ee15efdc47fea`. Missing observations are skipped. Unchanged closes count as a non-up outcome and a separate predictor state. After 252 training labels the models scored 10,048 subsequent observations. Brier score was 0.248291 for the directional model and 0.248028 for the expanding base rate. The 60–70% bin contained 1,227 forecasts, averaging 61.25% predicted and 59.58% observed. This retrospective study uses the downloaded data vintage and descriptive scores. No significance or futures profitability claim follows. [Nasdaq data via FRED](https://fred.stlouisfed.org/series/NASDAQ100)

**Illustrative inputs.** With spot 27,000, 30 days remaining, 4% financing and a 0.6% dividend yield, theoretical NQ is 27,075.56. A quote of 27,080 is 4.44 points above that model. The signed-print fixture yields a failed high and +10 contracts of net buying outside value. The data provider must establish completeness and aggressor identity. Profile boundaries are supplied inputs and can be calculated by the existing OCaml volume profile. A print cannot establish hidden liquidity or passive replenishment. Neither example is a historical fill. [Volume profile implementation](../../lib/profile.ml)
