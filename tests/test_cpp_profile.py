"""Pure-Python fallback and full-dictionary differential C++ profile tests."""
import importlib.util
import random
import unittest

from company.market_profile import Trade, volume_profile

NATIVE = importlib.util.find_spec("company._nq_cpp") is not None


def make_trades(n, seed=11, symbol="NQH5"):
    rng = random.Random(seed)
    ts = 1738593000 * 1_000_000_000
    tick = 84000
    output = []
    for i in range(n):
        tick = max(100, tick + rng.choice((-2, -1, 0, 0, 1, 2)))
        output.append(Trade(
            ts + (i // 2) * 35_000_000, symbol, tick, rng.randint(1, 30),
            rng.choice(("B", "A", "N")), i,
        ))
    return output


class NativeProfileTests(unittest.TestCase):
    def test_reference_remains_default(self):
        trades = make_trades(200)
        self.assertEqual(volume_profile(trades, .7), volume_profile(trades, .7, "python"))
        self.assertEqual(volume_profile(trades, .7), volume_profile(trades, .7, "auto"))

    def test_invalid_backend_rejected(self):
        with self.assertRaisesRegex(ValueError, "backend"):
            volume_profile(make_trades(5), .7, "cuda")

    @unittest.skipUnless(NATIVE, "native extension optional; compiled by C++ workflow")
    def test_full_profile_parity_across_fractions(self):
        for n in (1, 2, 3, 17, 300, 2_000, 21_000):
            for fraction in (.50, .70, .85, .95):
                with self.subTest(n=n, fraction=fraction):
                    trades = make_trades(n, seed=n * 29 + 7)
                    self.assertEqual(volume_profile(trades, fraction, "cpp"),
                                     volume_profile(trades, fraction, "python"))

    @unittest.skipUnless(NATIVE, "native extension optional")
    def test_both_contracts_and_real_auto_dispatch(self):
        for contract in ("NQH5", "MNQM5"):
            trades = make_trades(24_000, 102, contract)
            expected = volume_profile(trades, .7)
            self.assertEqual(volume_profile(trades, .7, "cpp"), expected)
            self.assertEqual(volume_profile(trades, .7, "auto"), expected)
            self.assertFalse(expected["delta_covers_all_volume"])
            self.assertEqual(expected["total_contracts_traded"],
                             sum([expected["aggressor_buy_volume"],
                                  expected["aggressor_sell_volume"],
                                  expected["aggressor_unknown_volume"]]))

    @unittest.skipUnless(NATIVE, "native extension optional")
    def test_large_weight_and_price_gaps(self):
        t = 1_750_000_000_000_000_000
        trades = [
            Trade(t, "NQZ6", 80000, 30_000_000, "B", 1),
            Trade(t + 1, "NQZ6", 80004, 30_000_000, "A", 2),
            Trade(t + 2, "NQZ6", 80009, 30_000_000, "N", 3),
        ]
        self.assertEqual(volume_profile(trades, .7, "cpp"),
                         volume_profile(trades, .7, "python"))

    @unittest.skipUnless(NATIVE, "native extension optional")
    def test_native_bad_inputs_rejected(self):
        from company import _nq_cpp
        with self.assertRaises(ValueError):
            _nq_cpp.aggregate([])
        base = make_trades(1)[0]
        for bad in (
            Trade(base.timestamp_ns, base.contract, base.price_ticks, 0, "B", 1),
            Trade(base.timestamp_ns, base.contract, -1, 1, "B", 1),
            Trade(base.timestamp_ns, base.contract, base.price_ticks, 1, "X", 1),
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                _nq_cpp.aggregate([bad])
