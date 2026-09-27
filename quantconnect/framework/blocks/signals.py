"""Entry signal blocks."""
from __future__ import annotations

from typing import Optional

from ..types import Context, Direction
from .base import Signal, register


@register("signal", "ema_cross")
class EmaCross(Signal):
    """Fast EMA crosses the slow EMA."""

    def __init__(self, fast: int = 20, slow: int = 50) -> None:
        if fast >= slow:
            raise ValueError("ema_cross: fast must be < slow")
        self.fast, self.slow = int(fast), int(slow)

    def indicators(self):
        return [("ema", self.fast), ("ema", self.slow)]

    def evaluate(self, ctx: Context) -> Optional[Direction]:
        f, s = ctx.ind("ema", self.fast), ctx.ind("ema", self.slow)
        if None in (f.value, s.value, f.prev, s.prev):
            return None
        if f.prev <= s.prev and f.value > s.value:
            return Direction.LONG
        if f.prev >= s.prev and f.value < s.value:
            return Direction.SHORT
        return None


@register("signal", "ema_trend")
class EmaTrend(Signal):
    """State (not event) signal: fast EMA above/below slow EMA.

    Mostly useful combined with an event signal (``combine: all``) or wrapped
    in a ``signal_exit``.
    """

    def __init__(self, fast: int = 20, slow: int = 50) -> None:
        self.fast, self.slow = int(fast), int(slow)

    def indicators(self):
        return [("ema", self.fast), ("ema", self.slow)]

    def evaluate(self, ctx: Context) -> Optional[Direction]:
        f, s = ctx.ind("ema", self.fast).value, ctx.ind("ema", self.slow).value
        if f is None or s is None or f == s:
            return None
        return Direction.LONG if f > s else Direction.SHORT


@register("signal", "rsi_reversion")
class RsiReversion(Signal):
    """RSI re-enters the neutral zone from oversold (long) / overbought (short)."""

    def __init__(self, period: int = 14, lower: float = 30.0, upper: float = 70.0) -> None:
        self.period, self.lower, self.upper = int(period), float(lower), float(upper)

    def indicators(self):
        return [("rsi", self.period)]

    def evaluate(self, ctx: Context) -> Optional[Direction]:
        rsi = ctx.ind("rsi", self.period)
        if rsi.value is None or rsi.prev is None:
            return None
        if rsi.prev < self.lower <= rsi.value:
            return Direction.LONG
        if rsi.prev > self.upper >= rsi.value:
            return Direction.SHORT
        return None


@register("signal", "donchian_breakout")
class DonchianBreakout(Signal):
    """Close breaks the prior N-bar high (long) / low (short)."""

    def __init__(self, period: int = 20) -> None:
        self.period = int(period)

    def indicators(self):
        return [("donchian", self.period)]

    def evaluate(self, ctx: Context) -> Optional[Direction]:
        dc = ctx.ind("donchian", self.period)
        if dc.upper is None:
            return None
        if ctx.close > dc.upper:
            return Direction.LONG
        if ctx.close < dc.lower:
            return Direction.SHORT
        return None


@register("signal", "bollinger_reversion")
class BollingerReversion(Signal):
    """Close crosses back inside the Bollinger band after closing outside."""

    def __init__(self, period: int = 20, k: float = 2.0) -> None:
        self.period, self.k = int(period), float(k)

    def indicators(self):
        return [("bollinger", self.period, self.k)]

    def evaluate(self, ctx: Context) -> Optional[Direction]:
        bb = ctx.ind("bollinger", self.period, self.k)
        prev = ctx.prev_bar
        if prev is None or bb.lower is None or bb.prev_lower is None:
            return None
        if prev.close < bb.prev_lower and ctx.close >= bb.lower:
            return Direction.LONG
        if prev.close > bb.prev_upper and ctx.close <= bb.upper:
            return Direction.SHORT
        return None
