"""Offline MBP-1 pretty-price adapter synthetic fixtures."""
import csv
import io
import unittest

from company import databento_bbo_csv as adapter
from company import execution_replay as replay


def vendor(rows):
    out = io.StringIO()
    columns = sorted(adapter.COLUMNS)
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return out.getvalue().encode()


def record(**updates):
    row = {
        "ts_event": "2026-11-20T15:00:00.000000001Z",
        "ts_recv": "2026-11-20T15:00:00.000000050Z",
        "sequence": "100", "symbol": "MNQZ6", "rtype": "1",
        "publisher_id": "1", "instrument_id": "777",
        "flags": str(adapter.LAST_FLAG),
        "action": "M", "bid_px_00": "21000.00",
        "bid_sz_00": "10", "ask_px_00": "21000.25",
        "ask_sz_00": "12",
    }
    return {**row, **updates}


class DatabentoMbpAdapterTests(unittest.TestCase):
    def test_normalizes_pretty_price_to_nq_ticks(self):
        raw = vendor([record()])
        transformed, receipt = adapter.convert(raw, "MNQZ6")
        self.assertIn(b"84000,10,84001,12,100", transformed)
        self.assertEqual(receipt["records"], 1)
        self.assertFalse(receipt["independent_license_verification"])
        spec = {
            "contract": "MNQZ6", "source_sha256": receipt["output_sha256"],
            "source_kind": "synthetic", "provider": "synthetic",
            "schema": "top_of_book_v1", "rights_status": "unverified",
            "fees_per_contract_usd": "1", "conservative_slippage_ticks": 1,
            "max_quote_age_ns": 10000, "max_spread_ticks": 5, "max_records": 10,
        }
        quotes = replay.read_quotes(transformed, spec)
        self.assertEqual(quotes[0].ask, 84001)

    def test_discard_intermediate_and_accept_last(self):
        first = record(flags="0", sequence="99")
        last = record()
        raw = vendor([first, last])
        payload, summary = adapter.convert(raw, "MNQZ6")
        self.assertEqual(summary["discarded_intermediate_event_rows"], 1)
        self.assertEqual(len(payload.splitlines()), 2)

    def test_rejects_bad_timestamp_flag_and_book_reset(self):
        for bad in ({"flags": "136"}, {"action": "R"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                adapter.convert(vendor([record(**bad)]), "MNQZ6")

    def test_rejects_mixed_instrument_and_wrong_schema(self):
        a = record(flags="0", sequence="99")
        b = record(instrument_id="778")
        with self.assertRaisesRegex(ValueError, "instrument_id"):
            adapter.convert(vendor([a, b]), "MNQZ6")
        with self.assertRaisesRegex(ValueError, "rtype"):
            adapter.convert(vendor([record(rtype="160")]), "MNQZ6")

    def test_rejects_crossed_or_unscaled_prices_and_unmapped_symbols(self):
        with self.assertRaisesRegex(ValueError, "crossed"):
            adapter.convert(vendor([record(bid_px_00="21001.00")]), "MNQZ6")
        with self.assertRaises(ValueError):
            adapter.convert(vendor([record(bid_px_00="21000.01")]), "MNQZ6")
        with self.assertRaisesRegex(ValueError, "mixed symbols"):
            adapter.convert(vendor([record(symbol="NQZ6")]), "MNQZ6")
