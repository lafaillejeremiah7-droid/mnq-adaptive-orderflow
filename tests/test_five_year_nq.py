"""Unit tests for five-year historical NQ research, all fixtures synthetic."""
import hashlib
import unittest

from company import five_year_nq as research


def fixture(year):
    return (
        "DateTime,Open,High,Low,Close,Volume\n"
        f"{year}-04-05 09:30:00,100,101,99,100,10\n"
        f"{year}-04-05 09:31:00,100,101.25,98.75,100,20\n"
        f"{year}-04-05 09:32:00,100,101.5,98.5,100,30\n"
        f"{year}-04-05 09:33:00,100,101.75,98.25,100,40\n"
        f"{year}-04-05 09:34:00,100,102,98,100,50\n"
        f"{year}-04-05 09:35:00,100,102.25,97.75,100,60\n"
        f"{year}-04-05 09:36:00,100,102.5,97.5,100,70\n"
        f"{year}-04-05 09:37:00,100,102.75,97.25,100,80\n"
        f"{year}-04-05 09:38:00,100,103,97,100,90\n"
        f"{year}-04-05 09:39:00,100,103.25,96.75,100,100\n"
        f"{year}-04-05 09:40:00,100,103.5,96.5,100,110\n"
    ).encode()


class Tests(unittest.TestCase):
    def test_fingerprint_blocks_mutation(self):
        raw=b"hello"
        blob=hashlib.sha1(b"blob 5"+bytes([0])+raw).hexdigest()
        self.assertEqual(research.verify_blob(raw,blob),hashlib.sha256(raw).hexdigest())
        with self.assertRaises(ValueError):
            research.verify_blob(raw,b"0"*40)

    def test_parse_real_schema_and_time(self):
        items,coverage=research.parse_year(fixture(2021),2021)
        self.assertEqual(len(items),10)
        self.assertEqual(coverage["rows"],11)
        self.assertIn("unknown",coverage["timezone"])
        with self.assertRaisesRegex(ValueError,"out-of-year"):
            research.parse_year(fixture(2021),2022)

    def test_price_grid(self):
        self.assertAlmostEqual(research.range_bps(dict(Open="100",High="101",Low="99",Close="100",Volume="2")),200.0)
        with self.assertRaises(ValueError):
            research.range_bps(dict(Open="100",High="101.1",Low="99",Close="100",Volume="2"))

    def test_training_only_threshold_and_bootstrap(self):
        train=[("2021-04-05",float(i),float(i)) for i in range(101)]
        test=[]
        for day in ("2024-05-01","2024-05-02","2025-05-01"):
            test.extend([(day,0.0,1.0)]*10)
            test.extend([(day,100.0,4.0)]*10)
        result=research.frozen_holdout(train,test)
        self.assertEqual(result["test_observations_after_low"],30)
        self.assertEqual(result["test_observations_after_high"],30)
        self.assertEqual(result["date_paired_holdout_effect"]["dates"],3)
        self.assertEqual(result["date_paired_holdout_effect"]["median_difference_bps"],3)
        self.assertEqual(result,research.frozen_holdout(train,test))

    def test_no_pairs_rejected(self):
        with self.assertRaises(ValueError):
            research.parse_year(fixture(2021).replace(b"09:3",b"08:3"),2021)


if __name__=="__main__":
    unittest.main()
