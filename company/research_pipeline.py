"""One-command offline NQ/MNQ experiment and adversarial screening.

Coordinates the existing point-in-time researcher and the automated reviewer,
rehashes input and engine bytes independently within the same process and
writes a pinned receipt. This is NOT an autonomous service, human independent
review, licensed source authentication, or live-trading authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

from company import research_gate, research_lab


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(protocol_path: Path, data_path: Path, output_root: Path) -> Path:
    """Run research, re-read source and engine, fail closed on audit mismatch."""
    protocol_path = Path(protocol_path)
    data_path = Path(data_path)
    output_root = Path(output_root)
    folder = research_lab.run(protocol_path, data_path, output_root)
    engine_path = Path(research_lab.__file__)
    review = research_gate.run(folder, source_path=data_path, engine_path=engine_path)
    if review.get("production_ready") or review.get("authorization_to_trade"):
        raise RuntimeError("automated research gate cannot authorize trading")
    protocol_bytes = (folder / "protocol.json").read_bytes()
    result_bytes = (folder / "result.json").read_bytes()
    review_bytes = (folder / "adversarial_review.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    result = json.loads(result_bytes)
    source_bytes = data_path.read_bytes()
    engine_bytes = engine_path.read_bytes()
    if (fingerprint(source_bytes) != result.get("data_sha256")
            or fingerprint(engine_bytes) != result.get("engine_sha256")
            or fingerprint(protocol_bytes) != result.get("protocol_sha256")):
        raise ValueError("pipeline recheck detected changing source, engine or protocol")
    if (review.get("reviewer_independently_rechecked_raw_bytes") is not True
            or review.get("reviewer_independently_rechecked_engine_bytes") is not True):
        raise RuntimeError("automated review did not independently rehash the inputs")
    receipt = {
        "version": 1,
        "study_id": protocol["id"],
        "pipeline_engine_sha256": fingerprint(Path(__file__).read_bytes()),
        "protocol_sha256": fingerprint(protocol_bytes),
        "input_sha256": fingerprint(source_bytes),
        "research_engine_sha256": fingerprint(engine_bytes),
        "result_sha256": fingerprint(result_bytes),
        "adversarial_review_sha256": fingerprint(review_bytes),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "research_status": result["evidence_status"],
        "screen_passed": review["screen_passed"],
        "blockers": [x["code"] for x in review["blockers"]],
        "independent_exchange_authentication": False,
        "independent_human_validation_completed": False,
        "production_ready": False,
        "authorization_to_trade": False,
        "disposition": "blocked_or_research_only",
        "limitations": [
            "Rechecking bytes in the same process is not independent scientific reproduction.",
            "A protocol SHA-256 is not evidence of preregistration before test inspection.",
            "The pipeline does not create, authenticate or license market data.",
            "Features and execution outcomes remain upstream declarations.",
            "Only an unaffiliated researcher can provide independent review.",
        ],
    }
    with (folder / "pipeline_receipt.json").open("x") as destination:
        json.dump(receipt, destination, indent=2, sort_keys=True)
        destination.write("\n")
    return folder


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("research-runs/pipeline"))
    args = parser.parse_args()
    try:
        folder = run(args.protocol, args.data, args.out)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        parser.exit(2, "research pipeline rejected: " + str(exc) + "\n")
    receipt = json.loads((folder / "pipeline_receipt.json").read_text())
    print(json.dumps({
        "artifacts": str(folder),
        "disposition": receipt["disposition"],
        "blockers": receipt["blockers"],
        "production_ready": False,
    }))


if __name__ == "__main__":
    main()
