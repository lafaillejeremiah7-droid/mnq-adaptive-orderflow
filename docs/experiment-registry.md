# Experiment registry

Freeze an experiment before inspecting validation or holdout scores. Store every attempted candidate, including failed runs and rejections. The local SQLite registry takes a full code revision, immutable specification, deterministic seed, chronological windows and the SHA-256 of the actual input file. Keep that input available under its data license. A checksum establishes byte identity. Source authenticity, blind data custody and completeness of the research history require independent review.

The example below records an engineering exercise using the repository’s illustrative labels. It uses the original model revision. For another experiment, use its actual clean, committed revision, data manifest, selection criterion, costs and risk assumptions.

Save this as `spec.json`.

```json
{
  "experiment_id": "illustrative-label-audit-001",
  "question": "Do the illustrative labels permit a market-performance claim?",
  "model_version": "original-tournament",
  "git_commit": "13c61c4dc8488870378c742d0a2d2b95c9614e39",
  "seed": 17,
  "dataset": {
    "id": "repo-illustrative-labels",
    "source": "examples/ILLUSTRATIVE_mnq_labeled_setups.csv",
    "kind": "synthetic",
    "sha256": "fd38889af83861e19768e448c1a90d1aa3103b405ecf93ff32b063adddfdba86"
  },
  "data_period": [1699999980000, 1700216100000],
  "windows": {
    "training": [1699999980000, 1700100000000],
    "validation": [1700100000000, 1700160000000],
    "holdout": [1700160000000, 1700216100000]
  },
  "features": {"geometry": "Direction, target distance, stop distance and horizon at detection"},
  "parameters": {},
  "hypotheses": ["The fixture constitutes genuine holdout evidence"],
  "baseline": "Same-geometry target-first frequency",
  "acceptance_rule": "Reject market-performance claims if provenance is synthetic",
  "cost_assumptions": "Provenance audit only. No fills or P&L are modeled.",
  "drawdown_assumptions": "Zero exposure in this engineering exercise."
}
```

Save the following independent review as `decision.json`.

```json
{
  "status": "REJECTED",
  "metrics": {},
  "hypotheses_tested": 0,
  "holdout_used": false,
  "reviewer": "illustrative data audit",
  "findings": "The file is an explicitly synthetic fixture.",
  "rejection_reasons": ["Genuine observations unavailable"]
}
```

```sh
mkdir -p data
python3 -m scripts.experiment_registry data/research.sqlite init
python3 -m scripts.experiment_registry data/research.sqlite register spec.json examples/ILLUSTRATIVE_mnq_labeled_setups.csv
python3 -m scripts.experiment_registry data/research.sqlite decide illustrative-label-audit-001 decision.json
python3 -m scripts.experiment_registry data/research.sqlite list
python3 -m scripts.experiment_registry data/research.sqlite show illustrative-label-audit-001
```

Initialize the database once. A missing database or unknown experiment ID causes a read or append to fail. Registration hashes the supplied file. Known fixture digests and files named illustrative require the synthetic classification. Other sources are operator-declared `historical`, `synthetic` or `unverified`. A changed dataset or specification needs a new experiment ID.

All windows use UTC epoch milliseconds and half-open intervals `[start, end)`. Training, validation and holdout must be ordered and disjoint. Record all attempted hypotheses in the decision count. If a protocol deviates from the registered plan, record the actual count and rejection reason. Metrics are named finite numeric values. A rejected trial can record an empty set of metrics when an earlier gate prevents evaluation. A retained trial receives the status `RETAINED_FOR_RESEARCH`. Both statuses are research dispositions.

Each registration has one decision. When a decision uses the holdout, the registry checks for overlap against previously evaluated windows on the same dataset ID or the same artifact hash. Prior completed trials count even when rejected. A requested retention with a reused holdout is recorded as a rejection with its original submitted status and conflicting trial IDs. Open or unlogged runs, other registries and related datasets with different names and different bytes can escape this check. Keep a single research history and limit access to the holdout until the challenger is frozen. Record `holdout_used` truthfully, including after a failed evaluation that exposed it.

Append a later observation with its separate artifact.

```sh
python3 -m scripts.experiment_registry data/research.sqlite observe EXPERIMENT_ID observation.json subsequent-observations.csv
```

The observation JSON requires `period` (a half-open UTC millisecond range), `source`, `kind`, `sha256`, positive integer `sample_size`, numeric `metrics` and text `findings`. Supported kinds are `forward_paper`, `forward_live`, `synthetic` and `unverified`. The period must start after the recorded decision and must already have ended. Later observations require fresh bytes and disjoint, chronologically appended periods. Preserve records of deterioration and negative subsequent outcomes. A forward record attests to the submitted artifact and timing. The registry does not authenticate a broker, verify fills or certify an edge.

Each append returns a per-experiment chain digest. Keep a separately protected copy after review. Supply it to `show EXPERIMENT_ID --expected-head DIGEST` to verify an exact checkpoint. Concurrent writes use SQLite transactions. An attempted duplicate registration or decision fails with the original history intact. After an interrupted client request, inspect `show` before retrying. Database owners can replace or roll back an entire file. Backups and externally held digests are necessary to detect that case. Cross-experiment exposure checks scan earlier decided trials and are intended for a local research log.
