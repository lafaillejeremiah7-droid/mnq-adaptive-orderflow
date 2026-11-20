# Nasdaq futures research shortlist and Kelly sizing

The 100 IDs in [selection order](locked-ids.txt) were chosen from the [original catalog](ideas.csv) using three chronological selection blocks. The screen used 530 intraday variants. Of these, 430 were removed: 8 lacked usable selection coverage or enough triggered decisions, 24 exceeded the four-per-feature cap and 398 ranked below the cutoff. Another 470 were outside the measurable scope of this pass. This is prioritization of future research. None of the 100 demonstrated a statistically reliable advantage over the paired baseline in the later comparison. [Prespecified protocol](protocol.md) · [Scores and reasons for all 1,000](screen.json)

## Which market did the data measure?

- **NQ, E-mini futures.** The CFTC's futures-only Traders in Financial Futures dataset identifies NASDAQ MINI as market 209742. Across 261 weekly position snapshots from October 13, 2020 to October 7, 2025, median open interest was 255,587 contracts. Leveraged-money net contracts divided by open interest had 10th, 50th and 90th percentiles of −20.38%, −12.49% and −2.53%. Spreads and portfolio hedges complicate directional interpretation. Weekly data have a reporting lag and cannot resolve a minute-level entry. These figures describe the NQ market and were excluded from ranking. [CFTC observations](nq-positioning.csv) · [CFTC source](https://publicreporting.cftc.gov/resource/gpe5-46if.json?cftc_contract_market_code=209742)
- **NDX, underlying price index.** From Oct 12, 2020 to Oct 8, 2025, 1,254 daily close-to-close log returns had 23.00% annualized sample volatility (252-day convention). Median absolute daily log return was 0.78%, and the 90th percentile was 2.33%. These magnitudes explain why a fixed distance in points can mean different things over time. Daily index closes cannot validate an intraday futures fill. [Nasdaq closes via FRED](https://fred.stlouisfed.org/series/NASDAQ100)
- **MNQ, execution study.** The actual simulation uses contract-specific one-minute OHLCV on one Micro E-mini at $2 per point. The full-priced NQ multiplier is $20. Queue sizes, spread costs and fill probabilities can differ by instrument. Historical research found that the E-mini played a major role in Nasdaq-100 price discovery during its sample, which motivates collecting synchronized NQ and MNQ quotes for future cross-market tests. It does not supply the missing quotes. [CME NQ](https://www.cmegroup.com/markets/equities/nasdaq/e-mini-nasdaq-100.contractSpecs.html) · [CME MNQ](https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.settlements.html) · [Hasbrouck, 2003](https://onlinelibrary.wiley.com/doi/10.1046/j.1540-6261.2003.00609.x) · [Archive and known limits](../backtests/mnq-opening-range.md)

## The mathematics of the screen

Expectancy in dollars per original eligible session counts skipped trades at zero. The paired improvement is the candidate's net P&L minus the baseline's on the same sessions with available features. This denominator penalizes filters that avoid winning trades. At $1 fees plus one tick of slippage per side, total modeled costs are $2 per round trip. At two ticks per side they are $3.

The original 50/50 baseline earned $278.50 gross across 923 trades and lost $1,567.50 after $2 round-trip costs. To respect the $100 planned-risk preference we capped the stop at 48 points in the screened candidates and their comparison baseline. A full stop costs $98 at base costs and $99 at stressed costs, before any additional adverse gap. This overlay also changes the trade outcomes. The 48/50 baseline lost $1,958 over all 923 entries. The account's actual floor and remaining room were unavailable.

Fit feature percentiles using earlier signals only. Score selection blocks of 200, 198 and 200 sessions after a 200-session warmup. Rank by the median of the three stressed improvements per comparable session. Freeze IDs and evaluate on the final 200 sessions. The comparable baseline gained $207.50 on 192 trades in that window. Of 100 candidates, 52 earned positive net P&L at $2 cost, 41 at $3 cost, and 35 beat their matched baseline at $2. Median candidate net was $10.75 in total. No candidate's simultaneous one-sided lower bound on paired improvement was above zero. The shared moving-block bootstrap preserves local session dependence and correlations between candidates. Its five-session block length and the historical reuse of this period limit the inference. Related variants are not independent replications. [Multiple testing and trading rules, Sullivan, Timmermann and White](https://onlinelibrary.wiley.com/doi/10.1111/0022-1082.00163)

The highest selection score belonged to MNQ-0364. Measure distance from the current close back to the session's most favorable price in the proposed direction, divided by opening-range width. Above the training 75th percentile, reverse the usual trade direction. In the final period this earned $52.50 net on 192 trades, $155 behind the baseline. A rule can finish profitable and still add no measured value to the simpler strategy.

### Five quantitative questions the data can answer

| Question | Mathematical quantity | How it applies here |
|---|---|---|
| How much does an event pay? | Expected net payoff = win probability × mean win − loss probability × mean absolute loss, using net outcomes. | Use separate empirical win and loss magnitudes. On the original setup, 463 of 923 trades won after $2 costs, yet average net payoff was negative. |
| What does a point mean across market regimes? | Relative range = opening range / opening price. Realized volatility over a window = square root of the sum of squared log returns. | Normalize distances using information available at decision time. A fixed 50-point target has different reachability at different index levels and volatility. |
| Did a change add information? | Paired difference per session and its uncertainty relative to the same-entry baseline. | Keep losing and skipped opportunities in the comparison. Duplicating a nearby threshold creates another test, not a new independent sample. |
| Can the account survive the path? | Running peak minus current marked equity; maximum of these gaps measures drawdown. | The workbook measures session-close drawdown. Intratrade equity marks, rule thresholds and pending risk are needed to test actual account survival. |
| How much can be reinvested? | Expected log growth, conditional on a specified joint distribution of payoffs and costs. | Estimate long-only Kelly after testing the edge. Compare growth when the estimate is perturbed or transferred to a later period. |

## Kelly criterion

**The question Kelly answers.** Given a recurring opportunity, a payoff distribution, and the ability to reinvest and resize continuously, what fraction of bankroll maximizes expected logarithmic growth? For a two-outcome bet risking one unit to win b units with probability p, full Kelly is f = p − (1−p)/b. For a 55% chance at even money this gives 10%. Half Kelly gives 5%. A misspecified win probability, transaction costs or dependence between trades can overwhelm the calculation. [Kelly's original 1956 paper](https://doi.org/10.1002/j.1538-7305.1956.tb03809.x) · [Thorp on practical applications](https://www.sciencedirect.com/science/article/pii/B9780444532480500150)

**Actual MNQ payoffs.** Of the 923 original trades, 427 exited on time. We use every realized net payoff. Let R equal the one-contract net payoff divided by the planned dollar loss for its bracket. Maximize the sample average of log(1+fR) over 0 ≤ f ≤ 1 with positive wealth at every observed outcome. Its derivative at zero is the sample mean R. A nonpositive mean implies zero long-only Kelly because the objective is concave. A positive sample mean does not establish a positive population mean. [Calculation and inputs](kelly.json)

| Model at $2 round-trip costs | Prior sample | Later 192 trades | Interpretation |
|---|---|---|---|
| Original 50/50 | 731 trades, estimated Kelly 0% | +$146, retrospective Kelly 1.14% | Full-sample mean −$1.70 per trade and Kelly 0%. A later fitted value was unavailable beforehand. |
| 48/50 baseline | 731 trades, estimated Kelly 0% | +$207.50, retrospective Kelly 1.60% | Full-sample Kelly is also 0%. |
| MNQ-0364, selected first | 553 selection trades, +$2,113.50, estimated Kelly 5.77% | +$52.50, retrospective Kelly 0.40% | Applying the earlier full, half or quarter fraction to later payoffs produced negative average log growth in all three cases. |

The third row illustrates *selection bias and volatility drag*. This candidate was chosen from hundreds of rules. Feeding its selection-period edge into a sizing optimizer reuses that optimistic estimate. Arithmetic dollar P&L can be positive while compounded growth is negative at an excessive fraction. The experiment assumes fractional continuous positions for illustration, holds the estimated fraction fixed during the audit and omits margin and firm payout rules. It cannot be used as a funded-account size instruction.

**Drawdown and integer size.** Standard Kelly optimizes a long-run objective. Tradeify can fail an account when marked equity touches its floor, including intratrade. Those are different objectives. Before translating any estimate into contracts, use the verified account equity, actual remaining daily and trailing loss capacity, existing open and pending risk, stressed per-contract loss and the trader's ceiling. If the allowed downside is below one contract's stressed loss, the feasible size is zero. The nominal $25,000 account label alone gives no sizing answer. Drawdown-constrained Kelly explicitly adds a wealth-floor probability condition, but its guarantee relies on the stated model and a specified floor; the funded firm's trailing floor needs its own pathwise simulation. [Busseti, Ryu and Boyd](https://web.stanford.edu/~boyd/papers/pdf/kelly.pdf) · [Tradeify drawdown rules](https://help.tradeify.co/en/articles/10495897-rules-trailing-max-drawdowns)

## Reproduction

From the repository root, with NumPy and the pinned MNQ archive:

```sh
python -m scripts.mnq_shortlist PATH_TO_DATED_MNQ_CSVS docs/shortlist
python -m scripts.mnq_kelly_review PATH_TO_DATED_MNQ_CSVS > docs/shortlist/kelly.json
```

Use the 100 retained IDs as a candidate pool. A stronger test would freeze a small number of distinct hypotheses, then score later, independently collected contract-specific sessions under the same fee and slippage assumptions.
