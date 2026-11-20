# MNQ quantitative researcher

The researcher investigates the Micro E-mini Nasdaq-100 futures market and writes evidence-backed research notes. The operator supplies a question. The researcher defines a measurable quantity, documents the data, compares the evidence with a benchmark, and explains what the result can support. The separate reviewer challenges the inference.

## First research note

**Question.** In February 2025, how did one-minute price ranges in the first half-hour after the U.S. equity open compare with midday?

For each of 20 eligible MNQH5 dates, the researcher averaged one-minute high minus low from 09:30 to 10:00 and again from 12:00 to 12:30, New York time. The opening average was larger on 19 dates. Across dates, the median paired difference was **9.13 index points per one-minute bar**. All observed dates had 30 bars in both windows. The comparison describes movement within one-minute bars. It provides no estimate of price direction. This previously inspected, single-contract month limits generalization. The pinned third-party archive has no independent exchange-level verification. [Protocol](studies/mnqh5-intraday-range/protocol.md) · [Date-by-date evidence](studies/mnqh5-intraday-range/evidence.json)

## Ask a research question

With an authenticated Codex CLI on a POSIX machine using Python 3.11 or later, launch either role in its own session. The same profiles are available to compatible GitHub Copilot clients in .github/agents.

```sh
python researcher.py researcher "How does MNQ intraday variability change across sessions? Define a benchmark and write a research note."
python researcher.py reviewer "Evaluate the evidence and limitations in studies/mnqh5-intraday-range."
```

The researcher can investigate volatility, liquidity, cross-market relationships, data quality and forecast calibration. It chooses methods suited to the question and identifies missing data. For example, a bid–ask spread study needs quotes. An OHLC file supplies traded price ranges. Neither role has an execution mandate. The reviewer runs locally with a read-only sandbox.

## Reproduce the published note

Recreate the input from the pinned source checkout, then compare the derived output with the committed evidence. The preparation script creates a fresh CSV path. The study checks its SHA-256 before analysis. [Pinned source](https://github.com/tdtrader76/NQ_Backtest/tree/7ac6bd20d3fa46b25fa6d2db947200ef9860c6ef)

```sh
python examples/prepare_mnq.py /path/to/pinned/NQ_Backtest /tmp/mnqh5-feb.csv
python range_study.py /tmp/mnqh5-feb.csv > /tmp/mnq-range-evidence.json
diff studies/mnqh5-intraday-range/evidence.json /tmp/mnq-range-evidence.json
python -m unittest discover -s tests
```

## Institutional basis

Citadel describes researchers working on forecasts, market impact and portfolio construction. Goldman Sachs describes quantitative strategists improving execution logic and analytics used by client-facing teams. Federal Reserve guidance describes qualified, objective challenge of a model’s intended use. This repository adapts the investigation and validation responsibilities to MNQ. The earlier simulator experiment has a [separate historical record](docs/earlier-simulator.md). [Citadel EQR](https://www.citadel.com/careers/career-perspectives/inside-eqr-what-it-means-quantitative-researcher/) · [Goldman Sachs](https://www.goldmansachs.com/careers/blog/meet-our-people-erin-r) · [Federal Reserve](https://www.federalreserve.gov/frrs/guidance/supervisory-guidance-on-model-risk-management.htm)

## First employee: Quant Researcher

See [Employee 001 charter](docs/EMPLOYEE_001_QUANT_RESEARCHER.md), [deterministic researcher](company/quant_researcher.py), and ECC-inspired [Codex agent role](.codex/agents/quant_researcher.toml). This role performs checksummed descriptive MNQ intraday-range research, not live execution or validated trading-alpha discovery. Run `python -m unittest discover -s tests -v` before merging.
