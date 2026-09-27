"""Block base classes and the block registry.

There are four kinds of building blocks:

* ``signal`` – proposes an entry direction (``evaluate(ctx) -> Direction | None``)
* ``filter`` – vetoes an entry (``allows(ctx, direction) -> bool``)
* ``exit``   – sets / moves stop + target and can request a discretionary exit
* ``sizer``  – converts equity + stop distance into a quantity

New blocks are plugged in with the ``@register(kind, name)`` decorator and are
then usable from the JSON-like config by ``{"type": name, ...params}``.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

from ..indicators import IndicatorSpec
from ..types import Context, Direction, Position

KINDS = ("signal", "filter", "exit", "sizer")
BLOCKS: Dict[str, Dict[str, type]] = {kind: {} for kind in KINDS}

T = TypeVar("T", bound=type)


def register(kind: str, name: str) -> Callable[[T], T]:
    if kind not in BLOCKS:
        raise ValueError(f"Unknown block kind '{kind}', expected one of {KINDS}")

    def decorator(cls: T) -> T:
        if name in BLOCKS[kind]:
            raise ValueError(f"{kind} block '{name}' registered twice")
        BLOCKS[kind][name] = cls
        cls.type_name = name  # type: ignore[attr-defined]
        return cls

    return decorator


def create_block(kind: str, spec: Dict[str, Any]):
    params = dict(spec)
    try:
        name = params.pop("type")
    except KeyError:
        raise ValueError(f"{kind} spec {spec!r} has no 'type'") from None
    cls: Optional[Type] = BLOCKS[kind].get(name)
    if cls is None:
        raise ValueError(f"Unknown {kind} '{name}'. Available: {sorted(BLOCKS[kind])}")
    try:
        return cls(**params)
    except TypeError as exc:
        raise ValueError(f"Bad parameters for {kind} '{name}': {exc}") from None


class Block:
    type_name = "?"

    def indicators(self) -> List[IndicatorSpec]:
        """Indicator specs this block reads, e.g. ``[("ema", 20)]``."""
        return []

    def __repr__(self) -> str:
        params = ", ".join(f"{k}={v!r}" for k, v in vars(self).items() if not k.startswith("_"))
        return f"{self.type_name}({params})"


class Signal(Block):
    def evaluate(self, ctx: Context) -> Optional[Direction]:  # pragma: no cover
        raise NotImplementedError


class Filter(Block):
    def allows(self, ctx: Context, direction: Direction) -> bool:  # pragma: no cover
        raise NotImplementedError


class Exit(Block):
    """Exit blocks run in ``priority`` order (stops → targets → management)."""

    priority = 2

    def on_entry(self, pos: Position, ctx: Context) -> None:
        """Called once when a position is created (before sizing)."""

    def on_bar(self, pos: Position, ctx: Context) -> Optional[str]:
        """Called on every following bar. Return a reason to exit at the close."""
        return None


class Sizer(Block):
    def __init__(self, max_alloc_pct: float = 1.0) -> None:
        self.max_alloc_pct = float(max_alloc_pct)

    def size(self, ctx: Context, direction: Direction, entry: float, stop: Optional[float]) -> float:
        qty = self._raw_size(ctx, direction, entry, stop)
        if entry > 0:
            qty = min(qty, ctx.equity * self.max_alloc_pct / entry)
        return max(qty, 0.0)

    def _raw_size(self, ctx: Context, direction: Direction, entry: float,
                  stop: Optional[float]) -> float:  # pragma: no cover
        raise NotImplementedError
