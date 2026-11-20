import unittest
from range_study import compare


def session(day, morning_ticks, midday_ticks):
    for hour, start, spread in [(14,30,morning_ticks),(17,0,midday_ticks)]:
        for minute in range(start, start+30):
            yield dict(timestamp=f"2025-02-{day:02d}T{hour:02d}:{minute:02d}:00Z",
                       contract="MNQH5",high=str(100+spread/4),low="100")


class RangeStudyTests(unittest.TestCase):
    def test_pairs_exclusions_ties_and_units(self):
        rows = list(session(3,12,4)) + list(session(4,8,8)) + list(session(5,80,4))[:-1]
        r = compare(rows)
        self.assertEqual(r["excluded_observed_dates"],["2025-02-05"])
        self.assertEqual((r["eligible_dates"],r["opening_larger"],r["ties"]), (2,1,1))
        self.assertEqual(r["median_paired_difference"],1)

    def test_duplicate_and_empty_sample(self):
        rows = list(session(3,12,4))
        with self.assertRaises(ValueError):
            compare([rows[0],*rows])
        with self.assertRaises(ValueError):
            compare(rows[:-1])
