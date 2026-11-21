"""Recompute research and adversarial-screen outputs from checksum-pinned inputs.

This is deterministic software replay by the same research algorithms,
NOT independent mathematical verification, market-data authentication,
external validation, or authority to trade.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from company import research_gate, research_lab


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify(study: Path, source: Path) -> dict:
    folder = Path(study)
    source_path = Path(source)
    p_bytes = (folder / "protocol.json").read_bytes()
    r_bytes = (folder / "result.json").read_bytes()
    v_bytes = (folder / "adversarial_review.json").read_bytes()
    receipt = json.loads((folder / "pipeline_receipt.json").read_text())
    p = json.loads(p_bytes)
    result = json.loads(r_bytes)
    review = json.loads(v_bytes)
    raw = source_path.read_bytes()
    engine = Path(research_lab.__file__).read_bytes()
    pipeline_engine = Path(__file__).with_name("research_pipeline.py").read_bytes()
    required = {
        "protocol_sha256": sha(p_bytes),
        "input_sha256": sha(raw),
        "research_engine_sha256": sha(engine),
        "pipeline_engine_sha256": sha(pipeline_engine),
        "result_sha256": sha(r_bytes),
        "adversarial_review_sha256": sha(v_bytes),
    }
    if not isinstance(receipt, dict) or receipt.get("study_id") != p.get("id"):
        raise ValueError("receipt study identity mismatch")
    for name, digest in required.items():
        if receipt.get(name) != digest:
            raise ValueError(f"receipt {name} checksum mismatch")
    if result.get("protocol_sha256") != sha(p_bytes):
        raise ValueError("research result protocol checksum mismatch")
    if result.get("data_sha256") != sha(raw):
        raise ValueError("research result input checksum mismatch")
    if result.get("engine_sha256") != sha(engine):
        raise ValueError("research result engine checksum mismatch")
    expected = research_lab.experiment(p, raw)
    expected["protocol_sha256"] = sha(p_bytes)
    expected["engine_sha256"] = sha(engine)
    if expected != result:
        raise ValueError("research metrics failed exact deterministic replay")
    expected_review = research_gate.audit(
        p_bytes, result, source_bytes=raw, engine_bytes=engine
    )
    if expected_review != review:
        raise ValueError("adversarial review failed exact deterministic replay")
    if (receipt.get("blockers") != [b["code"] for b in review["blockers"]]
            or receipt.get("screen_passed") != review["screen_passed"]):
        raise ValueError("receipt disposition differs from adversarial review")
    if (receipt.get("production_ready") is not False
            or receipt.get("authorization_to_trade") is not False
            or receipt.get("independent_human_validation_completed") is not False):
        raise ValueError("automated receipt improperly certifies independent review or trading")
    return {
        "study_id": p["id"],
        "hashes_match": True,
        "research_replay_matches": True,
        "adversarial_review_replay_matches": True,
        "automated_screen_passed": review["screen_passed"],
        "blockers": receipt["blockers"],
        "independent_math_validation": False,
        "independent_exchange_authentication": False,
        "production_ready": False,
        "authorization_to_trade": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    try:
        outcome = verify(args.study, args.source)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, "research replay rejected: " + str(exc) + "\n")
    print(json.dumps(outcome, sort_keys=True))


if __name__ == "__main__":
    main()
