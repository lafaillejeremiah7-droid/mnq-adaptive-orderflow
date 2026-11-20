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
