"""Core data types shared by every building block.

Everything in ``framework`` is plain Python (no QuantConnect / pandas imports),
so the exact same code runs inside LEAN and in the local backtester.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:  # pragma: no cover
    from .indicators import Indicator, IndicatorHub


class Direction(IntEnum):
    LONG = 1
    SHORT = -1

    @property
    def label(self) -> str:
        return "long" if self is Direction.LONG else "short"

    @property
    def opposite(self) -> "Direction":
        return Direction.SHORT if self is Direction.LONG else Direction.LONG


@dataclass(frozen=True)
class Bar:
    symbol: str
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Position:
    """A virtual position owned by exactly one setup on one symbol."""

    setup: str
    symbol: str
    direction: Direction
    quantity: float
    entry_price: float
    entry_time: datetime
    stop: Optional[float] = None
    target: Optional[float] = None
    initial_stop: Optional[float] = None
    bars_held: int = 0
    highest: float = 0.0
    lowest: float = 0.0
    entry_fee: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def risk_per_unit(self) -> Optional[float]:
        if self.initial_stop is None:
            return None
        risk = abs(self.entry_price - self.initial_stop)
        return risk or None

    def unrealized(self, price: float) -> float:
        return (price - self.entry_price) * self.quantity * self.direction

    def favorable_excursion(self) -> float:
        """Best price move in the trade's favour (per unit)."""
        if self.direction is Direction.LONG:
            return self.highest - self.entry_price
        return self.entry_price - self.lowest


@dataclass
class OrderIntent:
    """What the engine wants the execution layer to do.

    The execution layer (QuantConnect, local simulator, 3Commas) fills it and
    reports back via ``TradingEngine.confirm`` / ``TradingEngine.reject``.
    """

    id: int
    action: str  # "open" | "close"
    setup: str
    symbol: str
    direction: Direction  # direction of the *position*, not of the order
    quantity: float
    price: float  # reference price (bar close, stop or target level)
    time: datetime
    reason: str = ""
    stop: Optional[float] = None
    target: Optional[float] = None

    @property
    def signed_quantity(self) -> float:
        """+ = buy, - = sell."""
        sign = int(self.direction) if self.action == "open" else -int(self.direction)
        return self.quantity * sign

    @property
    def tag(self) -> str:
        return f"#{self.id}|{self.setup}|{self.action}|{self.direction.label}|{self.reason}"


@dataclass
class Trade:
    setup: str
    symbol: str
    direction: Direction
    quantity: float
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    reason: str
    fees: float = 0.0
    initial_stop: Optional[float] = None

    @property
    def gross_pnl(self) -> float:
        return (self.exit_price - self.entry_price) * self.quantity * self.direction

    @property
    def pnl(self) -> float:
        return self.gross_pnl - self.fees

    @property
    def r_multiple(self) -> Optional[float]:
        if self.initial_stop is None:
            return None
        risk = abs(self.entry_price - self.initial_stop) * self.quantity
        return self.gross_pnl / risk if risk else None


@dataclass
class Context:
    """Everything a block may look at when it is evaluated."""

    symbol: str
    bar: Bar
    hub: "IndicatorHub"
    equity: float

    @property
    def time(self) -> datetime:
        return self.bar.time

    @property
    def close(self) -> float:
        return self.bar.close

    @property
    def prev_bar(self) -> Optional[Bar]:
        return self.hub.prev_bar

    def ind(self, name: str, *params: Any) -> "Indicator":
        return self.hub.get(name, *params)
