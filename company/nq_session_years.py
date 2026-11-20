"""2024–2026 real historical NQ New York session comparison.

A separate pinned multi-provider bar source explicitly labels ET and RTH.
Bars cannot recover volume-by-price, passive absorption or an execution edge.
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import random
import statistics
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO="kfccolonel1/BARS"
COMMIT="b8f2d8ab36e44c289036ce093bf7c9f04073a7d9"
PATH="NQ/1min/NQ_1min_continuous.csv.gz"
BLOB="83214fdbf39adc379e2735da6364d4d3eea4e984"
EXPECTED_SIZE=10663386
NY=ZoneInfo("America/New_York")
COLUMNS=["datetime","open","high","low","close","volume","source","trading_date","session"]


def verify(data):
    if len(data)!=EXPECTED_SIZE:
        raise ValueError("historical source length changed")
    actual=hashlib.sha1(b"blob "+str(len(data)).encode()+bytes([0])+data).hexdigest()
    if actual!=BLOB:
        raise ValueError("Git source fingerprint changed")
    return hashlib.sha256(data).hexdigest()


def download():
    url=f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{PATH}"
    with urllib.request.urlopen(url,timeout=120) as response:
        data=response.read(EXPECTED_SIZE+1)
    return data,{"url":url,"sha256":verify(data),"git_blob_sha1":BLOB}


def compute(pairs):
    vals=[p["opening_minus_midday_bps"] for p in pairs.values()]
    if not vals:
        return {"n":0,"median":None,"bootstrap_95pct":None}
    rng=random.Random(20261120)
    simulations=sorted(statistics.median(rng.choices(vals,k=len(vals))) for _ in range(2000))
    return {
      "n":len(vals),"median":statistics.median(vals),"mean":statistics.mean(vals),
      "positive_share":sum(x>0 for x in vals)/len(vals),
      "bootstrap_95pct":[simulations[50],simulations[1949]],
    }


def analyze(raw):
    rdr=csv.DictReader(io.StringIO(gzip.decompress(raw).decode("utf-8-sig")))
    if rdr.fieldnames!=COLUMNS:
        raise ValueError("unexpected session CSV schema")
    time_last=None
    dates=defaultdict(lambda:[{},{}])
    all_rows=Counter()
    source_mix=Counter()
    first=last=None
    for row in rdr:
        if set(row)!=set(COLUMNS) or any(v is None for v in row.values()):
            raise ValueError("invalid bar fields")
        ts=datetime.fromisoformat(row["datetime"])
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise ValueError("timezone offset missing")
        if time_last is not None and ts<=time_last:
            raise ValueError("timestamps must be ordered and unique")
        first=first or ts
        last=time_last=ts
        local=ts.astimezone(NY)
        minute=local.hour*60+local.minute
        prices=[float(row[x]) for x in ("open","high","low","close")]
        o,h,l,c=prices
        if not all(math.isfinite(x) and 0<x<1e6 and abs(x*4-round(x*4))<1e-6 for x in prices):
            raise ValueError("invalid price grid")
        if not l<=min(o,c)<=max(o,c)<=h:
            raise ValueError("invalid OHLC")
        vol=row["volume"]
        if vol and (not math.isfinite(float(vol)) or float(vol)<0):
            raise ValueError("invalid volume")
        all_rows[str(local.year)]+=1
        source_mix[row["source"]]+=1
        if row["session"]!="RTH" or local.weekday()>4:
            continue
        day=local.date().isoformat()
        width=10000*(h-l)/o
        if 570<=minute<600:
            if minute in dates[day][0]:
                raise ValueError("duplicate opening minute")
            dates[day][0][minute]=width
        elif 720<=minute<750:
            if minute in dates[day][1]:
                raise ValueError("duplicate midday minute")
            dates[day][1][minute]=width
    included={}
    excluded=Counter()
    for day,(opening,midday) in sorted(dates.items()):
        if set(opening)!=set(range(570,600)) or set(midday)!=set(range(720,750)):
            excluded[day[:4]]+=1
            continue
        a=statistics.mean(opening.values())
        b=statistics.mean(midday.values())
        included[day]={"opening_range_bps":a,"midday_range_bps":b,"opening_minus_midday_bps":a-b}
    by_year={}
    for year in sorted({date[:4] for date in included}):
        subset={k:v for k,v in included.items() if k.startswith(year)}
        by_year[year]=compute(subset)
    return {
      "question":"Is mean one-minute range larger at the 09:30 New York open than at 12:00?",
      "source_range":[first.isoformat(),last.isoformat()],
      "observed_bars_by_year":dict(all_rows),
      "observed_bars_by_source":dict(source_mix),
      "complete_day_count":len(included),
      "incomplete_observed_days":dict(excluded),
      "all_day_paired_effect_bps":compute(included),
      "per_year":by_year,
      "unit_of_analysis":"one paired New York date, not an independent minute",
      "data_type":"third-party NQ continuous one-minute OHLCV; may have contract roll jumps",
      "as_of_context":"previously available public historical data, exploratory",
      "trade_by_price_reconstruction_available":False,
      "tradable_edge_validated":False
    }


def report(data):
    lines=[
      "# NQ opening versus midday range across 2024–2026", "",
      "Third-party market bars from a Git commit-pinned public file. The file explicitly supplies New York timestamps and sessions.",
      "The source mixes providers and has unadjusted futures roll discontinuities. This is NOT verified CME tick history.", "",
      "Hypothesis: average one-minute (high-low)/open bps is greater during 09:30–09:59 ET than 12:00–12:29 ET.",
      "Only dates with all 60 required minute bars were included.", "",
      "Total complete paired dates: {}.".format(data["complete_day_count"]),
      "Overall date-paired result: "+str(data["all_day_paired_effect_bps"]),"",
      "| Year | Complete paired dates | Median open-minus-midday (bps) | Opening larger share |",
      "|---|---:|---:|---:|",
    ]
    for year,stats in sorted(data["per_year"].items()):
        lines.append("| {} | {} | {:.4f} | {:.1%} |".format(
            year,stats["n"],stats["median"],stats["positive_share"]))
    lines += ["","## Interpretation limits","",
      "- Descriptive price-range seasonality does not forecast direction or establish profitable trade entries.",
      "- This series is not an untouched holdout after prior exploratory investigations.",
      "- Dates and intraday observations may be dependent; interval resamples dates as blocks.",
      "- Vendor composition changes, missing volume and front-month rolls limit generalization.",
      "- One-minute OHLCV has no actual volume-at-price, POC/VAH/VAL/HVN/LVN or order-book imbalance.",
      "- No exchange-level authenticity verification, fill model, trading-cost model or broker connection.",
      "", "Pinned data file: https://github.com/"+REPO+"/blob/"+COMMIT+"/"+PATH,
      "Aggregate report only. Raw vendor files are not redistributed.",""]
    return "\n".join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",type=Path,default=Path("studies/nq-session-years-2024-2026"))
    args=p.parse_args()
    raw,provenance=download()
    result=analyze(raw)
    result["source_manifest"]=provenance
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/"summary.json").write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n")
    (args.out/"report.md").write_text(report(result))
    print(json.dumps({"complete_dates":result["complete_day_count"],"by_year":result["per_year"]}))


if __name__=="__main__":
    main()
