import copy
import os
import tempfile
import unittest
from datetime import datetime

import helpers  # noqa: F401  (sets sys.path)

from backtest.data import load_csv, synthetic_bars
from backtest.run import run_backtest
from framework import Direction, OrderIntent, build_engine
from framework.bridge import ThreeCommasBridge
from strategy_config import CONFIG


class BacktestIntegration(unittest.TestCase):
    def series(self, n=800):
        return [synthetic_bars(u["ticker"], n, seed=3) for u in CONFIG["universe"]]

    def test_default_config_builds(self):
        engine = build_engine(CONFIG)
        self.assertEqual({s.name for s in engine.setups}, {"trend_follow", "mean_reversion", "breakout"})
        # shared indicators: atr(14) used by several setups is created once per symbol
        hub = engine.hubs["SPY"]
        self.assertEqual(len([k for k in hub._indicators if k == ("atr", 14)]), 1)

    def test_backtest_runs_deterministically_and_flat_at_end(self):
        r1 = run_backtest(copy.deepcopy(CONFIG), self.series())
        r2 = run_backtest(copy.deepcopy(CONFIG), self.series())
        self.assertGreater(len(r1.trades), 10)
        self.assertEqual(r1.curve[-1][1], r2.curve[-1][1])
        # pnl bookkeeping of the engine matches the broker's equity
        pnl = sum(t.pnl for t in r1.trades)
        self.assertAlmostEqual(r1.curve[-1][1] - CONFIG["backtest"]["cash"], pnl, places=4)

    def test_disabled_setup_is_skipped(self):
        cfg = copy.deepcopy(CONFIG)
        for s in cfg["setups"]:
            s["enabled"] = s["name"] == "breakout"
        result = run_backtest(cfg, self.series())
        self.assertEqual({t.setup for t in result.trades}, {"breakout"})

    def test_csv_loader(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.csv")
            with open(path, "w") as fh:
                fh.write("Date,Open,High,Low,Close,Volume\n2024-01-03,2,3,1,2.5,10\n2024-01-02,1,2,0.5,1.5,5\n")
            bars = load_csv(path, "X")
        self.assertEqual([b.close for b in bars], [1.5, 2.5])


class ThreeCommasTests(unittest.TestCase):
    def intent(self, action, direction=Direction.LONG):
        return OrderIntent(1, action, "s", "BTCUSD", direction, 0.5, 42000.0, datetime(2025, 1, 1, 12))

    def test_signal_bot_payload(self):
        b = ThreeCommasBridge(secret="sec", bot_uuid="uuid", symbol_map={"BTCUSD": "BTCUSDT"}, send_amount=True)
        p = b.build(self.intent("open"))
        self.assertEqual(p["action"], "enter_long")
        self.assertEqual(p["tv_instrument"], "BTCUSDT")
        self.assertEqual(p["timestamp"], "2025-01-01T12:00:00Z")
        self.assertEqual(p["order"]["amount"], "0.5")
        self.assertEqual(b.build(self.intent("close", Direction.SHORT))["action"], "exit_short")

    def test_dca_bot_payload(self):
        b = ThreeCommasBridge(mode="dca_bot", bot_id=123, email_token="tok", symbol_map={"BTCUSD": "USDT_BTC"})
        self.assertNotIn("action", b.build(self.intent("open")))
        close = b.build(self.intent("close"))
        self.assertEqual(close["action"], "close_at_market_price")
        self.assertEqual(close["pair"], "USDT_BTC")


if __name__ == "__main__":
    unittest.main()
