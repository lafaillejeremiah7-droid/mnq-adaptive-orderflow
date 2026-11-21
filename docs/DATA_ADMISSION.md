# NQ/MNQ historical trade-data admission

**Implemented:** The offline `company.data_admission` gate checks a user-declared
canonical trade file, NQ/MNQ contract, SHA-256 checksum and expected New York
session inventory. It reports missing or unexpected sessions, late first
prints, early last prints, excessive intertrade gaps and unknown-side volume.
NY DST is handled per date. It does not authenticate exchange data or licenses.

Manifest v1 must contain these exact fields:

- `version`: integer 1; `dataset_id`: lowercase slug; `provider`: name
- `venue`: `CME_GLOBEX` for `historical`, `SIMULATED` for `synthetic`
- `schema`: `canonical_trades_v1`; `contract`: one quarterly NQ/MNQ code
- `data_sha256`: lowercase SHA-256 of exact canonical CSV
- `source_kind`: `historical` or `synthetic`
- `rights_status`: `documented` or `unverified`; `rights_reference`: text
- `session_start`, `session_end`: New York HH:MM, same-day, at most 12 hours
- `session_dates`: sorted unique declared expected weekdays, YYYY-MM-DD
- `opening_tolerance_seconds`, `closing_tolerance_seconds`: integers 0–3600
- `max_intertrade_gap_seconds`: integer 1–7200
- `max_trades`: integer 1–5,000,000

Commands:

```sh
python -m company.data_admission --manifest manifest.json --trades nq.csv --output admission.json
python -m company.market_profile --spec study.json --trades nq.csv --admission-manifest manifest.json --out-root research-runs
```

The manifest contract and study session hours must match. Results pin
the manifest SHA-256 and admission report. Without an admission manifest,
`data_admission.status` is `not_checked` rather than a false certification.
Research output additionally records actual Python/C++ backend by session.

**Not established by successful validation:** authentic CME delivery, official
holiday or half-day calendar, vendor license entitlement, missing quotes,
accurate order-book reconstruction, queue fills, multi-year data integrity,
out-of-sample alpha, or trading authorization. A manually declared list of
expected dates cannot prove that a missing expected date was never omitted.
An official exchange calendar and independent source reconciliation are
required to upgrade these claims.

External specifications:

- CME historical data: https://www.cmegroup.com/market-data/real-time-and-historical-data.html
- Databento CME feed: https://databento.com/docs/datasets/glbx-mdp3
- Databento trades schema: https://databento.com/docs/schemas/trades
