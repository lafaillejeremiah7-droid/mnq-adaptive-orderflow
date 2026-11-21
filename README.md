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

## NQ/MNQ trade-by-trade volume profile research

[Employee #1's volume-profile and reaction lab](docs/PROFILE_RESEARCH_LAB.md) adds actual executed volume-at-price, POC, VAH, VAL, HVN, LVN, VWAP, labeled aggressor delta, and prior-session first-touch rejection/cross research on separate NQ or MNQ trade files. It deliberately rejects OHLC-only volume-profile reconstruction and records all censoring/coverage limits. Start with the file format, offline Databento CSV adapter, preregistered experiment protocol and commands in the guide. No real market data or brokerage credentials are bundled.

## Multi-year empirical NQ research (historical bars)

Employee #1 has completed two public-source historical studies beyond the single-day tick-profile demonstration:

- **Five calendar years, 2021–2025:** [read the NQ five-year report](studies/nq-five-year-2021-2025/report.md) and [source/coverage hashes](studies/nq-five-year-2021-2025/summary.json). It analyzes 1,597,249 minute bars from pinned NinjaTrader exports. Thresholds are calibrated on 2021–2023 and evaluated on 2024–2025 without retuning. The source has unknown time zone, so no opening-session statements are made from it.
- **Explicit New York sessions, 2024–2026:** [read the NQ multi-year opening-vs-midday report](studies/nq-session-years-2024-2026/report.md) and [source/coverage hashes](studies/nq-session-years-2024-2026/summary.json). It analyzes 593 complete paired dates from a separate, mixed-provider continuous-futures bar file with ET timestamps.

Rerun with `python -m company.five_year_nq` or `python -m company.nq_session_years` on a machine with network access; GitHub Actions has dedicated historical research workflows. Original third-party bars remain outside this repository. These are descriptive OHLCV studies, **not five years of POC/HVN/LVN/order-book research**. Historical price-and-size ticks and explicit rollover/coverage verification are still required for genuine multi-year volume-at-price tests. No study establishes tradable alpha or live readiness.

## New external data discovery: Hugging Face

[Hugging Face data-scout documentation](docs/HUGGINGFACE_DATA_SCOUT.md) explains the new `python -m company.huggingface_discovery` command and its dedicated Actions workflow. The Quant Researcher searches the Hugging Face public dataset API for potential NQ, MNQ, futures, and Nasdaq-related sources. It classifies candidate instrument types and file availability, records dataset revisions and license labels, and writes a metadata-only candidate report. It does **not** assume a listed dataset is exchange-authenticated or fit for backtesting, and it does not download raw market data.

Promising lead: `mdelcristo/NQ-F_1min_OHLCV_Parquet` advertises 2015–2025 NQ one-minute bars. `CarlosSilva1/ustech-ticks` is Nasdaq-related *CFD quotes*, not CME NQ prints. Neither source should be treated as volume-at-price NQ tick data solely from a Hugging Face preview.

## Scientist-grade experiment governance (research only)

Employee #1 now includes a registered, checksummed, point-in-time [research experiment runner](company/research_lab.py) and an [adversarial model-review gate](company/research_gate.py). See [standards, operations and limits](docs/QUANT_RESEARCH_STANDARD.md). The researcher fits a fixed train-only ridge baseline comparison across purged chronological folds, evaluates date-level uncertainty and a declared multiple-testing family, and rejects overlapping-return P&L. The gate does not self-approve live trading or pretend to be a human independent reviewer. Run the existing Python test suite.

## Path-dependent risk research

The researcher also includes [NQ/MNQ Monte Carlo risk study](company/risk_research.py): resample whole historical trade days, apply explicit static or EOD-trailing drawdowns and target-first rules, calculate failure/target/unfinished frequencies and Wilson intervals, and account for separate NQ/MNQ tick values and round-trip fees. Synthetic tests do **not** establish real challenge success probabilities. Usage and assumptions: [quant research standard](docs/QUANT_RESEARCH_STANDARD.md).


## Benchmarked architecture: Python + Polars + optional integrated C++

Measured the same trade-volume/POC/value-area task on 250k synthetic trades and 488,749 vendor-reported NQZ6 RTH trades. Rust was 5.9× faster and C++ 9.6× faster than interpreted Python loops on the historical sample; Rust-backed Polars was 3.1× faster while staying in Python. All outputs matched exactly. These results concern a narrowly defined kernel, **not full trading-system or model speed**. Read [decision, methodology and limitations](docs/LANGUAGE_ARCHITECTURE_DECISION.md), [report](studies/language-benchmark/report.md), and [benchmark code](benchmarks/lang_perf/). Keep Python as the core research language; do not auto-replace the audited Python engine with the standalone experimental binaries.

### Native C++ volume-profile acceleration

The researcher now has an optional C++20 pybind11 extension that aggregates trade-size-at-price and aggressor counts inside the existing volume_profile engine while keeping Python rules for POC/VAH/VAL, HVN/LVN and delta. Complete result dictionaries match on differential tests; the historic vendor sample showed approximately 2.0–2.35x full-profile speedups on separate runners. The old standalone CSV speed comparison is not the full research speedup.

Build on Linux using Python development headers and C++20 compiler:

    python -m pip install pybind11==3.0.1 setuptools wheel
    python setup.py build_ext --inplace
    python -m company.market_profile --spec protocol.json --trades trades.csv --profile-backend cpp

The default is Python; auto selects C++ only for >=20,000 historical trades when the extension is installed. See [the C++ integration guide](docs/CPP_ACCELERATION.md) and [integrated benchmark](studies/cpp-profile-acceleration/report.md). This is research-only, not an institutional edge or live system.

## Data admission, quote replay, and durable research operations (research-only)

The latest development branch adds four tightly scoped improvements. None
independently certifies trading alpha, licenses or exchange completeness:

- [Data admission](docs/DATA_ADMISSION.md) validates checksums and declared
  RTH session coverage. [Multi-year dataset registry](docs/HISTORICAL_DATASET.md)
  reconciles locally supplied quarterly NQ/MNQ trade files and operator-declared
  rollover calendars. An operator must still obtain properly licensed data and
  independent exchange-calendar evidence.
- [Independent-formula numerical validation](company/independent_validation.py)
  checks persisted holdout predictions against raw labels and recomputes RMSE,
  MAE, squared-error improvement and date sign tests. It does not reproduce
  feature engineering or prove human independent model approval.
- [Quote-cost scenarios](docs/EXECUTION_REPLAY.md) simulate only latency-delayed
  top-of-book aggressive order assumptions, with spread, displayed-size,
  adverse slippage and NQ/MNQ tick values. A separate
  [Databento MBP-1 offline adapter](docs/DATABENTO_BBO.md) can normalize a
  legally supplied pretty-priced vendor CSV to the quote format. Actual
  fills, order queue, impact and exchange permissions remain unverified.
- [SQLite research service](docs/RESEARCH_SERVICE.md) provides checksummed
  enqueued jobs, persistent status, error recovery, deterministic replay,
  automated adversarial review and a separate numeric-check artifact. The
  polling worker requires a running host/process supervisor and cannot trade.

Example research-only service commands:

```sh
python -m company.research_service --db research-runs/jobs.sqlite3 enqueue --protocol protocol.json --data events.csv --out research-runs/jobs
python -m company.research_service --db research-runs/jobs.sqlite3 worker
python -m company.research_service --db research-runs/jobs.sqlite3 status
```

**Current release position:** The software components have passing automated
tests, but the overall Quant Researcher is not institutionally complete.
Authentic multi-year CME trade/quote/book history, verified data rights and
rolls, qualified independent scientific review and real execution evidence
remain missing. Keep the feature PR in draft; do not place live orders.
