"""The trading engine: platform independent, bar driven.

Per bar and symbol it
  1. updates the shared indicators,
  2. manages open positions (stop/target hit, trailing, discretionary exits),
  3. asks every setup for a new entry and runs sizing + portfolio risk,
and returns ``OrderIntent`` objects. The caller executes them and reports the
fill with ``confirm`` (or ``reject``). The engine keeps a *virtual* position
per (setup, symbol) so that several setups can share one account.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .indicators import IndicatorHub
from .risk import RiskManager
from .setup import Setup
from .types import Bar, Context, Direction, OrderIntent, Position, Trade

Key = Tuple[str, str]  # (setup name, symbol)


class TradingEngine:
    def __init__(
        self,
        setups: Iterable[Setup],
        risk: Optional[RiskManager] = None,
        lot_sizes: Optional[Dict[str, float]] = None,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.setups: List[Setup] = list(setups)
        names = [s.name for s in self.setups]
        if len(names) != len(set(names)):
            raise ValueError(f"setup names must be unique: {names}")
        self.risk = risk or RiskManager()
        self.lot_sizes = dict(lot_sizes or {})
        self.log = log or (lambda msg: None)
        self.hubs: Dict[str, IndicatorHub] = {}
        self.positions: Dict[Key, Position] = {}
        self.trades: List[Trade] = []
        self._blocked_until: Dict[Key, int] = {}  # hub bar count until which re-entry is blocked
        self._pending: Dict[int, tuple] = {}
        self._next_id = 1

    # ------------------------------------------------------------------ setup
    def add_symbol(self, symbol: str) -> IndicatorHub:
        hub = self.hubs.get(symbol)
        if hub is None:
            hub = self.hubs[symbol] = IndicatorHub(symbol)
            for setup in self.setups:
                if setup.trades(symbol):
                    for spec in setup.indicators():
                        hub.register(spec)
        return hub

    # ------------------------------------------------------------------ main loop
    def on_bar(self, bar: Bar, equity: float, allow_entries: bool = True) -> List[OrderIntent]:
        hub = self.add_symbol(bar.symbol)
        hub.update(bar)
        self.risk.on_bar(bar.time, equity)
        ctx = Context(bar.symbol, bar, hub, equity)
        intents: List[OrderIntent] = []

        for setup in self.setups:
            if not setup.trades(bar.symbol):
                continue
            key = (setup.name, bar.symbol)
            pos = self.positions.get(key)
            if pos is not None:
                intent = self._manage(setup, pos, ctx)
                if intent:
                    intents.append(intent)

        if allow_entries:
            for setup in self.setups:
                key = (setup.name, bar.symbol)
                if (not setup.trades(bar.symbol) or key in self.positions
                        or hub.bars <= self._blocked_until.get(key, 0)):
                    continue
                direction = setup.entry_signal(ctx)
                if direction is not None:
                    intent = self._open(setup, direction, ctx)
                    if intent:
                        intents.append(intent)
        return intents

    # ------------------------------------------------------------------ fills
    def confirm(self, intent_id: int, fill_price: float, fee: float = 0.0) -> None:
        pending = self._pending.pop(intent_id, None)
        if pending is None:
            return
        if pending[0] == "open":
            pos = self.positions.get(pending[1])
            if pos is not None:
                pos.entry_price, pos.entry_fee = fill_price, pos.entry_fee + fee
                pos.highest = pos.lowest = fill_price
        else:
            trade = pending[1]
            trade.exit_price, trade.fees = fill_price, trade.fees + fee

    def reject(self, intent_id: int) -> None:
        pending = self._pending.pop(intent_id, None)
        if pending is None:
            return
        if pending[0] == "open":
            self.positions.pop(pending[1], None)
        else:
            _, trade, pos, key = pending
            self.trades.remove(trade)
            self.positions[key] = pos
            self._blocked_until.pop(key, None)

    def close_all(self, prices: Dict[str, float], time: datetime, reason: str = "flatten") -> List[OrderIntent]:
        intents = []
        for (setup_name, symbol), pos in list(self.positions.items()):
            if symbol in prices:
                intents.append(self._close(pos, prices[symbol], reason, time, cooldown=0))
        return intents

    # ------------------------------------------------------------------ internals
    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id - 1

    def _round_qty(self, symbol: str, qty: float) -> float:
        lot = self.lot_sizes.get(symbol, 1.0)
        return round(math.floor(qty / lot + 1e-9) * lot, 10)

    def _open(self, setup: Setup, direction: Direction, ctx: Context) -> Optional[OrderIntent]:
        price = ctx.close
        pos = Position(setup.name, ctx.symbol, direction, 0.0, price, ctx.time,
                       highest=price, lowest=price)
        for ex in setup.exits:
            ex.on_entry(pos, ctx)
        pos.initial_stop = pos.stop

        qty = self._round_qty(ctx.symbol, setup.sizer.size(ctx, direction, price, pos.stop))
        if qty <= 0:
            return None
        qty, why = self.risk.approve(ctx.symbol, direction, qty, price, ctx.equity, self.positions)
        qty = self._round_qty(ctx.symbol, qty)
        if qty <= 0:
            self.log(f"{ctx.time} {setup.name} {ctx.symbol} {direction.label} blocked: {why}")
            return None

        pos.quantity = qty
        key = (setup.name, ctx.symbol)
        self.positions[key] = pos
        intent = OrderIntent(self._new_id(), "open", setup.name, ctx.symbol, direction, qty, price,
                             ctx.time, "entry", pos.stop, pos.target)
        self._pending[intent.id] = ("open", key)
        return intent

    def _manage(self, setup: Setup, pos: Position, ctx: Context) -> Optional[OrderIntent]:
        bar = ctx.bar
        pos.bars_held += 1
        price, reason = self._check_levels(pos, bar)
        if price is None:
            pos.highest, pos.lowest = max(pos.highest, bar.high), min(pos.lowest, bar.low)
            for ex in setup.exits:
                reason = ex.on_bar(pos, ctx)
                if reason:
                    price = bar.close
                    break
        if price is None:
            return None
        return self._close(pos, price, reason, bar.time, setup.cooldown_bars)

    @staticmethod
    def _check_levels(pos: Position, bar: Bar) -> Tuple[Optional[float], str]:
        """Stops are checked before targets (conservative when both are hit)."""
        if pos.direction is Direction.LONG:
            if pos.stop is not None and bar.low <= pos.stop:
                return min(bar.open, pos.stop), "stop"
            if pos.target is not None and bar.high >= pos.target:
                return max(bar.open, pos.target), "target"
        else:
            if pos.stop is not None and bar.high >= pos.stop:
                return max(bar.open, pos.stop), "stop"
            if pos.target is not None and bar.low <= pos.target:
                return min(bar.open, pos.target), "target"
        return None, ""

    def _close(self, pos: Position, price: float, reason: str, time: datetime, cooldown: int) -> OrderIntent:
        key = (pos.setup, pos.symbol)
        self.positions.pop(key, None)
        if cooldown:
            self._blocked_until[key] = self.hubs[pos.symbol].bars + cooldown
        trade = Trade(pos.setup, pos.symbol, pos.direction, pos.quantity, pos.entry_time,
                      pos.entry_price, time, price, reason, pos.entry_fee, pos.initial_stop)
        self.trades.append(trade)
        intent = OrderIntent(self._new_id(), "close", pos.setup, pos.symbol, pos.direction,
                             pos.quantity, price, time, reason)
        self._pending[intent.id] = ("close", trade, pos, key)
        return intent
