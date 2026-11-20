# Employee #1 — Quantitative Researcher / Data Scientist standard

Status: **working research infrastructure, not institutional certification.** No claim of exceeding real human quants is currently supported. This project must earn that conclusion with independent results.

## Required professional workflow

1. Scientific question: Define the measurable hypothesis, null benchmark, units, outcome horizon, decision time, falsifier and expected limitations before observing the evaluation dataset.
2. Data science: Identify NQ versus MNQ versus CFD; pin vendor/source revision and SHA256, verify license, contract, roll events, tick sizes, timestamps, timezone, source delays, missing values and sessions. OHLCV does not reconstruct volume by price or aggressive buyer/seller flows.
3. Point-in-time controls: Features must be available before each decision. Training labels must have ended before the test fold's embargo cutoff. Train-only normalization. No post-hoc test tuning.
4. Model comparison: Prefer comprehensible baselines. Predeclare fixed model specification and evaluate out-of-sample statistical loss. A more complex model must consistently beat simpler alternatives.
5. Inference: Report sample accounting, dependent observation clusters, confidence intervals, uncertainty, model falsification and correction for all registered hypotheses including failed attempts.
6. Economic realism: Separately test gross and cost-aware results, overlapping labels, quote spread, commissions, slippage, impact, latency, fills, tail losses and applicable prop-firm constraints. Never infer executions from candle high/low.
7. Independent challenge: An **independent qualified** reviewer reproduces evidence from licensed raw data, checks source and transformations, audits selection bias, tests alternative explanations and can reject the model.
8. Production governance: Model ownership, authenticated deployment approval, monitoring, emergency stop, audit log and changing-market responses. This repository grants no trading authority.

## Current code

- company/huggingface_discovery.py: Public Hub dataset scouting with source and instrument candidate warnings.
- company/five_year_nq.py and company/nq_session_years.py: Previously completed real historical bar studies. These dates are already seen, not pristine holdouts.
- company/market_profile.py: True volume-at-price research on timestamped trade prints, not one-minute bars.
- company/research_lab.py: Reproducible, registered offline predictive experiment; SHA-256 source/protocol/engine hashes, declared feature availability, single dated NQ or MNQ contract, train-only ridge vs train-only mean baseline, purged frozen or expanding chronological evaluation, date-block bootstrap and Bonferroni for declared hypothesis family, hypothetical position-cost sensitivity and immutable output.
- company/research_gate.py: Automated skeptical review with explicit blockers; **not** an independent human validation or production approval.

## General event-based research input

One UTF-8 CSV containing, in exact column order:

    decision_at_utc,feature_available_at_utc,label_end_at_utc,contract,forward_return_bps,x_foo,x_bar

Every timestamp must be explicit UTC ISO-8601. The first time is the decision, the second is the availability of all supplied features, and the third is the end of the observed future label. Features are finite numeric x_-prefixed columns. The label is future return in *basis points*, not NQ points or dollars. Columns must match registered protocol feature list exactly. Each experiment supports one explicit quarterly NQ/MNQ contract. Multi-year continuous contracts need a separately audited, roll-aware ETL that is not yet built.

Mandatory protocol keys: id, researcher, question, hypothesis, falsifier, data_source, source_sha256, source_kind, source_rights, contract, features, train_end_utc, test_start_utc, test_end_utc, embargo_seconds, max_label_horizon_seconds, test_folds, retraining, min_train_dates, min_test_dates, min_test_events, ridge_lambda, decision_threshold_bps, cost_per_side_bps, hypotheses_in_family, seed, max_records, data_previously_examined.

For example, a prospective experiment may set train_end_utc to 2025-01-15T00:00:00Z, test_start_utc to 2025-02-01T00:00:00Z, test_end_utc to 2025-03-01T00:00:00Z, source_kind to historical, source_rights to unverified, contract to MNQH5, features to ["x_foo", "x_bar"], test_folds to 3, retraining to frozen, embargo_seconds to 600, max_label_horizon_seconds to 300, ridge_lambda to 10, hypotheses_in_family to 20 and data_previously_examined to true. The source SHA256 must be calculated on the actual exact input file. **This is not an endorsed experimental design; no unverified historical dataset is a fresh holdout.**

Commands:

    python -m company.research_lab --protocol protocol.json --data events.csv
    python -m company.research_gate --study research-runs/institutional/<experiment-id> --source events.csv --engine company/research_lab.py
    python -m unittest discover -s tests -v

The new experiment writes protocol.json, result.json and research_note.md to a fresh output directory only. The second command writes adversarial_review.json. Neither module downloads confidential data nor executes trades. Its default use in tests is synthetic and clearly labeled.

### What the safeguards actually guarantee

- Timestamp checks reject any explicitly future-dated feature and all naive/local timestamps; a malicious or incorrect upstream feature pipeline could still encode future prices despite a false availability time.
- Training label purge and embargo enforce declared event timing; the upstream source's roll/corporate/exchange timestamp correctness is NOT independently certified.
- Frozen evaluation never fits on test dates. Expanding evaluation legitimately retrains with earlier test outcomes once they are available, so it is not a single untouched set.
- Date grouping currently means **UTC calendar dates**, not verified CME trade sessions. This limits independence and inference.
- The researcher compares one fixed ridge specification against a train-only mean. More robust baselines, nested tuning and broad factor research are not yet implemented.
- Bootstrapping is over UTC dates. Its interval and exact sign p-value can be wrong under serial day dependence; Bonferroni only covers the *declared* test family. Neither statistical significance nor lower loss proves tradeability.
- Indicative P&L is omitted if label intervals overlap, and even permitted results omit queue/fill modeling. Dollar risk in NQ/MNQ and proprietary firm rules need separate simulations.
- Hashes ensure local consistency and reproducibility, not proof of pre-registration before first viewing results or legal source entitlements.
- Machine review NEVER authenticates an independent reviewer or automatically authorizes deployment. Without --source and --engine it reports the missing independent source/code rehash as explicit review blockers. Even with both supplied, code cannot establish reviewer independence or upstream market correctness.

### Remaining gaps before a credible professional-standard claim

Licensed multi-year CME tick trades/quotes/book history and authenticated historical roll calendar; data-contract tests against a second independent provider; robust causal/forecasting ETL with actual feature availability proofs; an experiment registry and untouched holdouts; independent cluster/moving-block inference; distinct nulls and baseline ablations; more time-series model families and properly nested hyperparameter selection; cost-aware market replay and sizing/ruin simulations; independent validation by a qualified person; production monitoring and authenticated controls.

## What counts as "surpassing" a professional researcher

Only a fair blind benchmark can establish this: on previously unseen real market research assignments, demonstrate more reliable falsification, stronger replicated out-of-sample performance, fewer methodological errors, or better research throughput **without lowering quality**. Code size, indicator count and in-sample Sharpe cannot satisfy this.

References:
- Federal Reserve / OCC / FDIC model-risk guidance and effective challenge: https://www.federalreserve.gov/frrs/guidance/supervisory-guidance-on-model-risk-management.htm
- CME NQ/MNQ official tick and multiplier specifications: https://www.cmegroup.com/markets/equities/sp-500-and-nasdaq-100-futures.html

These are quality benchmarks, not evidence of regulatory compliance.
