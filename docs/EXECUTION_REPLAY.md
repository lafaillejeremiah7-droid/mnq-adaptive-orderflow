# Conservative NQ/MNQ top-of-book execution scenarios

Historical `top_of_book_v1` is a normalized **best bid/ask snapshot**, not a
record of actual fills or complete CME market-by-order depth. Input CSV header:

`ts_event_ns,ts_recv_ns,contract,bid_ticks,bid_size,ask_ticks,ask_size,sequence`

Each price is already an integer NQ/MNQ 0.25-point tick. Quote times are UTC
nanoseconds; `ts_recv_ns` is when a vendor capture system received the quote.
All records must be sorted by `(ts_recv_ns, sequence)` with no duplicates.
Quotes must be strictly uncrossed, positive, and for one quarterly contract.

Required JSON spec fields: `contract`, `source_sha256` (exact CSV),
`source_kind` (synthetic/historical), `provider`, `schema` (top_of_book_v1),
`rights_status` (documented/unverified), `fees_per_contract_usd`,
`conservative_slippage_ticks`, `max_quote_age_ns`, `max_spread_ticks`,
`max_records`. Separate intentions JSON is a list of
`{decision_ns,side,contracts,latency_ns}` dictionaries (BUY or SELL only).

```sh
python -m company.execution_replay --spec quote-spec.json --quotes bbo.csv --intentions scenarios.json --output scenario-report.json
```

At arrival time = decision+latency, the simulator selects only the latest
**received** BBO record no later than arrival, rejects stale/overwide quotes
and insufficient unconsumed displayed top size, and assumes fill at opposite
touch plus a user-specified adverse slippage stress. It computes cost relative
to displayed mid plus fee using $5 NQ tick and $0.50 MNQ tick.

**This is not an exact execution model.** Quote size can cancel, the actual
queue is unknown, deeper price levels are absent, source timestamps and
licenses are unverified, and deterministic slippage is not a measured bound.
The output distinguishes hypothetical fill from no-simulated-fill and has
`actual_exchange_fills_verified=false`. Market-by-order reconstruction,
exchange fill reports and measured latency/impact are needed for genuine
execution realism. Do not use this as evidence of a profitable edge.

References:
- https://databento.com/docs/schemas/mbp-1
- https://databento.com/docs/schemas/mbo
- https://www.cmegroup.com/articles/faqs/market-by-order-mbo.html
