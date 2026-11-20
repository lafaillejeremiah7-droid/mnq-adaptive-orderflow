"""Publish a compact receipt or recheck a published run against the original bars."""
import argparse
import json
from pathlib import Path

from quantlab import backtest, check_id, digest, encoded, read, save, validate


def receipt(result):
    return {"result_sha256": digest(encoded(result)),
            "summary": {k: v for k, v in result.items() if k != "trades"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=Path("experiments"))
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("publish").add_argument("id")
    verify = actions.add_parser("verify")
    verify.add_argument("id")
    verify.add_argument("data", type=Path)
    args = parser.parse_args()
    folder = args.ledger / check_id(args.id)
    if args.action == "publish":
        result = read(folder/"result.json")
        save(folder/"receipt.json", receipt(result))
    else:
        protocol = read(folder/"protocol.json")
        validate(protocol["spec"])
        if digest(Path(__file__).with_name("quantlab.py").read_bytes()) != protocol["engine_sha256"]:
            parser.error("check out the registered engine revision")
        result = backtest(protocol["spec"], args.data.read_bytes())
        if read(folder/"receipt.json") != receipt(result):
            parser.error("published receipt does not match reconstructed trades")
        if not (folder/"result.json").exists():
            save(folder/"result.json", result)
        elif (folder/"result.json").read_bytes() != encoded(result):
            parser.error("local fills differ from receipt")
    print(json.dumps({"result_sha256": digest(encoded(result)), "trade_count":result["trade_count"]}))


if __name__ == "__main__":
    main()
