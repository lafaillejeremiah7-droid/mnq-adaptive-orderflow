# Historical forecast comparison

The tournament compares four deterministic forecasts of the same binary outcome. A target touch first gives a label of one. A stop touch first or expiration of the complete horizon gives zero. A timeout has unknown dollar P&L without a priced exit. The tournament consumes offline event labels and writes a JSON report.

## Point-in-time input

The original eight CSV columns remain supported. Five optional columns record information that legacy files cannot establish.

| Column | Meaning |
| --- | --- |
| `feature_available_at_ms` | Latest UTC millisecond when all inputs to this decision, including the regime, were available. Must be at or before detection. |
| `label_available_at_ms` | First UTC millisecond when this particular outcome could be used by the learner. Must be at or after resolution. |
| `instrument` | MNQ or NQ. |
| `contract` | A specific expiry identifier from the dataset. |
| `setup_id` | Versioned, predeclared entry/label definition. |

Each file may describe a single instrument, contract and setup definition. Unknown values remain unknown when their columns are omitted. A contract roll needs a separate file or an independently validated continuous-series definition and implementation. Decision and resolution times are minute-aligned. Availability times may fall between minutes. `TIME_LIMIT` requires the full declared number of minutes. A repeated detection with the same direction, target, stop and horizon raises an error even if the regime or outcome changed.

For a legacy file the program assumes features were available at detection and labels at resolution. The report counts rows with explicit timestamps. Neither a completed row nor a timestamp establishes that prices, regime labels or revisions were available then. The Data Auditor reports the raw-bar coverage, contract/calendar and source limitations. Missing minutes between *events* can be legitimate. Raw bar continuity must be checked during labeling. The OCaml labeler requires consecutive bars up to the first touch or horizon and rejects same-bar double touches.

## Selection and evaluation

Pass a fixed validation start and holdout start together for a registered study. The standalone exploratory default splits at 60% and 80% of the observed unique detection times. Preserve the input bytes, assessment time, dates, hyperparameters and trial history to reproduce a comparison.

1. At decision time `t`, each worker sees the regime and geometry. The common training catalog contributes only same-geometry labels released strictly before `t - embargo`. The recency workers weight by release order.
2. Drop a validation event if its predeclared horizon end **or** its label release plus the embargo reaches the holdout start. The same horizon rule applies to a quick target touch and a timeout. The Judge ranks three challengers by common-event validation Brier score and requires a predeclared improvement over baseline.
3. Structural checks cover the whole file. Holdout forecasting begins only after validation selects a challenger that clears the margin. The selected policy and baseline update on earlier released observations according to their fixed rules, including prior holdout labels. This evaluates an adaptive forecast. Candidate identity and hyperparameters stay fixed for the test.
4. The Skeptic compares paired Brier losses by resampling circular blocks of consecutive observed New York dates. A sampled date retains all events and both forecasts together. The mean weights individual events equally. The default takes 800 replicates, two dates per block and a fixed seed of 41. Acceptance requires positive mean improvement and a positive 2.5th percentile. There must be at least two full blocks and the configured minimum number of dates.

The date grouping uses the New York civil calendar. It does not infer a CME trading session or insert an absent date. Dependence beyond the prespecified block length, few effectively independent periods, missing or ambiguously resolved labels, and repeated attempts on the same holdout can all bias the comparison. Register a new untouched evaluation period before judging a revised specification. Source verification, calibrated probability intervals, trade-level execution outcomes and forward observations require additional evidence.

## Reproduce a historical assessment

```bash
python3 -m scripts.agent_tournament \
  --history examples/ILLUSTRATIVE_mnq_labeled_setups.csv \
  --as-of-ms 1700216040000 \
  --validation-start-ms 1700129580000 \
  --holdout-start-ms 1700172780000 \
  --embargo-minutes 1 --block-days 2 --seed 41 \
  --evidence-kind synthetic
```

The example yields `NO_VALIDATED_WINNER` and zero final comparisons. Per-agent details include a validation forecast, comparable prior counts, positive and negative subset counts, and validation Brier error where observations exist. A missing holdout score means the corresponding gate was never reached. Even `RESEARCH_CHAMPION_ONLY` identifies a forecast-score result on the supplied labels. The trading-edge verdict stays `EDGE_NOT_ESTABLISHED`.
