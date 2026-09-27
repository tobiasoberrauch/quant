"""Exit blocks: initial stops, targets, trailing and discretionary exits.

The engine itself checks ``pos.stop`` / ``pos.target`` against each new bar's
high/low. Blocks only *place* and *move* those levels, or return a reason from
``on_bar`` to exit at the bar close.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..types import Context, Direction, Position
from .base import Exit, create_block, register


def _tighter(pos: Position, candidate: float) -> float:
    """Ratchet: a stop may only move in the trade's favour."""
    if pos.stop is None:
        return candidate
    if pos.direction is Direction.LONG:
        return max(pos.stop, candidate)
    return min(pos.stop, candidate)


@register("exit", "atr_stop")
class AtrStop(Exit):
    priority = 0

    def __init__(self, period: int = 14, mult: float = 2.0) -> None:
        self.period, self.mult = int(period), float(mult)

    def indicators(self):
        return [("atr", self.period)]

    def on_entry(self, pos: Position, ctx: Context) -> None:
        atr = ctx.ind("atr", self.period).value
        if atr:
            pos.stop = pos.entry_price - pos.direction * self.mult * atr


@register("exit", "percent_stop")
class PercentStop(Exit):
    priority = 0

    def __init__(self, pct: float = 0.02) -> None:
        self.pct = float(pct)

    def on_entry(self, pos: Position, ctx: Context) -> None:
        pos.stop = pos.entry_price * (1 - pos.direction * self.pct)


@register("exit", "r_target")
class RMultipleTarget(Exit):
    """Take profit at ``r`` times the initial risk. Needs a stop block."""

    priority = 1

    def __init__(self, r: float = 2.0) -> None:
        self.r = float(r)

    def on_entry(self, pos: Position, ctx: Context) -> None:
        if pos.stop is not None:
            risk = abs(pos.entry_price - pos.stop)
            pos.target = pos.entry_price + pos.direction * self.r * risk


@register("exit", "percent_target")
class PercentTarget(Exit):
    priority = 1

    def __init__(self, pct: float = 0.04) -> None:
        self.pct = float(pct)

    def on_entry(self, pos: Position, ctx: Context) -> None:
        pos.target = pos.entry_price * (1 + pos.direction * self.pct)


@register("exit", "trailing_atr")
class TrailingAtrStop(Exit):
    """Chandelier-style trail from the close; only ever tightens."""

    priority = 2

    def __init__(self, period: int = 14, mult: float = 3.0) -> None:
        self.period, self.mult = int(period), float(mult)

    def indicators(self):
        return [("atr", self.period)]

    def _level(self, pos: Position, ctx: Context) -> Optional[float]:
        atr = ctx.ind("atr", self.period).value
        if not atr:
            return None
        return ctx.close - pos.direction * self.mult * atr

    def on_entry(self, pos: Position, ctx: Context) -> None:
        if pos.stop is None:
            pos.stop = self._level(pos, ctx)

    def on_bar(self, pos: Position, ctx: Context) -> Optional[str]:
        level = self._level(pos, ctx)
        if level is not None:
            pos.stop = _tighter(pos, level)
        return None


@register("exit", "break_even")
class BreakEven(Exit):
    """Move the stop to entry (+offset R) once the trade is ``trigger_r`` in profit."""

    priority = 2

    def __init__(self, trigger_r: float = 1.0, offset_r: float = 0.0) -> None:
        self.trigger_r, self.offset_r = float(trigger_r), float(offset_r)

    def on_bar(self, pos: Position, ctx: Context) -> Optional[str]:
        risk = pos.risk_per_unit
        if risk and pos.favorable_excursion() >= self.trigger_r * risk:
            pos.stop = _tighter(pos, pos.entry_price + pos.direction * self.offset_r * risk)
        return None


@register("exit", "time_exit")
class TimeExit(Exit):
    priority = 3

    def __init__(self, max_bars: int = 20) -> None:
        self.max_bars = int(max_bars)

    def on_bar(self, pos: Position, ctx: Context) -> Optional[str]:
        return "time" if pos.bars_held >= self.max_bars else None


@register("exit", "signal_exit")
class SignalExit(Exit):
    """Exit when any signal block points the other way, e.g. an EMA cross back."""

    priority = 3

    def __init__(self, signal: Dict[str, Any]) -> None:
        self.signal = create_block("signal", signal)

    def indicators(self):
        return self.signal.indicators()

    def on_bar(self, pos: Position, ctx: Context) -> Optional[str]:
        d = self.signal.evaluate(ctx)
        if d is not None and d is pos.direction.opposite:
            return f"signal:{self.signal.type_name}"
        return None
