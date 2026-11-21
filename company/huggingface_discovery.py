"""Search Hugging Face for NQ/MNQ market datasets and audit *metadata only*.

No datasets are downloaded or treated as exchange-authenticated. Candidate
status requires follow-up validation of instrument, schema, history, timezone,
license, source provenance, data quality, and contract/rollover treatment.
Uses public Hub REST API and Python standard library; no API key required.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://huggingface.co"
SEARCH_TERMS = ("NQ", "MNQ", "NQ-F", "Nasdaq", "CME", "USTECH")
SEED_DATASETS = (
    "mdelcristo/NQ-F_1min_OHLCV_Parquet",
    "lynx1231/historical-equity-index-futures-data-sample",
    "CarlosSilva1/ustech-ticks",
    "syncster-data/us-market-1m-data",
)
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
SUPPORTED_EXTS = (".parquet", ".csv", ".csv.gz", ".arrow", ".jsonl", ".jsonl.gz")
MAX_RESPONSE_BYTES = 5_000_000
MAX_SIBLINGS_IN_REPORT = 20


def fetch_json(url: str) -> dict | list:
    """Fixed-host read-only metadata transport; never a general URL fetcher."""
    if not (url.startswith(BASE + "/api/datasets?") or url.startswith(BASE + "/api/datasets/")):
        raise ValueError("only Hugging Face dataset metadata endpoints are allowed")
    req = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": "NQ-Quant-Researcher-Dataset-Audit/1.0"
    })
    with urllib.request.urlopen(req, timeout=25) as response:
        content = response.read(MAX_RESPONSE_BYTES + 1)
    if len(content) > MAX_RESPONSE_BYTES:
        raise ValueError("Hub metadata response exceeds size limit")
    return json.loads(content.decode("utf-8"))


def dataset_detail_url(dataset_id: str) -> str:
    if not IDENTIFIER.fullmatch(dataset_id):
        raise ValueError("unsafe or invalid dataset identifier")
    return BASE + "/api/datasets/" + urllib.parse.quote(dataset_id, safe="/")


def search_url(term: str, limit: int = 25) -> str:
    if not isinstance(term, str) or not term or len(term) > 80:
        raise ValueError("invalid search term")
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("invalid search limit")
    return BASE + "/api/datasets?" + urllib.parse.urlencode({
        "search": term, "limit": limit
    })


def _file_paths(obj: dict) -> list[str]:
    siblings = obj.get("siblings") or []
    if not isinstance(siblings, list):
        return []
    return [
        s["rfilename"] for s in siblings
        if isinstance(s, dict) and isinstance(s.get("rfilename"), str)
    ]


def assess_metadata(dataset_id: str, detail: dict) -> dict:
    """Never infer verified CME data solely from title or declared tags."""
    if not IDENTIFIER.fullmatch(dataset_id):
        raise ValueError("invalid repo id")
    if not isinstance(detail, dict):
        raise ValueError("invalid HF dataset metadata")
    if detail.get("id") and detail["id"].lower() != dataset_id.lower():
        raise ValueError("mismatched dataset metadata identity")
    files = _file_paths(detail)
    card = detail.get("cardData") or {}
    if not isinstance(card, dict):
        card = {}
    license_label = card.get("license")
    if isinstance(license_label, list):
        license_label = ",".join(str(x) for x in license_label)
    if not isinstance(license_label, str) or not license_label.strip():
        license_label = None
    tags = detail.get("tags") or []
    tags = [x for x in tags if isinstance(x, str)] if isinstance(tags, list) else []
    if license_label is None:
        tagged = [x[8:] for x in tags if x.startswith("license:")]
        if tagged:
            license_label = tagged[0]
    direct = dataset_id.lower() + " " + " ".join(files[:150]).lower()
    # "NQ" also refers to the huge unrelated Natural Questions NLP corpus.
    # Parquet is a storage format, NOT evidence of OHLCV or market data.
    has_nq = bool(
        re.search(r"(?<![a-z0-9])(?:mnq|nq)(?![a-z0-9])", direct)
        or re.search(r"(?<![a-z0-9])(?:mnq|nq)[hmuz][0-9]{1,4}(?![a-z0-9])", direct)
    )
    has_cfd = bool(re.search(r"ustech|cfd|us100|nas100", direct))
    has_futures = bool(re.search(r"(?<![a-z])futures?(?![a-z])", direct))
    financial_markers = bool(re.search(
        r"nasdaq|ohlcv|market.?data|trading|financial|price.?bars?|(?<![a-z])"
        r"(?:1min|1m|minute|candles?|bid.?ask|orderbook|volume.?profile)(?![a-z])|"
        r"(?:mnq|nq)[hmuz][0-9]{1,4}(?![a-z0-9])|nq-f(?![a-z])",
        direct,
    ))
    market_context = financial_markers or has_futures
    has_ohlcv = bool(re.search(r"ohlcv|1min|1m_|1m-|(?:price|minute).?bars?", direct))
    has_tick = bool(re.search(r"ticks?|trades?|orderbook|market-by-order|(?<![a-z])mbo(?![a-z])", direct))
    contains_data_files = any(path.lower().endswith(SUPPORTED_EXTS) for path in files)
    if has_cfd:
        classification = "related_CFD_not_NQ_futures"
    elif has_nq and market_context and has_tick:
        classification = "NQ_or_MNQ_tick_candidate_unverified"
    elif has_nq and market_context and has_ohlcv:
        classification = "NQ_or_MNQ_OHLCV_candidate_unverified"
    elif has_nq and market_context or has_futures:
        classification = "futures_candidate_requires_instrument_verification"
    elif financial_markers:
        classification = "broader_financial_data_verify_NQ_presence"
    else:
        classification = "not_confirmed_relevant"
    gated = detail.get("gated", False)
    private = bool(detail.get("private", False))
    rank = {
        "NQ_or_MNQ_tick_candidate_unverified": 90,
        "NQ_or_MNQ_OHLCV_candidate_unverified": 80,
        "futures_candidate_requires_instrument_verification": 45,
        "broader_financial_data_verify_NQ_presence": 25,
        "related_CFD_not_NQ_futures": 15,
        "not_confirmed_relevant": 0,
    }[classification]
    if not contains_data_files:
        rank -= 15
    if gated or private:
        rank -= 5
    claims = {
        "dataset_id": dataset_id,
        "url": BASE + "/datasets/" + dataset_id,
        "revision_sha": detail.get("sha"),
        "classification": classification,
        "ranking_score": rank,
        "license_label": license_label,
        "license_is_verified_rights": False,
        "gated": gated,
        "private": private,
        "last_modified": detail.get("lastModified"),
        "downloads_count": detail.get("downloads"),
        "files_count": len(files),
        "data_file_paths_sample": [
            p for p in files if p.lower().endswith(SUPPORTED_EXTS)
        ][:MAX_SIBLINGS_IN_REPORT],
        "file_types": sorted({p.rsplit(".", 1)[-1].lower() for p in files
                              if p.lower().endswith(SUPPORTED_EXTS)}),
        "real_CME_NQ_or_MNQ_proven": False,
        "complete_years_coverage_proven": False,
        "trades_and_size_at_price_proven": False,
        "timestamp_timezone_proven": False,
        "contract_rollover_policy_proven": False,
        "data_integrity_proven": False,
        "eligible_for_raw_strategy_backtest": False,
        "limitations": [
            "HF metadata is only a candidate discovery signal; no rows were downloaded or verified.",
            "A license label does not establish the publisher's rights to exchange market data.",
            "Nasdaq index CFDs, QQQ, equities and synthetic data are NOT equivalent to CME NQ/MNQ executed trades.",
            "OHLCV minute bars cannot reconstruct volume-at-price, trade delta, book depth or absorption.",
        ],
    }
    return claims


def discover(get_json=fetch_json, queries=SEARCH_TERMS, seeds=SEED_DATASETS,
             search_limit=25, maximum_candidates=32) -> dict:
    """Search and inspect bounded metadata; explicit failures are retained."""
    identifiers = []
    failures = []
    terms = {}
    for term in queries:
        url = search_url(term, search_limit)
        try:
            search_result = get_json(url)
            if not isinstance(search_result, list):
                raise ValueError("search endpoint did not return a list")
            found = []
            for record in search_result:
                if isinstance(record, dict):
                    name = record.get("id")
                    if isinstance(name, str) and IDENTIFIER.fullmatch(name):
                        found.append(name)
                        identifiers.append(name)
            terms[term] = {"returned": len(found), "endpoint": url}
        except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            terms[term] = {"error": type(exc).__name__ + ": " + str(exc)}
            failures.append({"query": term, "error": str(exc)})
    # Explicit references are always inspected, even when Hub search changes.
    # The very common "NQ" in the NLP Natural Questions benchmark otherwise
    # fills the first search page and crowds out market-data candidates.
    market_name = re.compile(
        r"nq-f(?![a-z])|(?:mnq|nq)[hmuz][0-9]{1,4}|ustech|nasdaq|futures?|"
        r"cme|ohlcv|1min|market|intraday|tick|orderbook",
        flags=re.IGNORECASE,
    )
    prioritized = [x for x in identifiers if market_name.search(x)]
    ordered = list(dict.fromkeys([*seeds, *prioritized]))
    if len(ordered) > maximum_candidates:
        ordered = ordered[:maximum_candidates]
    assessed = []
    for dataset_id in ordered:
        try:
            detail = get_json(dataset_detail_url(dataset_id))
            assessed.append(assess_metadata(dataset_id, detail))
        except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            failures.append({"dataset_id": dataset_id, "error": type(exc).__name__ + ": " + str(exc)})
    discarded_irrelevant = sum(x["classification"] == "not_confirmed_relevant" for x in assessed)
    assessed = [x for x in assessed if x["classification"] != "not_confirmed_relevant"]
    assessed.sort(key=lambda x: (-x["ranking_score"], x["dataset_id"].casefold()))
    return {
        "employee": "quant-researcher-001",
        "source": "Hugging Face public dataset metadata API",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "purpose": "Find candidate market datasets; never automatically trust them",
        "search_terms": terms,
        "candidate_count": len(assessed),
        "discarded_unrelated_search_results": discarded_irrelevant,
        "excluded_search_ids_without_market_context": len(set(identifiers) - set(ordered)),
        "candidates": assessed,
        "failures": failures,
        "raw_market_data_downloaded": False,
        "research_edge_validated": False,
        "promotion_gate": [
            "Verify publisher permission, exchange redistribution rights, and actual license terms.",
            "Download bounded samples from a pinned revision and hash the bytes.",
            "Inspect true columns, instrument identity, contract code, timestamp timezone, cadence and coverage.",
            "Check duplicates, missing periods, order, rollover policy, scale and trade/quote definitions.",
            "Classify as OHLCV, executed trade prices/sizes, or book updates before selecting research.",
            "Keep old/hypothesis-seen datasets separate from fresh holdouts.",
        ],
    }


def markdown_report(result: dict) -> str:
    lines = [
        "# Hugging Face market-dataset discovery for NQ/MNQ", "",
        "Generated UTC: " + result["generated_utc"], "",
        "**This is a metadata-only audit, not a verified market-data acquisition.**",
        "Hugging Face dataset claims and license labels are not exchange authenticity certificates.",
        "Unrelated NLP/other search results filtered: " + str(result.get("discarded_unrelated_search_results", 0)), "",
        "| Candidate dataset | Classification | License label | Files | Review |",
        "|---|---|---|---:|---|",
    ]
    for c in result["candidates"]:
        lines.append("| [{0}]({1}) | {2} | {3} | {4} | {5} |".format(
            c["dataset_id"], c["url"], c["classification"],
            c["license_label"] or "unspecified", c["files_count"],
            "gated" if c["gated"] or c["private"] else "inspect rows + rights"
        ))
    lines += ["", "## Search API coverage", ""]
    for term, outcome in result["search_terms"].items():
        lines.append("- " + term + ": " + str(outcome.get("returned", outcome.get("error"))))
    if result["failures"]:
        lines += ["", "## Lookup failures", ""]
        for failed in result["failures"]:
            lines.append("- " + str(failed))
    lines += ["", "## Validation before any quantitative experiment", ""]
    lines.extend("- " + s for s in result["promotion_gate"])
    lines += ["", "Dataset files were not downloaded; no backtest was run. Market data rights remain unverified.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("studies/huggingface-discovery"))
    args = parser.parse_args()
    outcome = discover()
    if not outcome["candidates"]:
        parser.exit(2, "Hugging Face candidate discovery failed: no inspectable datasets\n")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "candidates.json").write_text(
        json.dumps(outcome, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    (args.output / "report.md").write_text(markdown_report(outcome))
    print(json.dumps({
        "candidate_count": outcome["candidate_count"],
        "failures": len(outcome["failures"]),
        "top": [x["dataset_id"] for x in outcome["candidates"][:6]],
    }))


if __name__ == "__main__":
    main()
