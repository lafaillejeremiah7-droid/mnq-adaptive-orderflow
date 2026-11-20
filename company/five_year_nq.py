"""Five-year empirical NQ research, 2021-2025, via pinned public 1m CSVs.

Timestamp timezone is undocumented in the source. No session inference,
no volume-at-price inference, no orders, no untested alpha claims.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import random
import statistics
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

SOURCE_REPO = "tdtrader76/NQ_Backtest"
SOURCE_COMMIT = "7ac6bd20d3fa46b25fa6d2db947200ef9860c6ef"
FILES = {
  2021: ("6257ed4b54cb2ed598dba3660b3397795bf3e745", 19843057),
  2022: ("77a8fae1283ef5a24385e47ad47bcb156c65b00f", 15386387),
  2023: ("5b3e186e783ba1ffd2a0cfb51295ff328157eb63", 19955662),
  2024: ("34b93384444426239312707ee92683b50c8e94a5", 19897930),
  2025: ("131adf871a9fce789e252aee71ae6737f1dcb32f", 16900814),
}
HEADERS = ["DateTime","Open","High","Low","Close","Volume"]
SEED = 20261120


def verify_blob(data, expected):
    actual = hashlib.sha1(b"blob " + str(len(data)).encode() + bytes([0]) + data).hexdigest()
    if actual != expected:
        raise ValueError("GitHub blob integrity mismatch")
    return hashlib.sha256(data).hexdigest()


def fetch_year(year):
    ref, length = FILES[year]
    path = "Procesados/{}/NQ_1min_{}.csv".format(year,year)
    url = "https://raw.githubusercontent.com/{}/{}/{}".format(SOURCE_REPO,SOURCE_COMMIT,path)
    with urllib.request.urlopen(url, timeout=120) as response:
        content = response.read(length + 1)
    if len(content) != length:
        raise ValueError("source length mismatch for year {}".format(year))
    return content, {"url":url, "git_sha1":ref, "sha256":verify_blob(content,ref), "bytes":length}


def range_bps(row):
    prices = [float(row[x]) for x in ("Open","High","Low","Close")]
    o,h,l,c=prices
    if not all(math.isfinite(x) and 0 < x < 1e6 and abs(x*4-round(x*4)) < 1e-6 for x in prices):
        raise ValueError("invalid NQ tick price")
    if not l <= min(o,c) <= max(o,c) <= h:
        raise ValueError("inconsistent OHLC")
    if not float(row["Volume"]).is_integer() or int(row["Volume"]) <= 0:
        raise ValueError("invalid volume")
    return 10000.0*(h-l)/o


def parse_year(raw, year):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if reader.fieldnames != HEADERS:
        raise ValueError("unexpected yearly CSV schema")
    past_time = None
    past_range = None
    pairs, daily = [], set()
    ranges = []
    discontinuities = 0
    first_time = None
    for row in reader:
        if set(row) != set(HEADERS) or any(v is None for v in row.values()):
            raise ValueError("missing or extra source field")
        dt = datetime.strptime(row["DateTime"],"%Y-%m-%d %H:%M:%S")
        if dt.year != year or (past_time is not None and dt <= past_time):
            raise ValueError("unsorted or out-of-year timestamp")
        first_time = first_time or dt
        this_range = range_bps(row)
        ranges.append(this_range)
        daily.add(dt.date().isoformat())
        if past_time is not None:
            if dt - past_time == timedelta(minutes=1) and dt.date() == past_time.date():
                pairs.append((dt.date().isoformat(),past_range,this_range))
            else:
                discontinuities += 1
        past_time,past_range=dt,this_range
    if len(pairs) < 10:
        raise ValueError("no adequate contiguous minute pairs")
    return pairs, {
      "year":year,"rows":len(ranges),"calendar_dates":len(daily),
      "contiguous_pairs":len(pairs),"discontinuities_or_day_boundaries":discontinuities,
      "first_naive_timestamp":first_time.isoformat(),
      "last_naive_timestamp":past_time.isoformat(),
      "median_one_minute_range_bps":statistics.median(ranges),
      "timezone":"unknown: no America/New_York assumption",
    }


def quantile(items,fraction):
    if not items:
        raise ValueError("empty quantile")
    values=sorted(items)
    return values[int((len(values)-1)*fraction)]


def paired_bootstrap(values,seed=SEED):
    if not values:
        return {"dates":0,"median_difference_bps":None,"bootstrap_95pct":None}
    rng=random.Random(seed)
    n=len(values)
    sims=sorted(statistics.median(rng.choices(values,k=n)) for _ in range(2000))
    return {
      "dates":n,
      "median_difference_bps":statistics.median(values),
      "mean_difference_bps":statistics.mean(values),
      "bootstrap_95pct":[sims[50],sims[1949]],
      "positive_days":sum(x>0 for x in values),
      "negative_days":sum(x<0 for x in values),
    }


def frozen_holdout(train,test):
    low=quantile([row[1] for row in train],0.2)
    high=quantile([row[1] for row in train],0.8)
    if high <= low:
        raise ValueError("training thresholds are degenerate")
    daily=defaultdict(lambda:[[],[]])
    observations=[0,0]
    for date,lagged,next_range in test:
        if lagged <= low:
            daily[date][0].append(next_range)
            observations[0]+=1
        elif lagged >= high:
            daily[date][1].append(next_range)
            observations[1]+=1
    differences={}
    for date,(lo,hi) in daily.items():
        if len(lo)>=5 and len(hi)>=5:
            differences[date]=statistics.mean(hi)-statistics.mean(lo)
    slices={}
    for year in (2024,2025):
        sample=[v for k,v in differences.items() if k.startswith(str(year))]
        slices[str(year)]={"eligible_dates":len(sample),
                           "median_effect_bps":statistics.median(sample) if sample else None,
                           "positive_date_share":sum(x>0 for x in sample)/len(sample) if sample else None}
    return {
      "question":"Does prior 1m intrabar range forecast next 1m intrabar range?",
      "quantity":"(high-low)/open*10000 basis points",
      "calibration_years":[2021,2022,2023],"holdout_years":[2024,2025],
      "predeclared_comparison":"bottom versus top quintile of previous 1m normalized range",
      "thresholds_trained_only_on_2021_2023_bps":{"bottom_20pct":low,"top_20pct":high},
      "test_observations_after_low":observations[0],
      "test_observations_after_high":observations[1],
      "date_paired_holdout_effect":paired_bootstrap(list(differences.values())),
      "holdout_year_slices":slices,
      "no_entry_or_exit_or_costs_or_PNL_tested":True
    }


def research(download=fetch_year):
    train,test=[],[]
    manifest={}
    coverage={}
    for year in sorted(FILES):
        raw,provenance=download(year)
        pairs,stats=parse_year(raw,year)
        coverage[str(year)]=stats
        manifest[str(year)]=provenance
        if year<=2023:
            train.extend(pairs)
        else:
            test.extend(pairs)
        print(json.dumps({"year":year,"bars":stats["rows"],"sha256":provenance["sha256"]}),flush=True)
    return {
      "researcher":"quant-researcher-001",
      "period":"2021-2025 inclusive",
      "source_repo":SOURCE_REPO,"source_commit":SOURCE_COMMIT,
      "source_pinned_blobs":manifest,"annual_coverage":coverage,
      "frozen_holdout":frozen_holdout(train,test),
      "data_type":"historical_NQ_one_minute_OHLCV",
      "volume_at_price_computable":False,
      "independent_CME_data_authenticity_verified":False,
      "tradable_edge_validated":False,
      "limits":[
        "Public third-party NinjaTrader files; exchange authenticity and rights not independently verified.",
        "Quarterly contracts stitched and duplicates deleted by source processing.",
        "Source timestamps have no recorded time zone; no session-specific claims.",
        "OHLCV cannot reconstruct POC, VAH, VAL, HVN, LVN, footprint or absorption.",
        "Consecutive-bar observations are serially correlated; daily bootstrap is descriptive.",
        "This is one held-out hypothesis, not a trading-system validation.",
        "No spread, queue, execution costs, trade entries or positions were simulated."
      ]
    }


def report(result):
    h=result["frozen_holdout"]
    d=h["date_paired_holdout_effect"]
    lines=[
      "# Five years of real historical NQ one-minute data: 2021–2025","",
      "**Pinned public third-party NinjaTrader exports; not synthetic.**",
      "The files were checked against Git object fingerprints. This does not establish CME-origin authenticity.","",
      "## Hypothesis",
      h["question"],
      "Training: 2021–2023. Frozen holdout: 2024–2025.",
      "Predictor: prior one-minute high-low normalized by open; result: next contiguous minute range in basis points.","",
      "Lower threshold {:.4f} bps, upper threshold {:.4f} bps.".format(
        h["thresholds_trained_only_on_2021_2023_bps"]["bottom_20pct"],
        h["thresholds_trained_only_on_2021_2023_bps"]["top_20pct"]),
      "Holdout observations after low: {:,}; after high: {:,}.".format(
        h["test_observations_after_low"],h["test_observations_after_high"]),
      "Eligible paired days: {}.".format(d["dates"]),
      "Median daily high-minus-low conditional next-bar difference: {} bps.".format(d["median_difference_bps"]),
      "Exploratory date-bootstrap interval: {} bps.".format(d["bootstrap_95pct"]),"",
      "| Year | Real bars | Calendar dates | Median 1m range (bps) |",
      "|---|---:|---:|---:|"
    ]
    for year,stats in sorted(result["annual_coverage"].items()):
        lines.append("| {} | {:,} | {:,} | {:.3f} |".format(year,stats["rows"],stats["calendar_dates"],stats["median_one_minute_range_bps"]))
    lines += ["","Holdout splits: "+json.dumps(h["holdout_year_slices"],sort_keys=True),"",
      "## Critical limits",""] + ["- "+x for x in result["limits"]]
    lines += ["","No profitability or actual volume-profile claim is supported.","",
      "Source revision: https://github.com/"+SOURCE_REPO+"/tree/"+SOURCE_COMMIT,
      "Manifest contains all SHA-256 file fingerprints. Raw files are not redistributed.",""]
    return "\n".join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,default=Path("studies/nq-five-year-2021-2025"))
    args=parser.parse_args()
    result=research()
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/"summary.json").write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n")
    (args.out/"report.md").write_text(report(result))
    print(json.dumps({"success":True,"dates":result["frozen_holdout"]["date_paired_holdout_effect"]["dates"]}))


if __name__=="__main__":
    main()
