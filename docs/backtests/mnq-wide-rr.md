# Wider reward and risk distances on MNQ

## Protocol frozen before scoring

Use one MNQ and the exact unfiltered reversed failed-break entries from the previous exit study. Freeze the 09:30–09:59 Eastern range on Monday–Thursday. The first 10:00–14:28 minute that trades outside exactly one edge and closes strictly inside triggers entry at the next open. Buy a failed high and sell a failed low. Use the existing 30-minute exit, adverse gap and same-minute stop-first assumptions. Deduct $3.50 per round trip, then stress at $5.50. The price-only study measures hypothetical fills.

Enumerate every whole-point short distance from 25 through 50 crossed with every whole-point long distance from 50 through 100. First place the shorter distance at the target and the longer at the stop. Then swap legs. Include the shared 50/50 case once. The 2,651 unique pairs include the requested 50/25, 75/35, 100/50 (TP/SL) and their mirrors. Rank each unequal group by stressed net P&L, breaking ties by smaller stop and then smaller target. Score the same Oct 4, 2023–Oct 3, 2024 sessions as the previous sweep. Verify 200 eligible sessions, 187 trades and the old 18/12 control's −$778 base net.

Replay the six named pairs plus the single ranked leader from each unequal group on Oct 7, 2024–Oct 8, 2025, irrespective of selection-window performance. Record the selected pairs before processing that window. It has been seen in related studies. Comparing thousands of strongly correlated exits can produce incidental winners. Treat all results as descriptive and leave any promotion decision to a fresh prospective test. Evaluate every requested distance for comparison even when the modeled loss exceeds the trader's account-risk ceiling. Use the original [archive and eligibility rules](mnq-opening-range.md).

## Results for one MNQ

Both windows contained 200 eligible sessions. There were 187 entries in the first and 192 in the later window. Figures below are dollars after the stated round-trip cost. Drawdown is measured on session closes at base costs. Intraday drawdown can be larger.

| Target | Stop | First window, $3.50 | Later window, $3.50 | Later window, $5.50 | Later net wins | Later max drawdown |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 50 | 486.50 | −25.50 | −409.50 | 126 | 1,183.50 |
| 35 | 75 | 675.00 | 612.00 | 228.00 | 125 | 1,035.50 |
| 50 | 100 | 1,176.00 | 34.00 | −350.00 | 112 | 1,444.00 |
| 50 | 25 | 244.50 | −321.50 | −705.50 | 77 | 900.00 |
| 75 | 35 | 951.50 | −182.00 | −566.00 | 84 | 809.50 |
| 100 | 50 | 790.50 | −1,117.50 | −1,501.50 | 90 | 1,655.00 |
| 47 | 91 | 1,339.50 | 46.50 | −337.50 | 113 | 1,373.50 |
| 64 | 50 | 1,538.50 | −633.50 | −1,017.50 | 95 | 1,410.00 |

The last two rows are the selected leaders. Across all 1,325 smaller-target variants, 1,319 finished positive under stressed costs in the first window. Of the 1,325 larger-target variants, 995 did so. The equal-distance 50/50 control earned $695 under stress in that window. Nearby settings share most of the same trades. Counting positive settings cannot substitute for independent evidence.

In the later window, 35 target / 75 stop earned $1.19 per trade under stress and had a $1,035.50 session-close drawdown at base costs. A 75-point stop on one MNQ risks $150 before costs or adverse gaps. This exceeds the trader's stated $100 ceiling even if the statistical result holds. For 100 target / 50 stop, only 13 later trades hit the target, 66 hit the stop and 113 exited on time. Nominal reward/risk therefore does not determine realized payoffs. Account failure was not simulated.

Reproduce with `python3 -m scripts.mnq_wide_rr PATH_TO_MNQ_CSV_DIRECTORY results.csv`. [Full grid and later comparisons](mnq-wide-rr-results.csv)
