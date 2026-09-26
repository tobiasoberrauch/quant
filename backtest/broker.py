"""Minimal simulated broker: fills intents at their reference price with slippage + fees."""
from __future__ import annotations

from typing import Dict, Tuple

from framework import OrderIntent


class SimBroker:
    def __init__(self, cash: float, commission_pct: float = 0.0005, slippage_pct: float = 0.0002,
                 min_commission: float = 0.0) -> None:
        self.cash = float(cash)
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.min_commission = min_commission
        self.holdings: Dict[str, float] = {}
        self.prices: Dict[str, float] = {}
        self.fees_paid = 0.0

    def mark(self, symbol: str, price: float) -> None:
        self.prices[symbol] = price

    def equity(self) -> float:
        return self.cash + sum(q * self.prices.get(s, 0.0) for s, q in self.holdings.items())

    def gross_exposure(self) -> float:
        return sum(abs(q * self.prices.get(s, 0.0)) for s, q in self.holdings.items())

    def fill(self, intent: OrderIntent) -> Tuple[float, float]:
        qty = intent.signed_quantity
        slip = self.slippage_pct if qty > 0 else -self.slippage_pct
        price = intent.price * (1 + slip)
        fee = max(abs(qty) * price * self.commission_pct, self.min_commission)
        self.cash -= qty * price + fee
        self.fees_paid += fee
        self.holdings[intent.symbol] = self.holdings.get(intent.symbol, 0.0) + qty
        if abs(self.holdings[intent.symbol]) < 1e-12:
            del self.holdings[intent.symbol]
        return price, fee
