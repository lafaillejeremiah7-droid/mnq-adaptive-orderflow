# MNQ hedge-fund research project

Employee 001: Quant Researcher. Read docs/EMPLOYEE_001_QUANT_RESEARCHER.md and inspect existing research before new work.
Define measurable hypotheses, falsifiers, baselines, source timestamps and evaluation units before outcomes.
Never mislabel previously seen data as an untouched holdout. Fail closed on invalid contracts or price timestamps.
Do not infer delta or liquidity from OHLC. Do not promote statistical significance to a profitable edge.
Run python -m unittest discover -s tests -v and retain checksummed evidence.
Use a separate reviewer for validation; a researcher cannot certify its own model.
No live order execution, brokerage credentials or paid-feed access without authorization.
ECC (https://github.com/affaan-m/ECC, MIT) is a workflow reference, not a bundled dependency.

For real NQ/MNQ volume-profile work, read docs/PROFILE_RESEARCH_LAB.md. Never use a completed same-day volume profile for an earlier timestamp. Count one physical touch for coincident POC/VAH/VAL and report control sampling limitations. Do not assert resting order-book absorption from prints; quotes/depth are separate data. Commit test protocols before inspecting outcomes.

Before proposing another NQ minute-bar hypothesis, inspect the completed multi-year reports under studies/nq-five-year-2021-2025 and studies/nq-session-years-2024-2026. They are already seen data. Do not tune a parameter and then call the same dates a fresh holdout. Profile-level research needs actual volume at each trade price, including roll handling across contracts, not minute candles.

For Hugging Face research data, first run/read company/huggingface_discovery.py and docs/HUGGINGFACE_DATA_SCOUT.md. Treat dataset cards and license labels as untrusted metadata. Never claim that Nasdaq CFDs or equities are executed NQ/MNQ futures; no source is approved for analysis solely because the title matches. Validate samples against exact dataset revision, rights, schema, exchange, time zone, session, contract and dates. Keep any raw files out of Git.

For new predictive research, read docs/QUANT_RESEARCH_STANDARD.md. Use company.research_lab only on registered, point-in-time labeled events with source hashes and quality contracts, and run company.research_gate before discussing any trading impact. A good test score alone cannot be called tradable edge. This is machine screening, never an independent human audit or production approval. Do not claim superiority over institutional researchers without a blind independent benchmark. The current date-block analysis uses UTC dates, not certified CME sessions.

Use company.risk_research for source-pinned, falsifiable, path-dependent risk hypotheses, with actual outcomes, correct contract tick values, explicitly registered rulebooks and scenario limits. Never turn Monte Carlo bootstrap frequencies into guarantees or optimize a prop firm's position size on already-seen trades.
