# Quant Researcher — Four-gap implementation and external release blockers

## Implementation inventory

- Historical data foundation: `company/data_admission.py` and `company/historical_dataset.py` reconcile user-declared sessions, trade files, checksums and contract roll assignments. `company/databento_bbo_csv.py` normalizes downloaded MBP-1 quote exports. None verifies licensed exchange delivery.
- Numerical validation: `company/research_lab.py` now persists holdout predictions. `company/independent_validation.py` rechecks source targets, errors, fold counts and declared-family sign p-values with independent formulas. This is not independent model training or a human validator.
- Execution: `company/execution_replay.py` provides conservative top-of-book scenario costs with delayed quote access, quote-age/spread guards, top-size exhaustion, fees and tick values. These are assumed costs without actual fills, queue dynamics or complete book replay.
- Operations: `company/research_service.py` uses a durable SQLite queue and local polling worker, immutable study IDs, checksums, automated adversarial review, replay and numerical cross-checks. It does not include a cloud-hosted always-on process or brokerage connections.

## What is NOT complete

1. **Licensed, independently authenticated multi-year CME trades and MBP/MBO data.** An actual entitlement and suitable raw files must be supplied. Independently verify market-calendar/roll assignments and exchange timestamps. The existing third-party one-minute studies cannot establish trade-by-price order flow.
2. **Independent scientific validation.** A qualified independent reviewer must independently reproduce data preparation, test preregistration/hypothesis-family history, assess novel untouched holdout periods and approve or reject scientific claims. Internal deterministic and numerical replay cannot replace this.
3. **Realistic, independently calibrated execution.** Obtain complete trade/quote/order event histories, latency measurements, exchange/clearing fee schedules, cancel/replace and partial-fill evidence, and actual fill reports. L1 cost estimates do not prove executable orders.
4. **Unattended production research service.** The local worker is operable while running, but host deployment, process supervision, secrets/permissions, monitoring, backups and incident runbooks have not been independently reviewed. Trading is deliberately disabled.

## Release gates

| Requirement | Software check | External completion gate | Status |
|---|---|---|---|
| Canonical trade data and vendor MBP-1 normalization | Tested offline with synthetic fixtures | Obtain and validate legally usable multi-year historical CME source | BLOCKED |
| Scientific metric cross-check | Numeric source-label reconciliation and CI | Human independent reconstruction and genuine prospective holdout | BLOCKED |
| Execution cost simulation | Conservative L1 scenario CI | True multi-level market replay, source entitlement, empirical fills | BLOCKED |
| Research worker | SQLite queue, recovery and self-audit tests | Durable hosted supervision/monitoring and operations acceptance | BLOCKED |

Tests and static checks can pass even while each external gate is blocked.
Do not promote the PR or use it to place trades until those requirements
are resolved independently. If a source or authorization is unavailable,
record BLOCKED, never mark it PASS by assumption.

Sources: https://www.cmegroup.com/market-data/real-time-and-historical-data.html
and https://databento.com/docs/schemas/mbp-1
