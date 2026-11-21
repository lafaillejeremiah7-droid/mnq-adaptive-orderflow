# Multi-year NQ/MNQ data inventory (source evidence still required)

The module `company.historical_dataset` supports offline indexing of an
arbitrary number of individually validated, checksum-pinned NQ or MNQ
quarterly-contract trade CSV partitions, including rollover assignments.
It does not buy, scrape, or download exchange market data.

Create one canonical trade CSV and matching `company.data_admission` manifest
per partition. Supply a sorted `session_date,contract` calendar CSV that
declares the contract considered active on each expected date. This calendar
is **self-declared**, not an independently checked CME holiday/roll schedule.

JSON registry v1 fields: `version=1`, `dataset_id`, `dataset=GLBX.MDP3`,
`contract_root=NQ|MNQ`, `source_kind=historical|synthetic`,
`rights_status=unverified|documented`, `rights_reference`,
`calendar_file`, `calendar_sha256`, and `partitions` containing file/manifest
relative paths. All paths must stay under the configured root.

```sh
python -m company.historical_dataset --registry registry.json --root ./licensed-data --output inventory_report.json
```

This checks file integrity, individual trade structure and session coverage,
consistent source and rights declarations, correct assigned contract per
date, no duplicate sessions and complete equality to declared inventory.
It does not authenticate the declared source; it does not check every CME
session without an official exchange calendar; it cannot independently
validate entitlement, native book depth, queue state or exchange feed gaps.

To resolve the actual data blocker: obtain suitable multi-year licensed CME
trade and MBO or MBP historical files; acquire vendor entitlement/rights
documentation; independently reconcile official session and roll schedules;
validate independent instrument mapping and source sequence quality.

References: https://www.cmegroup.com/market-data/real-time-and-historical-data.html
and https://databento.com/docs/datasets/glbx-mdp3.
