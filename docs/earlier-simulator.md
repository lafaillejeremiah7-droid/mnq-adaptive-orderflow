# MNQ quant researcher

An AI researcher for Micro E-mini Nasdaq-100 futures, a separate reviewer, and a reproducible one-minute trade simulator. Start with one question. The included study shows the researcher rejecting an MNQ signal when fill ordering determines the sign of its return.

## What institutional researchers do, applied to MNQ

| Publicly documented work | How the researcher applies it here |
| --- | --- |
| Citadel’s equity researchers study forecasts, market impact and portfolio construction. Two Sigma describes combining forecasts with risks and trading costs to choose positions. | Specify whether the prediction concerns direction, volatility or execution. For an outright signal, compare incremental net dollars with holding zero contracts. For a hedge, compare residual portfolio risk with the unhedged book. [Citadel EQR](https://www.citadel.com/careers/career-perspectives/inside-eqr-what-it-means-quantitative-researcher/) · [Two Sigma](https://www.twosigma.com/businesses/investment-management/) |
| Bank desk researchers build valuation, hedging and risk models. Electronic trading strategists improve how client orders are executed. | A desk with Nasdaq equity exposure might study how many micro contracts offset its beta, the mismatch between portfolio and index returns, the margin cash needed and the cost of rebalancing. An execution researcher would compare MNQ fills with quotes observable at the decision time. Those are separate research questions. [JPMorganChase](https://www.jpmorganchase.com/careers/explore-opportunities/programs/quant-fin-programs) · [Goldman Sachs](https://www.goldmansachs.com/careers/blog/meet-our-people-erin-r) |
| U.S. banking guidance describes objective challenge by qualified reviewers with sufficient independence. AQR researchers used actual institutional executions to estimate trading costs. | Give a second session the frozen inputs, simulator and result. Check units, missing bars, exposure, time ordering, ambiguity and cost sensitivity. Better execution claims require quote, order or fill evidence. [Federal Reserve](https://www.federalreserve.gov/frrs/guidance/supervisory-guidance-on-model-risk-management.htm) · [AQR](https://www.aqr.com/insights/research/working-paper/trading-costs) |

These sources describe broad institutional work. Public information does not establish a particular firm’s proprietary MNQ signal, staffing or execution policy. The hedge and trading examples above are our adaptations. CME sets the MNQ multiplier at $2 per index point. The 0.25-point outright tick is $0.50 per contract. NQ’s dollar multiplier is ten times as large. The two contracts have separate order books. [CME specifications and FAQ](https://www.cmegroup.com/articles/faqs/frequently-asked-questions-micro-e-mini-equity-index-futures.html)

## Use the researcher

With an authenticated Codex CLI and a POSIX machine with Python 3.11 or later, start the lead and review sessions separately. Each model session uses your configured account. The deterministic commands below only need the Python standard library.

```sh
python researcher.py researcher "Design one MNQ experiment on unused dates. Inspect the existing ledger first."
python researcher.py reviewer "Audit experiments/mnqh5-202502-impulse and identify the strongest reason to reject it."
```

The same profiles are in `.github/agents/` for compatible GitHub Copilot clients. The local reviewer launches in a read-only sandbox. Provide locally accessible data for an independent replay. The operator records the returned review with `python quantlab.py review ID review-input.json`. Its four fields are reviewer, verdict, findings and result_sha256. A role name or digest alone cannot authenticate an independent reviewer. The supplied historical trial has a same-author rejection, labeled in its record.

## First MNQ experiment

The researcher tested whether a completed one-minute price move of at least five points continues into the next minute. Buy the next open after an up move, sell after a down move. Simulate one contract, a five-point stop, a five-point target, and exit at that minute’s close if neither is reached. Costs are $1 round trip plus one tick on each side, or $2 per trade in total. These are assumptions. The calendar window, rule, costs and rejection criteria were committed before running this implementation. The underlying archive had been studied previously.

| February 2025, MNQH5 | Result |
| --- | ---: |
| Observed one-minute bars / trading dates | 7,620 / 20 |
| Simulated trades / ambiguous exits | 3,530 / 954 |
| Gross P&L under stop-first convention | −$8,828 |
| Fees and simulated slippage | $7,060 |
| Net P&L / flat-cash benchmark | −$15,888 / $0 |
| Maximum closed-trade drawdown | $15,888 |
| Net with one additional tick of slippage per side | −$19,418 |
| Net assigning every ambiguous exit to the target first | +$3,192 |

The registered trade count minimum was 30, the minimum net was one cent and the drawdown budget was $500. These are evaluation criteria, so the simulator continues after a threshold is breached. It measures the unconstrained rule. The two extreme fill conventions straddle zero. The actual sequence requires finer data, and even a recorded print does not guarantee an executable fill. The verdict is **reject**.

The simulator uses UTC start-stamped bars, half-open windows, immediately adjacent minutes, a single outright contract, integer price ticks and integer cents. It can enter at the open of the next minute following an exit at the preceding close. Execution models a fixed cost per side and stop/target touches on observed OHLC. It assumes availability at the next open and has no queue, latency, margin, gap-through-stop or intrabar equity model. The input preparer selects observed weekday bars from 09:30 to before 16:00 New York time including partial sessions. It provides no independent attestation of exchange-calendar coverage, missing prints or archive corrections. Number of trades is not a count of independent observations.

## Reproduce the published study

Use the pinned third-party source checkout. The preparation script takes the checkout directory as its first argument. It creates a new CSV and refuses to overwrite an existing one. The repo stores the input hash, protocol, result digest, summary and disposition. A successful audit rebuilds the local trade ledger. [Pinned data source](https://github.com/tdtrader76/NQ_Backtest/tree/7ac6bd20d3fa46b25fa6d2db947200ef9860c6ef)

```sh
python examples/prepare_mnq.py /path/to/pinned/NQ_Backtest /tmp/mnqh5-feb.csv
python audit.py verify mnqh5-202502-impulse /tmp/mnqh5-feb.csv
python quantlab.py replay mnqh5-202502-impulse /tmp/mnqh5-feb.csv
```

## Start a new trial

Use a fresh directory for this synthetic tutorial. For shared research use the default tracked experiments directory, synchronize it first, then commit each protocol before evaluation. Merge experiment records before parallel branches evaluate related data. Publish the receipt and preserve locally reconstructable inputs under their data license.

```sh
python quantlab.py --ledger /tmp/mnq-tutorial register examples/protocol.json
python quantlab.py --ledger /tmp/mnq-tutorial run fixture-001 examples/bars.csv
python audit.py --ledger /tmp/mnq-tutorial publish fixture-001
python quantlab.py --ledger /tmp/mnq-tutorial replay fixture-001 examples/bars.csv
python -m unittest discover -s tests -v
```

Registration freezes the exact simulator and dataset hashes. Attempts reserve overlapping windows for the same contract spelling within that ledger, including failed runs. The local file lock protects one checkout. Other branches, alternate symbol spellings, other instruments and previously downloaded files can contain overlapping information. Git history and a local journal provide provenance within this workflow. Strong independent holdouts require separate data custody and controlled access.

The built-in engine supports one-minute impulse continuation or reversal with a single-bar holding period. The researcher can design different experiments, including hedge quality or volatility forecasting. Each new experiment family requires its own validated evaluator. The repository contains no broker integration.
