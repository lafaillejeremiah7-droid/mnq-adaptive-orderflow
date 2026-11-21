# Employee #1 local research worker and immutable job registry

`company.research_service` implements a local SQLite job queue for the
existing point-in-time experiment. It is not a hosted always-on agent or
a regulated live trading system. Run the worker manually, or operate it
under a separately configured process supervisor.

```sh
python -m company.research_service --db research-runs/jobs.sqlite3 enqueue --protocol experiment.json --data events.csv --out research-runs/jobs
python -m company.research_service --db research-runs/jobs.sqlite3 worker
python -m company.research_service --db research-runs/jobs.sqlite3 status
python -m company.research_service --db research-runs/jobs.sqlite3 worker --poll-seconds 5
python -m company.research_service --db research-runs/jobs.sqlite3 recover --confirm-no-active-workers
python -m company.research_service --db research-runs/jobs.sqlite3 retry --id research-id
```

Enqueue pins the source and protocol SHA-256 and reserves an immutable ID.
A single SQLite transaction claims the next job. The worker calls the
research experiment, automated adversarial screen, exact replay verifier,
and separate Decimal-based numeric cross-check. It then saves an audit
report `numeric_validation.json` and a durable completed/failed state.
All errors are retained in SQLite. Source changes fail closed. Crashed
`running` jobs can be explicitly marked `interrupted`; retries refuse
to overwrite partial artifacts and require inspection/a fresh study ID.

Worker polling is a foreground process and ends if the host process stops.
An external scheduler/supervisor must provide durable unattended execution.
This service does NOT acquire or authenticate licensed feeds, guarantee
independent model validation, reconstruct market depth, execute trades,
or authorize brokerage orders. Every experiment remains research-only.

The recovery command may only be run once all worker processes are stopped.
It refuses to relabel active work without explicit operator acknowledgement.
SQLite connections are closed after each operation. A worker whose queue claim
changes during execution reports failure instead of falsely marking success.
