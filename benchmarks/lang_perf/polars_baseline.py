"""Rust-backed Polars through Python, same input/aggregation contract.

This makes the comparison more realistic than pure-Python vs hand-written
native binaries alone. Cold Python import time is included for all commands.
"""
import argparse
import json
from pathlib import Path

import polars as pl
from benchmarks.lang_perf.reference import HEADER


def aggregate(path):
    df = pl.read_csv(
        path,
        schema={
            "timestamp_ns": pl.Int64,
            "price_ticks": pl.Int64,
            "size": pl.Int64,
            "side": pl.String,
            "sequence": pl.Int64,
        },
    )
    if df.columns != HEADER.split(",") or df.height == 0:
        raise ValueError("unexpected profile benchmark data")
    if any(x for x in df.null_count().row(0)):
        raise ValueError("missing fields")
    if not df.select(
        (pl.col("timestamp_ns") > 0).all()
        & (pl.col("price_ticks") > 0).all()
        & (pl.col("size") > 0).all()
        & (pl.col("sequence") >= 0).all()
        & pl.col("side").is_in(["B", "A", "N"]).all()
    ).item():
        raise ValueError("bad numeric or side fields")
    invalid_order = df.select(
        (
            (pl.col("timestamp_ns") < pl.col("timestamp_ns").shift(1))
            | (
                (pl.col("timestamp_ns") == pl.col("timestamp_ns").shift(1))
                & (pl.col("sequence") <= pl.col("sequence").shift(1))
            )
        ).fill_null(False).any()
    ).item()
    if invalid_order:
        raise ValueError("unordered events")
    minute = pl.col("timestamp_ns") // 60_000_000_000
    side = pl.col("side")
    size = pl.col("size")
    signed = (
        pl.when(side == "B").then(size)
        .when(side == "A").then(-size)
        .otherwise(0)
    )
    stats = df.select([
        pl.len().alias("rows"),
        size.sum().alias("contracts"),
        (pl.col("price_ticks") * size).sum().alias("weighted_price_ticks"),
        pl.when(side == "B").then(size).otherwise(0).sum().alias("buy_contracts"),
        pl.when(side == "A").then(size).otherwise(0).sum().alias("sell_contracts"),
        pl.when(side == "N").then(size).otherwise(0).sum().alias("unknown_contracts"),
        pl.col("price_ticks").n_unique().alias("unique_prices"),
        minute.n_unique().alias("unique_minutes"),
        (minute * signed).sum().alias("minute_delta_weighted_checksum"),
    ]).row(0, named=True)
    vap_frame = df.group_by("price_ticks").agg(pl.col("size").sum().alias("v"))
    volume = dict(zip(vap_frame["price_ticks"].to_list(), vap_frame["v"].to_list(), strict=True))
    total, weighted = stats["contracts"], stats["weighted_price_ticks"]
    poc = min(volume, key=lambda p: (-volume[p], abs(p*total-weighted), p))
    lo = hi = poc
    covered = volume[poc]
    target = (total*7+9)//10
    lower, upper = min(volume), max(volume)
    while covered < target:
        left = lo-1 if lo>lower else None
        right = hi+1 if hi<upper else None
        if left is None:
            chosen = right
        elif right is None:
            chosen = left
        else:
            vl, vr = volume.get(left, 0), volume.get(right, 0)
            chosen = left if vl>vr or (vl==vr and abs(left*total-weighted)<=abs(right*total-weighted)) else right
        if chosen is None:
            break
        covered += volume.get(chosen, 0)
        lo,hi=min(lo,chosen),max(hi,chosen)
    return {**stats,"poc_ticks":poc,"vah_ticks":hi,"val_ticks":lo}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data",type=Path)
    print(json.dumps(aggregate(parser.parse_args().data),sort_keys=True))


if __name__=="__main__":
    main()
