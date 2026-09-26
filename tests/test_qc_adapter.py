"""Smoke test of quantconnect/main.py against a tiny stub of the LEAN API.

This does not replace a real QuantConnect backtest; it verifies the adapter
wiring: bars -> engine -> market orders -> order events -> engine.confirm.
"""
import importlib
import sys
import types
import unittest
from types import SimpleNamespace

import helpers  # noqa: F401  (sets sys.path)

from backtest.data import merge, synthetic_bars


def _make_stub_module():
    m = types.ModuleType("AlgorithmImports")

    class Enum:
        pass

    m.Resolution = SimpleNamespace(MINUTE="minute", HOUR="hour", DAILY="daily")
    m.Market = SimpleNamespace(COINBASE="coinbase", OANDA="oanda")
    m.OrderStatus = SimpleNamespace(FILLED="filled", INVALID="invalid", CANCELED="canceled")
    m.Slice = object
    m.OrderEvent = object

    class DataDict(dict):
        def contains_key(self, key):
            return key in self

    class QCAlgorithm:
        def __init__(self):
            self.cash, self.is_warming_up, self.live_mode = 0, False, False
            self.orders, self.logs, self.webhooks = {}, [], []
            self.holdings, self.prices = {}, {}
            self.portfolio = SimpleNamespace(total_portfolio_value=0)
            self.transactions = SimpleNamespace(get_order_by_id=self.orders.get)
            self.notify = SimpleNamespace(web=lambda url, data: self.webhooks.append((url, data)))

        def set_start_date(self, *a): pass
        def set_end_date(self, *a): pass
        def set_warm_up(self, *a): pass

        def set_cash(self, cash):
            self.cash = cash
            self.portfolio.total_portfolio_value = cash

        def debug(self, msg): self.logs.append(msg)
        log = debug

        def add_equity(self, ticker, resolution):
            return SimpleNamespace(symbol=f"SYM:{ticker}")

        def market_order(self, symbol, qty, tag=""):
            oid = len(self.orders) + 1
            self.orders[oid] = SimpleNamespace(tag=tag)
            price = self.prices[symbol]
            self.cash -= qty * price
            self.holdings[symbol] = self.holdings.get(symbol, 0) + qty
            self.on_order_event(SimpleNamespace(
                order_id=oid, status="filled", fill_price=price, message="",
                order_fee=SimpleNamespace(value=SimpleNamespace(amount=1.0))))

        def mark(self, symbol, price):
            self.prices[symbol] = price
            self.portfolio.total_portfolio_value = self.cash + sum(
                q * self.prices[s] for s, q in self.holdings.items())

    m.QCAlgorithm = QCAlgorithm
    m.DataDict = DataDict
    return m


class QuantConnectAdapterTest(unittest.TestCase):
    def test_main_runs_against_stub(self):
        stub = _make_stub_module()
        sys.modules["AlgorithmImports"] = stub
        try:
            main = importlib.import_module("main")
            algo = main.ModularTradingAlgorithm()
            algo.initialize()
            self.assertEqual(set(algo.symbols), {"SPY", "QQQ", "IWM"})

            series = [synthetic_bars(t, 900, seed=5) for t in algo.symbols]
            for step in merge(series):
                bars = stub.DataDict()
                for b in step:
                    sym = algo.symbols[b.symbol]
                    algo.mark(sym, b.close)
                    bars[sym] = SimpleNamespace(end_time=b.time, open=b.open, high=b.high,
                                                low=b.low, close=b.close, volume=b.volume)
                algo.on_data(SimpleNamespace(bars=bars, quote_bars=stub.DataDict()))
            algo.on_end_of_algorithm()

            self.assertGreater(len(algo.orders), 10)
            self.assertFalse(algo.engine._pending, "every intent must be confirmed via on_order_event")
            # engine's virtual book equals the stub broker's net holdings
            net = {}
            for pos in algo.engine.positions.values():
                sym = algo.symbols[pos.symbol]
                net[sym] = net.get(sym, 0) + pos.quantity * pos.direction
            self.assertEqual({k: v for k, v in algo.holdings.items() if v}, net)
            self.assertTrue(any(line.startswith("[") for line in algo.logs))
        finally:
            sys.modules.pop("AlgorithmImports", None)
            sys.modules.pop("main", None)


if __name__ == "__main__":
    unittest.main()
