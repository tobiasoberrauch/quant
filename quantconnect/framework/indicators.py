"""Streaming indicators + a per-symbol hub that shares them between blocks.

Blocks never own indicators. They *declare* them as specs such as
``("ema", 50)`` and the hub creates each unique spec once per symbol. Two
setups that both use ``("atr", 14)`` therefore share one ATR instance.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any, Deque, Dict, Optional, Tuple, Type

from .types import Bar

IndicatorSpec = Tuple[Any, ...]


class Indicator:
    """Base class. ``value`` is ``None`` until the indicator is warmed up."""

    def __init__(self) -> None:
        self.value: Optional[float] = None
        self.prev: Optional[float] = None
        self.samples = 0

    @property
    def ready(self) -> bool:
        return self.value is not None

    def update(self, bar: Bar) -> None:
        self.samples += 1
        self.prev = self.value
        self.value = self._compute(bar)

    def _compute(self, bar: Bar) -> Optional[float]:  # pragma: no cover
        raise NotImplementedError


class SMA(Indicator):
    def __init__(self, period: int) -> None:
        super().__init__()
        self.period = int(period)
        self._window: Deque[float] = deque(maxlen=self.period)
        self._sum = 0.0

    def _compute(self, bar: Bar) -> Optional[float]:
        if len(self._window) == self.period:
            self._sum -= self._window[0]
        self._window.append(bar.close)
        self._sum += bar.close
        if len(self._window) < self.period:
            return None
        return self._sum / self.period


class EMA(Indicator):
    """EMA seeded with the SMA of the first ``period`` closes."""

    def __init__(self, period: int) -> None:
        super().__init__()
        self.period = int(period)
        self._alpha = 2.0 / (self.period + 1)
        self._seed: list = []

    def _compute(self, bar: Bar) -> Optional[float]:
        if self.value is None:
            self._seed.append(bar.close)
            if len(self._seed) < self.period:
                return None
            return sum(self._seed) / self.period
        return self.value + self._alpha * (bar.close - self.value)


class RSI(Indicator):
    """Wilder's RSI."""

    def __init__(self, period: int = 14) -> None:
        super().__init__()
        self.period = int(period)
        self._prev_close: Optional[float] = None
        self._gains: list = []
        self._losses: list = []
        self._avg_gain: Optional[float] = None
        self._avg_loss: Optional[float] = None

    def _compute(self, bar: Bar) -> Optional[float]:
        if self._prev_close is None:
            self._prev_close = bar.close
            return None
        change = bar.close - self._prev_close
        self._prev_close = bar.close
        gain, loss = max(change, 0.0), max(-change, 0.0)
        n = self.period
        if self._avg_gain is None:
            self._gains.append(gain)
            self._losses.append(loss)
            if len(self._gains) < n:
                return None
            self._avg_gain = sum(self._gains) / n
            self._avg_loss = sum(self._losses) / n
        else:
            self._avg_gain = (self._avg_gain * (n - 1) + gain) / n
            self._avg_loss = (self._avg_loss * (n - 1) + loss) / n
        if self._avg_loss == 0:
            return 100.0 if self._avg_gain > 0 else 50.0
        rs = self._avg_gain / self._avg_loss
        return 100.0 - 100.0 / (1.0 + rs)


def _true_range(bar: Bar, prev_close: Optional[float]) -> float:
    if prev_close is None:
        return bar.high - bar.low
    return max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close))


class ATR(Indicator):
    """Wilder's Average True Range."""

    def __init__(self, period: int = 14) -> None:
        super().__init__()
        self.period = int(period)
        self._prev_close: Optional[float] = None
        self._seed: list = []

    def _compute(self, bar: Bar) -> Optional[float]:
        tr = _true_range(bar, self._prev_close)
        self._prev_close = bar.close
        if self.value is None:
            self._seed.append(tr)
            if len(self._seed) < self.period:
                return None
            return sum(self._seed) / self.period
        return (self.value * (self.period - 1) + tr) / self.period


class ADX(Indicator):
    """Wilder's ADX; also exposes ``plus_di`` / ``minus_di``."""

    def __init__(self, period: int = 14) -> None:
        super().__init__()
        self.period = int(period)
        self.plus_di: Optional[float] = None
        self.minus_di: Optional[float] = None
        self._prev: Optional[Bar] = None
        self._seed: list = []
        self._dx_seed: list = []
        self._tr = self._pdm = self._mdm = 0.0
        self._smoothed = False

    def _compute(self, bar: Bar) -> Optional[float]:
        prev, self._prev = self._prev, bar
        if prev is None:
            return None
        up, down = bar.high - prev.high, prev.low - bar.low
        pdm = up if up > down and up > 0 else 0.0
        mdm = down if down > up and down > 0 else 0.0
        tr = _true_range(bar, prev.close)
        n = self.period
        if not self._smoothed:
            self._seed.append((tr, pdm, mdm))
            if len(self._seed) < n:
                return None
            self._tr = sum(s[0] for s in self._seed)
            self._pdm = sum(s[1] for s in self._seed)
            self._mdm = sum(s[2] for s in self._seed)
            self._smoothed = True
        else:
            self._tr = self._tr - self._tr / n + tr
            self._pdm = self._pdm - self._pdm / n + pdm
            self._mdm = self._mdm - self._mdm / n + mdm
        self.plus_di = 100.0 * self._pdm / self._tr if self._tr else 0.0
        self.minus_di = 100.0 * self._mdm / self._tr if self._tr else 0.0
        di_sum = self.plus_di + self.minus_di
        dx = 100.0 * abs(self.plus_di - self.minus_di) / di_sum if di_sum else 0.0
        if self.value is None:
            self._dx_seed.append(dx)
            if len(self._dx_seed) < n:
                return None
            return sum(self._dx_seed) / n
        return (self.value * (n - 1) + dx) / n


class Donchian(Indicator):
    """Highest high / lowest low of the *previous* ``period`` bars.

    The current bar is excluded so that ``close > upper`` is a real breakout.
    ``value`` is the channel midline.
    """

    def __init__(self, period: int = 20) -> None:
        super().__init__()
        self.period = int(period)
        self.upper: Optional[float] = None
        self.lower: Optional[float] = None
        self._highs: Deque[float] = deque(maxlen=self.period)
        self._lows: Deque[float] = deque(maxlen=self.period)

    def _compute(self, bar: Bar) -> Optional[float]:
        if len(self._highs) == self.period:
            self.upper, self.lower = max(self._highs), min(self._lows)
        self._highs.append(bar.high)
        self._lows.append(bar.low)
        if self.upper is None:
            return None
        return (self.upper + self.lower) / 2.0


class Bollinger(Indicator):
    """Bollinger bands; ``value`` is the middle band. Keeps previous bands."""

    def __init__(self, period: int = 20, k: float = 2.0) -> None:
        super().__init__()
        self.period = int(period)
        self.k = float(k)
        self.upper: Optional[float] = None
        self.lower: Optional[float] = None
        self.prev_upper: Optional[float] = None
        self.prev_lower: Optional[float] = None
        self._window: Deque[float] = deque(maxlen=self.period)

    def _compute(self, bar: Bar) -> Optional[float]:
        self._window.append(bar.close)
        self.prev_upper, self.prev_lower = self.upper, self.lower
        if len(self._window) < self.period:
            return None
        mean = sum(self._window) / self.period
        std = math.sqrt(sum((x - mean) ** 2 for x in self._window) / self.period)
        self.upper, self.lower = mean + self.k * std, mean - self.k * std
        return mean


INDICATORS: Dict[str, Type[Indicator]] = {
    "sma": SMA,
    "ema": EMA,
    "rsi": RSI,
    "atr": ATR,
    "adx": ADX,
    "donchian": Donchian,
    "bollinger": Bollinger,
}


class IndicatorHub:
    """Owns all indicators for one symbol and feeds them bar by bar."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.bars = 0
        self.last_bar: Optional[Bar] = None
        self.prev_bar: Optional[Bar] = None
        self._indicators: Dict[IndicatorSpec, Indicator] = {}

    def register(self, spec: IndicatorSpec) -> Indicator:
        name, *params = spec
        key = (name, *params)
        if key not in self._indicators:
            if name not in INDICATORS:
                raise ValueError(f"Unknown indicator '{name}'. Available: {sorted(INDICATORS)}")
            self._indicators[key] = INDICATORS[name](*params)
        return self._indicators[key]

    def get(self, name: str, *params: Any) -> Indicator:
        # Lazily registering keeps blocks robust, but engines pre-register so
        # every indicator sees the full history from the first bar.
        return self.register((name, *params))

    def update(self, bar: Bar) -> None:
        self.prev_bar, self.last_bar = self.last_bar, bar
        self.bars += 1
        for indicator in self._indicators.values():
            indicator.update(bar)

    def __len__(self) -> int:
        return len(self._indicators)
