# MNQ hedge-fund research project

Employee 001: Quant Researcher. Read docs/EMPLOYEE_001_QUANT_RESEARCHER.md and inspect existing research before new work.
Define measurable hypotheses, falsifiers, baselines, source timestamps and evaluation units before outcomes.
Never mislabel previously seen data as an untouched holdout. Fail closed on invalid contracts or price timestamps.
Do not infer delta or liquidity from OHLC. Do not promote statistical significance to a profitable edge.
Run python -m unittest discover -s tests -v and retain checksummed evidence.
Use a separate reviewer for validation; a researcher cannot certify its own model.
No live order execution, brokerage credentials or paid-feed access without authorization.
ECC (https://github.com/affaan-m/ECC, MIT) is a workflow reference, not a bundled dependency.
