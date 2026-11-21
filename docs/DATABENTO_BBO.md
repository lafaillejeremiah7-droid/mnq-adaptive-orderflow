# Databento MBP-1 -> normalized top-of-book adapter

Databento provides L1 MBP-1 data containing BBO prices, sizes and per-event
updates. This adapter accepts only a **previously downloaded and licensed**
`GLBX.MDP3` `mbp-1` DataFrame CSV exported with `pretty_px=True`,
`map_symbols=True`, and a named `ts_event` index (or column).

Required columns: ts_event, ts_recv, sequence, symbol, rtype, publisher_id,
instrument_id, flags, action, bid_px_00, bid_sz_00, ask_px_00, ask_sz_00.
The adapter requires rtype 1 and a single mapped quarterly NQ/MNQ outright,
converts display-scaled 0.25-point prices to integer ticks, checks both clocks
and sequence/identifier consistency, rejects bad receive-time flags and
book-clear actions, and emits only LAST-marked complete event snapshots.
Undefined, single-sided, crossed or ill-formed books fail closed.

```sh
python -m company.databento_bbo_csv --input mbp1_vendor.csv --contract MNQZ6 --output bbo.csv --report bbo_import.json
```

Keep the source raw file, its hash, exported parameters, license and symbol
mapping. The generated canonical BBO can feed the separate quote-cost
scenario simulator. Neither module can reconstruct queue positions or
authenticate the source. No market order is submitted.

Official schema: https://databento.com/docs/schemas/mbp-1
Common quality flags: https://databento.com/docs/conventions/common-fields-enums-types
