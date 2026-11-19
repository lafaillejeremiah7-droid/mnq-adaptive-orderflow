# Morning VWAP reversal · rejected

The frozen strategy lost $1,460 before costs and $4,722 after modeled fees and slippage on 932 one-contract MNQ trades. Staying flat returned $0. Across the same 998 sessions the prior opening-range breakout lost $3,402.50. Both strategies failed the positive net expectancy criterion.

| Reused chronological segment | Trades | Net P&L | Net per trade |
| --- | ---: | ---: | ---: |
| Early | 558 | −$3,225.00 | −$5.78 |
| Middle | 190 | −$681.50 | −$3.59 |
| Latest | 184 | −$815.50 | −$4.43 |
| All | 932 | −$4,722.00 | −$5.07 |

This study used the same pinned October 2020–October 2025 outright minute-bar archive, completeness filters and opening-volume contract selection as the first study. The prior research exposed all three segments. No independently sourced, compatible later sample was obtained. These results are exploratory. [Data provenance and filtering](mnq-opening-range.md)

At 10:00–12:59 Eastern, the strategy looked for a price at least 20 points from the previous minute's session VWAP estimate to cross back inside that band. It aimed for the frozen VWAP with a 15-point stop. VWAP uses bar typical prices weighted by volume. Next-open conditional fills assume sufficient liquidity and negligible decision latency. Simulated costs were $3.50 per round trip. At $5.50, the loss reached $6,586. Maximum session-close drawdown at base costs was $4,822. Account rules could have stopped the path sooner.

The per-trade expectancy lower bound was −$7.30 using three-session blocks, 3,999 draws and a one-sided tail probability of 1.25% for two policies and two endpoints. A lower bound below zero does not by itself prove a negative edge. The realized simulated mean was negative in every segment. No parameters were revised after scoring. [Frozen protocol](mnq-vwap-reversion-protocol.md) · [Results](mnq-vwap-reversion-results.json)

Reproduce with `python3 -m scripts.mnq_vwap_reversion "/path/to/datos brutos/base de datos a corregir/MNQ"` from the repository root using the archive revision specified in the first study.
