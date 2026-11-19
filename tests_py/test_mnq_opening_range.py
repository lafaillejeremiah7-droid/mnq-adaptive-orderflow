import unittest

from scripts.mnq_opening_range import MINUTES, simulate


class OpeningRange(unittest.TestCase):
    def setUp(self):
        self.bars = [(1000,1002,998,1000,1)] * MINUTES

    def test_frozen_range_and_next_open(self):
        self.assertIsNone(simulate(self.bars))
        self.bars[30] = (1000,1210,998,1005,1)
        self.bars[31] = (1100,1260,1021,1105,1)
        self.assertEqual(simulate(self.bars)["gross_ticks"],160)
        self.bars[31] = (1100,1260,1020,1105,1)
        self.assertEqual(simulate(self.bars)["exit_reason"],"ambiguous_stop")

    def test_short_gap_and_time_exit(self):
        self.bars[30] = (1000,1000,995,995,1)
        self.bars[32] = (1100,1100,900,1000,1)
        self.assertEqual(simulate(self.bars)["gross_ticks"],-100)
        self.bars[32] = self.bars[0]
        self.bars[-1] = (995,1200,800,995,1)
        self.assertEqual(simulate(self.bars)["gross_ticks"],5)

    def test_latest_signal(self):
        self.bars[325] = (1000,1005,995,1005,1)
        self.assertIsNone(simulate(self.bars))
        self.bars[324] = self.bars[325]
        self.assertEqual(simulate(self.bars)["entry_minute"],325)
