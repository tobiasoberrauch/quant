"""Portfolio-level risk rules that apply across all setups."""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Optional, Tuple

from .types import Direction, Position


class RiskManager:
    def __init__(
        self,
        max_open_positions: int = 10,
        max_positions_per_symbol: int = 1,
        max_gross_exposure: float = 1.0,
        max_daily_loss_pct: Optional[float] = None,
        allow_opposing: bool = False,
    ) -> None:
        """
        max_gross_exposure  – sum of |notional| / equity (1.0 = no leverage).
                              New entries are scaled down to fit.
        max_daily_loss_pct  – e.g. 0.03 stops new entries for the rest of the
                              day once equity is 3% below the day's start.
        allow_opposing      – may one setup be long while another is short on
                              the same symbol? Brokers net these, so default off.
        """
        self.max_open_positions = int(max_open_positions)
        self.max_positions_per_symbol = int(max_positions_per_symbol)
        self.max_gross_exposure = float(max_gross_exposure)
        self.max_daily_loss_pct = max_daily_loss_pct
        self.allow_opposing = bool(allow_opposing)
        self._day: Optional[date] = None
        self._day_start_equity = 0.0
        self.halted = False

    def on_bar(self, time: datetime, equity: float) -> None:
        day = time.date()
        if day != self._day:
            self._day, self._day_start_equity, self.halted = day, equity, False
        elif self.max_daily_loss_pct is not None and self._day_start_equity > 0:
            if equity <= self._day_start_equity * (1 - self.max_daily_loss_pct):
                self.halted = True

    def approve(
        self,
        symbol: str,
        direction: Direction,
        quantity: float,
        price: float,
        equity: float,
        positions: Dict[Tuple[str, str], Position],
    ) -> Tuple[float, str]:
        """Return the approved quantity (possibly reduced; 0 = rejected) and a reason."""
        if self.halted:
            return 0.0, "daily loss limit"
        if len(positions) >= self.max_open_positions:
            return 0.0, "max open positions"
        same_symbol = [p for p in positions.values() if p.symbol == symbol]
        if len(same_symbol) >= self.max_positions_per_symbol:
            return 0.0, "max positions per symbol"
        if not self.allow_opposing and any(p.direction is not direction for p in same_symbol):
            return 0.0, "opposing position open"
        gross = sum(abs(p.quantity * p.entry_price) for p in positions.values())
        room = self.max_gross_exposure * equity - gross
        if room <= 0 or price <= 0:
            return 0.0, "max gross exposure"
        if quantity * price > room:
            return room / price, "scaled to exposure limit"
        return quantity, "ok"
