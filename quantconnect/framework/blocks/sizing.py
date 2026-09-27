"""Position sizing blocks."""
from __future__ import annotations

from typing import Optional

from ..types import Context, Direction
from .base import Sizer, register


@register("sizer", "fixed_risk")
class FixedRisk(Sizer):
    """Risk ``risk_pct`` of equity between entry and stop.

    Without a stop it falls back to ``fallback_fraction`` of equity (0 = skip).
    """

    def __init__(self, risk_pct: float = 0.01, fallback_fraction: float = 0.0,
                 max_alloc_pct: float = 1.0) -> None:
        super().__init__(max_alloc_pct)
        self.risk_pct, self.fallback_fraction = float(risk_pct), float(fallback_fraction)

    def _raw_size(self, ctx: Context, direction: Direction, entry: float,
                  stop: Optional[float]) -> float:
        if stop is None or stop == entry:
            return ctx.equity * self.fallback_fraction / entry if entry else 0.0
        return ctx.equity * self.risk_pct / abs(entry - stop)


@register("sizer", "fixed_fraction")
class FixedFraction(Sizer):
    """Allocate ``fraction`` of equity notional."""

    def __init__(self, fraction: float = 0.1, max_alloc_pct: float = 1.0) -> None:
        super().__init__(max_alloc_pct)
        self.fraction = float(fraction)

    def _raw_size(self, ctx, direction, entry, stop) -> float:
        return ctx.equity * self.fraction / entry if entry else 0.0


@register("sizer", "fixed_quantity")
class FixedQuantity(Sizer):
    def __init__(self, quantity: float = 1.0, max_alloc_pct: float = 1.0) -> None:
        super().__init__(max_alloc_pct)
        self.quantity = float(quantity)

    def _raw_size(self, ctx, direction, entry, stop) -> float:
        return self.quantity
