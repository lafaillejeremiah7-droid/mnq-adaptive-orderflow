# Quant Researcher Employee #1 — Full Code Audit

Date: 2026-11-20
Repository: lafaillejeremiah7-droid/mnq-adaptive-orderflow
Branch: feature/quant-research-workflow, draft PR #18
DECISION: NOT FINISHED. NO-GO for institutional equivalence or live execution.

## Scope and verification

Reviewed source tree, Python implementations, research/data contracts, risk mathematics,
source-retrieval jobs, test suites and GitHub Actions. Inspected logic in the
research-lab and adversarial-gate modules, risk simulator, volume profile,
Databento converter, five-year NQ study, New York session study, Hugging Face
data discovery, one-day vendor-sample study and older quantlab workflows.

Created a dedicated automated static-analysis/coverage workflow to scan the
Python modules and run all unit tests. Last passing audit: GitHub Actions
run 44839810949, commit 5e5c2c42443b7d454f5bcc841bb93d3bef26a67d.
Result: 90 unit tests pass, Ruff checks for undefined names/common bug
patterns pass, aggregate measured branch coverage = 69%.
Key measured coverage: company/research_lab.py 84%, company/risk_research.py
80%, company/market_profile.py 85%, company/research_gate.py 64%,
quantlab.py 52%, scripts/real_nq_vendor_sample.py 0% in unit suite.
The last script has been separately run via a successful historical-data CI job.
Existing research CI also passes Python 3.11 and 3.12.

## Fixed during audit

FIXED HIGH: Risk simulation mislabeled "target-first". Profit was checked
only at end-of-day, while drawdown was checked after every trade. It could
count a failed drawdown after an earlier qualifying profit target. Fixed to
check target after every completed trade; added adversarial regression test.

FIXED LOW/MEDIUM: Ruff identified 10 findings, mostly unused imports/variables
and ambiguous zip usage. Cleaned those issues.

FIXED HIGH (regression discovered by tests): lint-driven strict zip over an
N-item series and its N-1-item shifted copy always failed. Replaced with
itertools.pairwise, reran tests, and added static-coverage CI.

## Remaining critical blockers

1. DATA: No authenticated licensed multi-year CME NQ/MNQ tick trade, quote
   and book dataset with validated rollover, source completeness and venue
   identity. Multi-year findings use third-party one-minute OHLCV only;
   the individual executed-volume price sample covers one date. Hugging Face
   integration searches metadata only; it does not obtain or certify the
   multi-year exchange data.

2. POINT-IN-TIME LINEAGE: The generic experiment runner checks supplied
   feature-availability timestamps but does not independently prove that the
   upstream features could actually be computed at decision time. Exchange
   calendar, publication delays, contract roll and verified feed reconciliation
   need a separate data-engineering pipeline.

3. SCIENTIFIC PRE-REGISTRATION: Output SHA256 values are integrity evidence,
   not proof of preregistration before the evaluation set was seen. Previously
   inspected historical periods are not fresh holdouts. The user-specified
   hypothesis-family count can omit failed tests.

4. EXECUTION REALISM: No verified quote spread, limit queue, fills, slippage,
   latency, outages, partial orders, exchange margin or validated complete
   prop-firm rulebooks. Trade outcomes omit intratrade adverse excursion, and
   no proven tradable edge or payout probability exists.

5. INDEPENDENT VALIDATION: An automated adversarial review tool rejects weak
   evidence but cannot recreate an independent human sign-off. Although it
   can rehash supplied raw and engine code, it does not independently
   reconstruct all findings from raw market data. Production-ready and
   authorization-to-trade remain false.

## Remaining high-priority engineering blockers

6. MODEL BREADTH: General forecasting is a fixed ridge comparison with at
   most six features and a simple mean baseline. It lacks nested model
   selection, stronger baselines, systematic ablation/placebos, calibrated
   probabilistic models, robust regime comparison and dependency-aware
   uncertainty beyond a day bootstrap/sign test.

7. TEST DEPTH: 69% branch coverage is inadequate to call the system fully
   checked. Important vendor-sample script has 0% unit-suite coverage;
   data adapters, independent reviewer and older engines have low coverage.
   Need multi-provider integration, fuzz/property-based and numerical
   reference tests.

8. AGENT AUTONOMY: researcher.py launches an interactive Codex session. It
   is not an operational research service that independently orchestrates
   data licensing, research planning, time-accurate feature generation,
   blinded evaluation, peer-review and audit publication end-to-end.

9. DEPLOYMENT: All new work remains on draft PR #18. The separate main
   branch remains unchanged. No authorized live/paper deployment is ready.

## Completed as prototype components

- NQ/MNQ CSV validation, volume-at-price descriptive studies with supplied
  actual trade prints, first-touch reaction measurements, one-day vendor-sample
  ingestion and source checks.
- Real third-party historical one-minute NQ descriptive studies for
  2021–2025 and June 2024–October 2026.
- Hugging Face candidate metadata discovery with explicit CFD/stock warnings.
- A deterministic one-contract regression/baseline research harness with
  registered checksums, purged chronological folds and limited uncertainty
  and cost sensitivity.
- A skeptical automated rejection gate.
- A day-block Monte Carlo risk simulator with static and EOD trailing policy,
  corrected trade-level target-first ordering and limited confidence intervals.
- Working unit, static and coverage workflows with recorded results.

## Release gates

- Independently verified multi-year CME market data and point-in-time ETL.
- Actual prior registration with new blind holdout and an audit of every
  candidate including abandoned and failed tests.
- Independent algorithm/data review and exact reproduction by another
  qualified researcher.
- Proper model/baseline calibration and testing across different regimes.
- Independently checked execution costs, fill dynamics, risk and rulebooks.
- Much deeper tests/coverage, monitored operations and deployment approvals.
- Demonstrated blind head-to-head scientific results before claiming to
  surpass professional researchers.

Verdict: Keep the research PR as draft. Passing CI proves only that the
specified software cases execute consistently, not that this is a complete
professional quant researcher or a profitable trading system.

## Native research acceleration added after this audit

An optional C++20 aggregation kernel is now integrated and tested on Python 3.11 and 3.12. It has source/binary SHA-256 in research artifacts, differential checks for complete profile outputs, and two rounds of measured full-profile speedups. This addresses one computational hotspot, NOT the unresolved institutional data, statistical validation, execution, independent review or production-readiness blockers. See docs/CPP_ACCELERATION.md.
