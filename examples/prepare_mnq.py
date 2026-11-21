"""Recreate the February 2025 MNQH5 experiment data from the pinned source tree."""
import argparse
import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCE = Path("datos brutos/base de datos a corregir/MNQ")
ET = ZoneInfo("America/New_York")


def prepare(root, output):
    files = sorted((root / SOURCE).glob("glbx-mdp3-202502??.ohlcv-1m.MNQH5.csv"))
    if not files:
        raise ValueError("MNQH5 contract files missing from input directory")
    with output.open("x", newline="") as out:
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(["timestamp", "contract", "open", "high", "low", "close"])
        for path in files:
            with path.open() as inp:
                for row in csv.DictReader(inp):
                    stamp = row["ts_event"]
                    local = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(ET)
                    if local.weekday() >= 5 or not 570 <= local.hour*60+local.minute < 960:
                        continue
                    if row["symbol"] != "MNQH5" or not stamp.endswith(":00.000000000Z"):
                        raise ValueError(f"unexpected bar in {path.name}")
                    writer.writerow([stamp[:19]+"Z", row["symbol"], *[row[k] for k in ("open","high","low","close")]])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_checkout", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.source_checkout, args.output)
