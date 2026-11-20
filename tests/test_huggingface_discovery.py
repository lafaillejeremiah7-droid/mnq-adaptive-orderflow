"""Offline tests for Hugging Face market dataset discovery."""
import json
import unittest
from company import huggingface_discovery as hf


def detail(dataset_id, files, license_label="mit", **extra):
    return {
        "id": dataset_id, "sha": "a" * 40,
        "siblings": [{"rfilename": x} for x in files],
        "cardData": {"license": license_label},
        "gated": False, "private": False, "downloads": 20,
        **extra,
    }


class TestHuggingFaceDiscovery(unittest.TestCase):
    def test_identification_of_true_NQ_ohlcv_candidate(self):
        name = "mdelcristo/NQ-F_1min_OHLCV_Parquet"
        record = hf.assess_metadata(name, detail(name, ["NQ_1min_2015.parquet", "NQ_1min_2025.parquet"]))
        self.assertEqual(record["classification"], "NQ_or_MNQ_OHLCV_candidate_unverified")
        self.assertFalse(record["trades_and_size_at_price_proven"])
        self.assertFalse(record["eligible_for_raw_strategy_backtest"])
        self.assertEqual(record["license_label"], "mit")
        self.assertFalse(record["license_is_verified_rights"])

    def test_CFD_is_not_NQ_futures(self):
        name = "CarlosSilva1/ustech-ticks"
        record = hf.assess_metadata(name, detail(name, ["year=2024/month=03/USTECH-2024-03-part0001.parquet"]))
        self.assertEqual(record["classification"], "related_CFD_not_NQ_futures")
        self.assertFalse(record["real_CME_NQ_or_MNQ_proven"])

    def test_unspecified_license_and_missing_data(self):
        name = "example/naive"
        record = hf.assess_metadata(name, detail(name, ["README.md"], None))
        self.assertIsNone(record["license_label"])
        self.assertEqual(record["files_count"], 1)
        self.assertEqual(record["classification"], "not_confirmed_relevant")

    def test_mixed_futures_daily_not_promoted_to_trade_data(self):
        name = "lynx1231/historical-equity-index-futures-data-sample"
        record = hf.assess_metadata(name, detail(name, ["data/daily.parquet"]))
        self.assertEqual(record["classification"], "futures_candidate_requires_instrument_verification")
        self.assertFalse(record["trades_and_size_at_price_proven"])

    def test_fail_closed_on_mismatched_identity(self):
        with self.assertRaisesRegex(ValueError, "mismatched"):
            hf.assess_metadata("test/NQ-trades", detail("bad/other", ["NQ_ticks.csv"]))

    def test_reject_path_injection_and_wrong_endpoint(self):
        for name in ("foo/../../danger", "a", "foo/http://other.com", "foo/bar?x=1"):
            with self.assertRaises(ValueError):
                hf.dataset_detail_url(name)
        with self.assertRaises(ValueError):
            hf.fetch_json("https://evil.example.com/api/datasets")

    def test_search_url_encoding(self):
        self.assertIn("search=NQ+futures", hf.search_url("NQ futures"))
        self.assertIn("limit=3", hf.search_url("NQ", 3))

    def test_discovery_from_mock_hub_with_errors(self):
        nq = "mdelcristo/NQ-F_1min_OHLCV_Parquet"
        cfd = "CarlosSilva1/ustech-ticks"
        def fake(url):
            if "/api/datasets?" in url:
                if "MNQ" in url:
                    raise OSError("rate limited")
                return [{"id": cfd}, {"id": nq}, {"id": "invalid"}]
            if url.endswith(nq):
                return detail(nq, ["NQ_1min_2020.parquet"])
            if url.endswith(cfd):
                return detail(cfd, ["year=2024/USTECH-ticks.parquet"])
            raise ValueError("missing")
        r = hf.discover(get_json=fake, queries=("NQ", "MNQ"), seeds=(nq, cfd), maximum_candidates=6)
        self.assertEqual(len(r["candidates"]), 2)
        self.assertEqual(r["candidates"][0]["dataset_id"], nq)
        self.assertEqual(len(r["failures"]), 1)
        self.assertFalse(r["raw_market_data_downloaded"])
        self.assertIn("metadata-only", hf.markdown_report(r))


if __name__ == "__main__":
    unittest.main()
