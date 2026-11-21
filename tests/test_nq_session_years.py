"""Synthetic verification fixtures for explicitly ET-labeled NQ session research."""
import csv
import gzip
import io
import unittest
from company import nq_session_years as study


def sample():
    buffer=io.StringIO()
    writer=csv.writer(buffer,lineterminator="\n")
    writer.writerow(study.COLUMNS)
    for hour,minutes,range_width in ((9,range(30,60),2.0),(12,range(0,30),.5)):
        for m in minutes:
            writer.writerow([
              f"2025-06-03T{hour:02d}:{m:02d}:00-04:00",
              "20000",f"{20000+range_width/2:.2f}",f"{20000-range_width/2:.2f}","20000",
              "10","SYNTHETIC_FIXTURE","2025-06-03","RTH"])
    return gzip.compress(buffer.getvalue().encode())


class SessionTests(unittest.TestCase):
    def test_complete_paired_day(self):
        result=study.analyze(sample())
        self.assertEqual(result["complete_day_count"],1)
        self.assertGreater(result["all_day_paired_effect_bps"]["median"],0)
        self.assertEqual(result["per_year"]["2025"]["n"],1)
        self.assertFalse(result["tradable_edge_validated"])

    def test_missing_timezone_rejected(self):
        data=gzip.decompress(sample()).replace(b"-04:00",b"")
        with self.assertRaisesRegex(ValueError,"timezone"):
            study.analyze(gzip.compress(data))

    def test_no_fake_volume_profile(self):
        result=study.analyze(sample())
        self.assertFalse(result["trade_by_price_reconstruction_available"])

    def test_incomplete_midday_is_excluded(self):
        content=gzip.decompress(sample()).decode()
        lines=content.splitlines()
        reduced=[row for row in lines if "12:29" not in row]
        result=study.analyze(gzip.compress(("\n".join(reduced)+"\n").encode()))
        self.assertEqual(result["complete_day_count"],0)
        self.assertEqual(result["all_day_paired_effect_bps"]["n"],0)


if __name__=="__main__":
    unittest.main()
