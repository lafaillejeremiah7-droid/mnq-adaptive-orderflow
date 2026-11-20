# Employee #1: Hugging Face dataset scouting

Quant Researcher now has an **external market-dataset discovery** module. It scans
Hugging Face's public dataset metadata API, ranks relevant potential NQ/MNQ
sources, records source revisions, file paths, license labels and access
restrictions, and produces a reviewable manifest.

## Run

    python -m company.huggingface_discovery
    python -m unittest tests.test_huggingface_discovery -v

With network access, it writes two files to studies/huggingface-discovery:
candidates.json and report.md. A dedicated GitHub Actions workflow can run
discovery and commit these **metadata-only** reports on the research branch.

No Hugging Face login/token is required for public dataset metadata. Nothing
automatically downloads market-data files, approves a dataset as truthful,
executes trades, or calls a paid data provider.

## Specific datasets discovered during initial external inspection

- https://huggingface.co/datasets/mdelcristo/NQ-F_1min_OHLCV_Parquet
  advertises about 3.67 million NQ one-minute OHLCV rows covering approximately
  Jan 2015 to Jul 2025 (eleven annual Parquet files). Its dataset page has a
  MIT license label, but original exchange data rights, contract rollover and
  timestamp zone are not verified. Candidate for LONG-HORIZON price/volatility
  checks only until inspected.
- https://huggingface.co/datasets/CarlosSilva1/ustech-ticks advertises
  roughly 376 million bid/ask CFD *quote* ticks covering 2021–2026.
  This is a **Nasdaq-related CFD, not CME NQ/MNQ executions**, and must not be
  used to infer NQ volume profiles or exchange order-book absorption.
- https://huggingface.co/datasets/lynx1231/historical-equity-index-futures-data-sample
  offers example futures OHLCV including NQ contract codes, but the sampled
  data are not multi-year tick trades. Rows need independent verification.
- https://huggingface.co/datasets/syncster-data/us-market-1m-data
  broadly advertises US market minute bars; inspect the actual NQ symbols,
  entitlement, coverage, and schema before considering it.

These are **leads**, not data approvals. Hub hosted source files, model cards,
previews and license labels can be inaccurate or incompatible with licensed CME
feeds.

## Promotion policy

Employee #1 must first choose the question and the required level of market
data. Use executed trades (time, price, size, symbol) for volume-at-price,
tick delta if aggressor side is sourced, and complete MBO/MBP and trades for
passive book/liquidity hypotheses. Minute OHLCV can support candle-price,
volume totals, realized-volatility and session-range questions only.

Before using a candidate:
1. Verify the original publisher's data rights, third-party exchange terms,
   and any use/redistribution restrictions.
2. Pin one exact HF dataset commit and download only a bounded data sample
   into a private runner, not a public code repository.
3. Inspect actual schema, rows, asset identity, exchange, contract, timestamp
   units and timezone, date coverage, nulls, duplicates and tick sizes.
4. Confirm rollover handling, adjustment conventions and source consistency.
5. Record checksums, raw source details and every quality exclusion.
6. Register a falsifiable hypothesis and untouched test period.
7. Reject synthetic data, stock ETF data, and CFDs as substitutes for NQ
   executed trades (though they can be distinct explanatory proxies).

The discovery module **never marks a result research-ready by default**.
The presence of an MIT label on a Hub card does not convey guaranteed rights
to underlying copyrighted or exchange-licensed data.

Source: Hugging Face Hub API / list datasets:
https://huggingface.co/docs/huggingface_hub/en/package_reference/hf_api

## False-positive rejection

Hugging Face keyword search for `NQ` also returns Google's **Natural Questions**
NLP datasets. The scout explicitly requires financial-market context before
classifying a dataset as an NQ/MNQ futures prospect. A generic Parquet filename
is not evidence of price bars. Irrelevant search results are counted and
filtered from the candidate output.
