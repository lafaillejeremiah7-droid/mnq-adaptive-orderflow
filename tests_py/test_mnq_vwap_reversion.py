import unittest
from scripts.mnq_vwap_reversion import simulate


class ReversionTests(unittest.TestCase):
    def bars(self):
        bars = [(1000,1000,1000,1000,1000)] * 330
        bars[29] = (900,900,900,900,1)
        bars[30] = (900,930,900,930,1)
        bars[31] = (935,999,930,950,1)
        return bars

    def test_frozen_fractional_target(self):
        r = simulate(self.bars())
        self.assertEqual((r["direction"],r["entry_minute"],r["gross_ticks"]), (1,31,64))

    def test_short_symmetry(self):
        bars = [(2000-o,2000-l,2000-h,2000-c,v) for o,h,l,c,v in self.bars()]
        r = simulate(bars)
        self.assertEqual((r["direction"],r["gross_ticks"]),(-1,64))

    def test_gap_beyond_target(self):
        bars = self.bars()
        bars[31] = bars[0]
        self.assertIsNone(simulate(bars))
