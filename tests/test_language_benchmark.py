"""Check Python reference benchmark contract and deterministic input generation."""
import tempfile
import unittest
from pathlib import Path

from benchmarks.lang_perf.reference import HEADER, aggregate
from benchmarks.lang_perf.run import synthetic


class BenchmarkTests(unittest.TestCase):
    def test_synthetic_reproducibility_and_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"data.csv"
            synthetic(path, 101)
            first = path.read_bytes()
            synthetic(path, 101)
            self.assertEqual(first, path.read_bytes())
            result = aggregate(path)
            self.assertEqual(result["rows"], 101)
            self.assertEqual(result["contracts"], sum(1+(i*17)%11 for i in range(101)))
            self.assertEqual(
                result["contracts"],
                result["buy_contracts"]+result["sell_contracts"]+result["unknown_contracts"],
            )
            self.assertLessEqual(result["val_ticks"], result["poc_ticks"])
            self.assertGreaterEqual(result["vah_ticks"], result["poc_ticks"])

    def test_duplicates_and_zero_size_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"invalid.csv"
            for body in (
                "1760000000000000000,100,0,B,1\n",
                "1760000000000000000,100,1,B,1\n1760000000000000000,100,1,B,1\n",
            ):
                path.write_text(HEADER+"\n"+body)
                with self.assertRaises(ValueError):
                    aggregate(path)

    def test_tie_rule_and_contiguous_value_area(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"tie.csv"
            path.write_text(
                HEADER+"\n"
                "1760000000000000000,100,5,B,1\n"
                "1760000000000000001,102,5,A,2\n"
                "1760000000000000002,101,1,N,3\n"
            )
            result=aggregate(path)
            self.assertEqual(result["poc_ticks"], 100)
            self.assertEqual((result["val_ticks"], result["vah_ticks"]), (100,102))


if __name__ == "__main__":
    unittest.main()
