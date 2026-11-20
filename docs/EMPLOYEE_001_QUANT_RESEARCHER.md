# Employee 001 — Quant Researcher

Employee #1 is an MNQ **software research role**, not a human employee or an autonomous always-on service.

## Mission
Frame falsifiable research questions, record counterexamples and dataset provenance, analyze properly licensed historical MNQ evidence, preserve reproducibility and request independent review. No trade orders, position changes or asserted profitability.

## Implemented task
The CLI in company/quant_researcher.py computes average one-minute high-minus-low ranges in two specified nonoverlapping America/New_York time windows. It pairs eligible weekdays, excludes incomplete observed days, reports daily pairs, a median difference, an exploratory paired-date bootstrap CI and a two-sided sign test conditional on independent dates.

Input CSV columns: timestamp,contract,open,high,low,close. Data must have strictly increasing UTC minute-start timestamps, positive tick-aligned OHLC, and exactly one quarterly MNQ contract. This is descriptive OHLC analysis, not order flow.

## Research protocol JSON
Required fields: id, question, hypothesis, falsifier, data_source, data_kind, data_sha256, contract, start, end, window_a, window_b, min_dates, seed.
- data_kind: historical or synthetic; data_sha256: SHA-256 of exact CSV bytes.
- start/end: UTC timestamps in YYYY-MM-DDTHH:MM:00Z.
- window_a/window_b: objects with label, start and end, each New York HH:MM; 1–120 minutes; not overlapping.
- min_dates: at least 3; seed: reproducible nonnegative bootstrap RNG seed.
- id: unique lowercase run ID. Reuse is rejected.

## CLI
    python -m company.quant_researcher --spec /path/to/protocol.json --data /path/to/mnq-bars.csv --out-root research-runs
    python -m unittest discover -s tests -v

Each run creates research-runs/<id>/protocol.json, result.json and research_note.md. The result stores engine, protocol and input hashes. Raw data are not committed automatically. Tests use clearly labeled synthetic inputs.

## Validation and limitation
An observed range difference is not a directional forecast or a profitable edge. OHLC cannot measure volume delta, cumulative delta, absorption, market depth or fill prices. This software cannot prove a historically unexamined holdout or independently authenticate third-party exchange data. Calendar and roll handling require separate tests. An independent reviewer must inspect all findings.

ECC (https://github.com/affaan-m/ECC, MIT) inspired the plan-test-verify-review pattern and Codex role; ECC is not vendored or installed here. Existing quantlab.py and range_study.py remain independent, historically examined research tools.

## Additional mathematics the role must investigate

Beyond the deterministic price-range and volume-profile modules, study conditional first-passage probabilities, volatility-normalized excursions, realized volatility, robust bootstrap intervals, regime dependence, sequential outcomes, change-point detection, and appropriate Bayesian/time-series models **only when the source data and evaluation design justify them**. Specify the statistic and time-of-availability before computing it. Treat every added hypothesis/threshold as an additional comparison. A technical indicator is not automatically evidence of predictive information. For NQ/MNQ tick-trade research, use [the profile lab](docs/PROFILE_RESEARCH_LAB.md) for POC/VAH/VAL/HVN/LVN and level-reaction definitions.

## Completed historical assignments

Employee #1 has executed multi-year, source-pinned NQ OHLCV analyses. Read `studies/nq-five-year-2021-2025/` and `studies/nq-session-years-2024-2026/` before reusing the data. The first analysis compares conditional next-minute ranges using 2021–2023 thresholds and a 2024–2025 holdout. The second evaluates 09:30–10:00 ET versus midday range across complete paired sessions from 2024–2026. Both reports include source fingerprints, coverage, uncertainty, and limitations. Neither can substantiate five-year VAP/POC/VAH/VAL/HVN/LVN claims from minute OHLCV; provide licensed historical trade-by-price records for those questions.

## External data scout: Hugging Face

The research employee can now discover candidate market datasets using the Hugging Face Hub public metadata API. Read docs/HUGGINGFACE_DATA_SCOUT.md and inspect studies/huggingface-discovery/ when present. The scout must classify NQ/MNQ CME futures separately from USTECH CFDs, NDX spot/index values, QQQ shares, and synthetic datasets. Candidate findings are not verified, no raw data is auto-downloaded, and missing license or provenance must be flagged rather than inferred.
