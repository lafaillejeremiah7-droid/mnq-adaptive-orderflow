# Adaptive MNQ failed-break policy · rejected at validation

The signal fades a failed break of the first half-hour's high or low. At each proposal the same-contract baseline, regime, recency, and regime-plus-recency workers estimate the chance of reaching the target before the stop. The regime is computed from the latest 20 completed price changes. The recency workers discount older resolved outcomes. Each quarter's new outright must earn its own sample. All four estimates update from observed hypothetical setups even on days when the policy abstains. Their equal-weight mean controls participation. Risk per simulated trade stays fixed.

| Validation, Oct 4 2023–Oct 3 2024 | Trades | Net at $3.50 round trip | Net at $5.50 round trip |
| --- | ---: | ---: | ---: |
| Four-worker adaptive policy | 17 | −$227.50 | −$261.50 |
| Baseline agent | 18 | −$255.00 | −$291.00 |
| Every failed break | 187 | −$746.50 | −$1,120.50 |
| Remain flat | 0 | $0 | $0 |

Of 187 proposals, 108 had enough prior same-side history. The regime classifier called 99 of these range and nine trending. Compared with the baseline agent, the ensemble skipped one additional losing trade and added none. This explains the $29.50 stressed improvement over baseline. The evidence for adaptation is weak. The ensemble's development results were also negative, at −$284 over 102 trades under base costs.

The specification was committed before scoring. The update law, lookbacks, stop, target, costs, probability threshold and stopping rule were fixed. The adaptive policy missed both the 30-trade minimum and the positive stressed P&L requirement. The experiment stopped before this policy was scored on the latest 200 sessions or any new sample. The development and validation dates had already been used for earlier policies. This is a retrospective rejection. Inferring future success would require independent forward evidence. The three price regimes and recent outcomes cannot capture every change in liquidity, volatility or execution quality.

The simulator uses one MNQ, next-open hypothetical fills, a 12-point stop and 18-point target with a 30-minute time exit. Full-session completeness filtering can introduce selection bias. Account failure thresholds and actual manual fills were unavailable. See the [frozen protocol](mnq-adaptive-failed-break-protocol.md), [numerical results](mnq-adaptive-failed-break-results.json) and [source archive and execution assumptions](mnq-opening-range.md).

To reproduce, run `python3 -m scripts.mnq_adaptive_failed_break "/path/to/datos brutos/base de datos a corregir/MNQ"` from the repository root.
