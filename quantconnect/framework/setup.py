"""A Setup = one strategy composed from shared building blocks."""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from .blocks import Exit, Filter, Signal, Sizer
from .blocks.sizing import FixedRisk
from .indicators import IndicatorSpec
from .types import Context, Direction

_DIRECTIONS = {
    "both": (Direction.LONG, Direction.SHORT),
    "long": (Direction.LONG,),
    "short": (Direction.SHORT,),
}


class Setup:
    def __init__(
        self,
        name: str,
        signals: Sequence[Signal],
        filters: Sequence[Filter] = (),
        exits: Sequence[Exit] = (),
        sizer: Optional[Sizer] = None,
        symbols: Optional[Iterable[str]] = None,
        combine: str = "all",
        direction: str = "both",
        cooldown_bars: int = 0,
    ) -> None:
        if not signals:
            raise ValueError(f"setup '{name}' needs at least one signal")
        if combine not in ("all", "any"):
            raise ValueError(f"setup '{name}': combine must be 'all' or 'any'")
        if direction not in _DIRECTIONS:
            raise ValueError(f"setup '{name}': direction must be one of {sorted(_DIRECTIONS)}")
        self.name = name
        self.signals = list(signals)
        self.filters = list(filters)
        self.exits = sorted(exits, key=lambda e: e.priority)  # stable: keeps config order
        self.sizer = sizer or FixedRisk()
        self.symbols = None if symbols is None else set(symbols)
        self.combine = combine
        self.direction = direction
        self.allowed = _DIRECTIONS[direction]
        self.cooldown_bars = int(cooldown_bars)

    def trades(self, symbol: str) -> bool:
        return self.symbols is None or symbol in self.symbols

    def blocks(self):
        return [*self.signals, *self.filters, *self.exits, self.sizer]

    def indicators(self) -> List[IndicatorSpec]:
        specs: List[IndicatorSpec] = []
        for block in self.blocks():
            specs.extend(block.indicators())
        return specs

    def raw_signal(self, ctx: Context) -> Optional[Direction]:
        votes = [s.evaluate(ctx) for s in self.signals]
        if self.combine == "any":
            return next((v for v in votes if v is not None), None)
        first = votes[0]
        if first is not None and all(v is first for v in votes):
            return first
        return None

    def entry_signal(self, ctx: Context) -> Optional[Direction]:
        direction = self.raw_signal(ctx)
        if direction is None or direction not in self.allowed:
            return None
        if all(f.allows(ctx, direction) for f in self.filters):
            return direction
        return None

    def describe(self) -> str:
        syms = "all" if self.symbols is None else ",".join(sorted(self.symbols))
        lines = [f"Setup '{self.name}' [{self.direction}] symbols={syms} combine={self.combine}"]
        for label, items in (("signals", self.signals), ("filters", self.filters),
                             ("exits", self.exits), ("sizer", [self.sizer])):
            lines.append(f"  {label:8}: " + (", ".join(map(repr, items)) or "-"))
        return "\n".join(lines)
