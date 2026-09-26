import unittest

from helpers import bar, closes_to_bars

from framework.indicators import ADX, ATR, EMA, RSI, SMA, Bollinger, Donchian, IndicatorHub


def feed(ind, bars):
    for b in bars:
        ind.update(b)
    return ind


class IndicatorTests(unittest.TestCase):
    def test_sma(self):
        sma = SMA(3)
        values = []
        for b in closes_to_bars([1, 2, 3, 4, 5]):
            sma.update(b)
            values.append(sma.value)
        self.assertEqual(values, [None, None, 2.0, 3.0, 4.0])

    def test_ema_seed_and_recursion(self):
        ema = feed(EMA(3), closes_to_bars([1, 2, 3, 4]))
        # seed = SMA(1,2,3) = 2, then 2 + 0.5 * (4 - 2) = 3
        self.assertAlmostEqual(ema.value, 3.0)
        self.assertAlmostEqual(ema.prev, 2.0)

    def test_rsi_bounds_and_extremes(self):
        up = feed(RSI(5), closes_to_bars(range(1, 20)))
        self.assertEqual(up.value, 100.0)
        down = feed(RSI(5), closes_to_bars(range(20, 1, -1)))
        self.assertEqual(down.value, 0.0)
        mixed = feed(RSI(5), closes_to_bars([10, 11, 10, 12, 11, 13, 12, 11, 12]))
        self.assertTrue(0 < mixed.value < 100)

    def test_atr_constant_range(self):
        atr = feed(ATR(3), closes_to_bars([10] * 5, spread=1.0))
        self.assertAlmostEqual(atr.value, 2.0)

    def test_donchian_excludes_current_bar(self):
        dc = Donchian(3)
        bars = [bar(0, 10, 11, 9, 10), bar(1, 10, 12, 9, 11), bar(2, 11, 13, 10, 12), bar(3, 12, 20, 11, 19)]
        feed(dc, bars)
        self.assertEqual(dc.upper, 13)  # the 20 high of the current bar is not included
        self.assertEqual(dc.lower, 9)

    def test_bollinger_flat(self):
        bb = feed(Bollinger(4, 2), closes_to_bars([5, 5, 5, 5]))
        self.assertEqual((bb.lower, bb.value, bb.upper), (5, 5, 5))

    def test_adx_trending_is_high(self):
        adx = feed(ADX(5), closes_to_bars([100 + i * 2 for i in range(40)]))
        self.assertGreater(adx.value, 50)
        self.assertGreater(adx.plus_di, adx.minus_di)

    def test_hub_shares_instances(self):
        hub = IndicatorHub("X")
        a = hub.register(("ema", 10))
        b = hub.get("ema", 10)
        self.assertIs(a, b)
        self.assertEqual(len(hub), 1)
        with self.assertRaises(ValueError):
            hub.register(("nope", 1))


if __name__ == "__main__":
    unittest.main()
