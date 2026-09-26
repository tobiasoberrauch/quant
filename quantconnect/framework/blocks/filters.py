"""Filter blocks: each one can veto an entry."""
from __future__ import annotations

from datetime import time as dtime
from typing import Iterable, Optional

from ..types import Context, Direction
from .base import Filter, register


@register("filter", "trend")
class TrendFilter(Filter):
    """Long only above the moving average, short only below it."""

    def __init__(self, period: int = 200, ma: str = "sma") -> None:
        if ma not in ("sma", "ema"):
            raise ValueError("trend filter: ma must be 'sma' or 'ema'")
        self.period, self.ma = int(period), ma

    def indicators(self):
        return [(self.ma, self.period)]

    def allows(self, ctx: Context, direction: Direction) -> bool:
        ma = ctx.ind(self.ma, self.period).value
        if ma is None:
            return False
        return ctx.close > ma if direction is Direction.LONG else ctx.close < ma


@register("filter", "adx")
class AdxFilter(Filter):
    """Require trend strength (``min_adx``) or its absence (``max_adx``)."""

    def __init__(self, period: int = 14, min_adx: float = 20.0,
                 max_adx: Optional[float] = None, require_di: bool = False) -> None:
        self.period, self.min_adx, self.max_adx = int(period), float(min_adx), max_adx
        self.require_di = bool(require_di)

    def indicators(self):
        return [("adx", self.period)]

    def allows(self, ctx: Context, direction: Direction) -> bool:
        adx = ctx.ind("adx", self.period)
        if adx.value is None:
            return False
        if adx.value < self.min_adx:
            return False
        if self.max_adx is not None and adx.value > self.max_adx:
            return False
        if self.require_di:
            bullish = adx.plus_di > adx.minus_di
            return bullish if direction is Direction.LONG else not bullish
        return True


@register("filter", "volatility")
class VolatilityFilter(Filter):
    """ATR as % of price must be within ``[min_pct, max_pct]``."""

    def __init__(self, period: int = 14, min_pct: float = 0.0, max_pct: float = 100.0) -> None:
        self.period, self.min_pct, self.max_pct = int(period), float(min_pct), float(max_pct)

    def indicators(self):
        return [("atr", self.period)]

    def allows(self, ctx: Context, direction: Direction) -> bool:
        atr = ctx.ind("atr", self.period).value
        if atr is None or ctx.close <= 0:
            return False
        pct = 100.0 * atr / ctx.close
        return self.min_pct <= pct <= self.max_pct


@register("filter", "session")
class SessionFilter(Filter):
    """Only trade between ``start`` and ``end`` (HH:MM, bar time) on given weekdays."""

    def __init__(self, start: str = "00:00", end: str = "23:59",
                 weekdays: Iterable[int] = (0, 1, 2, 3, 4)) -> None:
        self.start, self.end = start, end
        self.weekdays = tuple(int(d) for d in weekdays)
        self._start = dtime.fromisoformat(start)
        self._end = dtime.fromisoformat(end)

    def allows(self, ctx: Context, direction: Direction) -> bool:
        t = ctx.time
        if t.weekday() not in self.weekdays:
            return False
        now = t.time()
        if self._start <= self._end:
            return self._start <= now <= self._end
        return now >= self._start or now <= self._end  # overnight session


@register("filter", "rsi_range")
class RsiRangeFilter(Filter):
    """Avoid chasing: long only if RSI < ``max_long``, short only if RSI > ``min_short``."""

    def __init__(self, period: int = 14, max_long: float = 70.0, min_short: float = 30.0) -> None:
        self.period, self.max_long, self.min_short = int(period), float(max_long), float(min_short)

    def indicators(self):
        return [("rsi", self.period)]

    def allows(self, ctx: Context, direction: Direction) -> bool:
        rsi = ctx.ind("rsi", self.period).value
        if rsi is None:
            return False
        return rsi < self.max_long if direction is Direction.LONG else rsi > self.min_short
