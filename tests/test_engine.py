import unittest

from helpers import bar, closes_to_bars

from framework import Direction, RiskManager, Setup, TradingEngine, build_setup
from framework.blocks import Signal, create_block, register


class ScriptedSignal(Signal):
    """Fires the given direction on the listed bar indices (counted by the hub)."""

    def __init__(self, fire_on):
        self.fire_on = dict(fire_on)

    def evaluate(self, ctx):
        return self.fire_on.get(ctx.hub.bars)


def engine_with(exits, fire_on=None, direction="both", risk=None, sizer=None, **kw):
    setup = Setup("s", [ScriptedSignal(fire_on or {1: Direction.LONG})],
                  exits=[create_block("exit", e) for e in exits],
                  sizer=create_block("sizer", sizer or {"type": "fixed_quantity", "quantity": 10}),
                  direction=direction, **kw)
    return TradingEngine([setup], risk or RiskManager())


def run(engine, bars, equity=100_000):
    intents = []
    for b in bars:
        for it in engine.on_bar(b, equity):
            engine.confirm(it.id, it.price)
            intents.append(it)
    return intents


class EngineTests(unittest.TestCase):
    def test_percent_stop_hit(self):
        eng = engine_with([{"type": "percent_stop", "pct": 0.05}])
        intents = run(eng, [bar(0, 100, 101, 99, 100), bar(1, 100, 101, 94, 96)])
        self.assertEqual([i.action for i in intents], ["open", "close"])
        self.assertEqual(intents[1].reason, "stop")
        self.assertAlmostEqual(intents[1].price, 95.0)
        self.assertAlmostEqual(eng.trades[0].pnl, -50.0)
        self.assertAlmostEqual(eng.trades[0].r_multiple, -1.0)

    def test_gap_through_stop_fills_at_open(self):
        eng = engine_with([{"type": "percent_stop", "pct": 0.05}])
        intents = run(eng, [bar(0, 100, 101, 99, 100), bar(1, 90, 91, 88, 89)])
        self.assertEqual(intents[1].price, 90)

    def test_r_target_and_short(self):
        eng = engine_with([{"type": "percent_stop", "pct": 0.02}, {"type": "r_target", "r": 2}],
                          fire_on={1: Direction.SHORT})
        intents = run(eng, [bar(0, 100, 100, 100, 100), bar(1, 99, 99.5, 95, 96)])
        self.assertEqual(intents[0].direction, Direction.SHORT)
        self.assertAlmostEqual(intents[0].target, 96.0)
        self.assertEqual(intents[1].reason, "target")
        self.assertGreater(eng.trades[0].pnl, 0)

    def test_stop_checked_before_target_same_bar(self):
        eng = engine_with([{"type": "percent_stop", "pct": 0.02}, {"type": "r_target", "r": 1}])
        intents = run(eng, [bar(0, 100, 100, 100, 100), bar(1, 100, 103, 97, 100)])
        self.assertEqual(intents[1].reason, "stop")

    def test_trailing_stop_only_tightens(self):
        eng = engine_with([{"type": "percent_stop", "pct": 0.1}, {"type": "trailing_atr", "period": 1, "mult": 1}])
        run(eng, [bar(0, 100, 100.5, 99.5, 100)])
        pos = next(iter(eng.positions.values()))
        run(eng, [bar(1, 100, 111, 109, 110)])  # atr(1) = TR = 11 -> trail 99 > 90
        self.assertAlmostEqual(pos.stop, 99.0)
        run(eng, [bar(2, 110, 110.5, 105, 105)])  # would loosen to 99.5-? never below 99
        self.assertGreaterEqual(pos.stop, 99.0)

    def test_time_exit(self):
        eng = engine_with([{"type": "time_exit", "max_bars": 2}])
        intents = run(eng, closes_to_bars([100, 100, 100, 100]))
        self.assertEqual(intents[-1].reason, "time")
        self.assertEqual(eng.trades[0].exit_time.day, 3)

    def test_direction_restriction(self):
        eng = engine_with([], fire_on={1: Direction.SHORT}, direction="long")
        self.assertEqual(run(eng, closes_to_bars([100, 100])), [])

    def test_fixed_risk_sizing(self):
        eng = engine_with([{"type": "percent_stop", "pct": 0.02}],
                          sizer={"type": "fixed_risk", "risk_pct": 0.01, "max_alloc_pct": 1.0})
        intents = run(eng, closes_to_bars([100]))
        # 1% of 100k = 1000 risk / 2 per share = 500 shares
        self.assertEqual(intents[0].quantity, 500)

    def test_risk_manager_scales_exposure(self):
        eng = engine_with([], sizer={"type": "fixed_quantity", "quantity": 5000},
                          risk=RiskManager(max_gross_exposure=0.5))
        intents = run(eng, closes_to_bars([100]))
        self.assertEqual(intents[0].quantity, 500)

    def test_risk_manager_blocks_opposing_positions(self):
        a = Setup("a", [ScriptedSignal({1: Direction.LONG})],
                  sizer=create_block("sizer", {"type": "fixed_quantity", "quantity": 1}))
        b = Setup("b", [ScriptedSignal({2: Direction.SHORT})],
                  sizer=create_block("sizer", {"type": "fixed_quantity", "quantity": 1}))
        eng = TradingEngine([a, b], RiskManager(max_positions_per_symbol=2))
        intents = run(eng, closes_to_bars([100, 100]))
        self.assertEqual(len(intents), 1)

    def test_reject_restores_state(self):
        eng = engine_with([{"type": "percent_stop", "pct": 0.05}])
        (open_intent,) = eng.on_bar(bar(0, 100, 100, 100, 100), 1e5)
        eng.reject(open_intent.id)
        self.assertEqual(eng.positions, {})
        eng2 = engine_with([{"type": "percent_stop", "pct": 0.05}])
        run(eng2, [bar(0, 100, 100, 100, 100)])
        (close_intent,) = eng2.on_bar(bar(1, 90, 90, 90, 90), 1e5)
        eng2.reject(close_intent.id)
        self.assertEqual(len(eng2.positions), 1)
        self.assertEqual(eng2.trades, [])

    def test_confirm_updates_fill_and_fees(self):
        eng = engine_with([{"type": "percent_stop", "pct": 0.05}])
        (it,) = eng.on_bar(bar(0, 100, 100, 100, 100), 1e5)
        eng.confirm(it.id, 100.5, 2.0)
        (close,) = eng.close_all({"TEST": 110}, it.time)
        eng.confirm(close.id, 109.5, 3.0)
        t = eng.trades[0]
        self.assertAlmostEqual(t.pnl, (109.5 - 100.5) * 10 - 5.0)

    def test_cooldown(self):
        eng = engine_with([{"type": "time_exit", "max_bars": 1}],
                          fire_on={i: Direction.LONG for i in range(1, 10)}, cooldown_bars=2)
        intents = run(eng, closes_to_bars([100] * 6))
        opens = [i.time.day for i in intents if i.action == "open"]
        self.assertEqual(opens, [1, 5])


class CompositionTests(unittest.TestCase):
    def test_combine_all_vs_any(self):
        long_sig, none_sig = ScriptedSignal({1: Direction.LONG}), ScriptedSignal({})
        qty = create_block("sizer", {"type": "fixed_quantity", "quantity": 1})
        all_setup = Setup("all", [long_sig, none_sig], sizer=qty, combine="all")
        any_setup = Setup("any", [long_sig, none_sig], sizer=qty, combine="any")
        eng = TradingEngine([all_setup, any_setup], RiskManager(max_positions_per_symbol=5))
        intents = run(eng, closes_to_bars([100]))
        self.assertEqual([i.setup for i in intents], ["any"])

    def test_no_stop_means_no_trade_with_fixed_risk(self):
        eng = TradingEngine([Setup("r", [ScriptedSignal({1: Direction.LONG})])])
        self.assertEqual(run(eng, closes_to_bars([100])), [])

    def test_indicator_specs_collected(self):
        setup = build_setup({
            "name": "x",
            "signals": [{"type": "ema_cross", "fast": 2, "slow": 4}],
            "filters": [{"type": "trend", "period": 3}],
        })
        self.assertEqual(setup.indicators(), [("ema", 2), ("ema", 4), ("sma", 3)])

    def test_custom_block_plugs_in(self):
        @register("signal", "always_long_test")
        class AlwaysLong(Signal):
            def evaluate(self, ctx):
                return Direction.LONG

        setup = build_setup({"name": "c", "signals": [{"type": "always_long_test"}],
                             "sizer": {"type": "fixed_quantity", "quantity": 1}})
        intents = run(TradingEngine([setup]), closes_to_bars([100]))
        self.assertEqual(len(intents), 1)

    def test_bad_config_errors_are_helpful(self):
        with self.assertRaisesRegex(ValueError, "Unknown signal 'nope'"):
            build_setup({"name": "bad", "signals": [{"type": "nope"}]})
        with self.assertRaisesRegex(ValueError, "Bad parameters"):
            build_setup({"name": "bad", "signals": [{"type": "ema_cross", "wrong": 1}]})
        with self.assertRaisesRegex(ValueError, "at least one signal"):
            build_setup({"name": "bad"})

    def test_unique_setup_names(self):
        s = Setup("dup", [ScriptedSignal({})])
        with self.assertRaises(ValueError):
            TradingEngine([s, s])


if __name__ == "__main__":
    unittest.main()
