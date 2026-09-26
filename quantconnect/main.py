"""QuantConnect / LEAN adapter for the modular trading framework.

This file is intentionally thin: it only converts LEAN data into ``Bar``
objects, forwards them to the platform-independent ``TradingEngine`` and turns
the returned ``OrderIntent`` objects into orders (and/or 3Commas webhooks).
All strategy logic lives in ``framework/`` and is configured in ``strategy_config.py``.
"""
# region imports
from AlgorithmImports import *  # noqa: F401,F403  (QuantConnect runtime)
# endregion
import json

from strategy_config import CONFIG
from framework import Bar, build_engine
from framework.bridge import build_bridge

_RESOLUTIONS = {
    "minute": Resolution.MINUTE,
    "hour": Resolution.HOUR,
    "daily": Resolution.DAILY,
}


class ModularTradingAlgorithm(QCAlgorithm):

    def initialize(self):
        cfg = CONFIG
        bt = cfg["backtest"]
        self.set_start_date(*bt["start"])
        self.set_end_date(*bt["end"])
        self.set_cash(bt["cash"])

        self.resolution = _RESOLUTIONS[cfg.get("resolution", "daily")]
        self.execution = cfg.get("execution", "qc")
        self.engine = build_engine(cfg, log=self.debug)
        self.bridge = build_bridge(cfg)
        self.symbols = {}  # ticker -> Symbol
        self.tickers = {}  # Symbol -> ticker

        for u in cfg["universe"]:
            self._add_security(u)

        for setup in self.engine.setups:
            self.debug(setup.describe())

        self.set_warm_up(cfg.get("warmup_bars", 200), self.resolution)

    def _add_security(self, u):
        kind, ticker = u.get("type", "equity"), u["ticker"]
        if kind == "equity":
            security = self.add_equity(ticker, self.resolution)
        elif kind == "crypto":
            market = getattr(Market, u.get("market", "COINBASE").upper())
            security = self.add_crypto(ticker, self.resolution, market)
        elif kind == "forex":
            market = getattr(Market, u.get("market", "OANDA").upper())
            security = self.add_forex(ticker, self.resolution, market)
        else:
            raise ValueError(f"unsupported security type {kind}")
        self.symbols[ticker] = security.symbol
        self.tickers[security.symbol] = ticker

    # ------------------------------------------------------------------ data
    def on_data(self, data: Slice):
        for ticker, symbol in self.symbols.items():
            bar = self._to_bar(data, ticker, symbol)
            if bar is None:
                continue
            equity = float(self.portfolio.total_portfolio_value)
            intents = self.engine.on_bar(bar, equity, allow_entries=not self.is_warming_up)
            for intent in intents:
                self._execute(intent)

    def _to_bar(self, data, ticker, symbol):
        source = None
        if data.bars.contains_key(symbol):
            source = data.bars[symbol]
        elif data.quote_bars.contains_key(symbol):
            source = data.quote_bars[symbol]
        if source is None:
            return None
        volume = float(getattr(source, "volume", 0) or 0)
        return Bar(ticker, source.end_time, float(source.open), float(source.high),
                   float(source.low), float(source.close), volume)

    # ------------------------------------------------------------------ execution
    def _execute(self, intent):
        if self.execution in ("3commas", "both"):
            self._send_3commas(intent)
        if self.execution == "3commas":
            # QC does not hold the position; assume the reference price.
            self.engine.confirm(intent.id, intent.price)
            return
        self.market_order(self.symbols[intent.symbol], intent.signed_quantity, tag=intent.tag)

    def _send_3commas(self, intent):
        if self.bridge is None or not self.live_mode:
            return
        payload = self.bridge.build(intent)
        self.notify.web(self.bridge.url, json.dumps(payload))
        self.debug(f"3Commas -> {payload.get('action', 'start_deal')} {intent.symbol}")

    def on_order_event(self, order_event: OrderEvent):
        order = self.transactions.get_order_by_id(order_event.order_id)
        tag = order.tag if order is not None else ""
        if not tag.startswith("#"):
            return
        intent_id = int(tag[1:].split("|", 1)[0])
        if order_event.status == OrderStatus.FILLED:
            fee = float(order_event.order_fee.value.amount)
            self.engine.confirm(intent_id, float(order_event.fill_price), fee)
        elif order_event.status in (OrderStatus.INVALID, OrderStatus.CANCELED):
            self.engine.reject(intent_id)
            self.debug(f"order for intent {intent_id} {order_event.status}: {order_event.message}")

    # ------------------------------------------------------------------ reporting
    def on_end_of_algorithm(self):
        stats = {}
        for t in self.engine.trades:
            s = stats.setdefault(t.setup, {"trades": 0, "wins": 0, "pnl": 0.0})
            s["trades"] += 1
            s["wins"] += t.pnl > 0
            s["pnl"] += t.pnl
        for name, s in stats.items():
            win = 100.0 * s["wins"] / s["trades"] if s["trades"] else 0.0
            self.log(f"[{name}] trades={s['trades']} win%={win:.1f} pnl={s['pnl']:.2f}")
