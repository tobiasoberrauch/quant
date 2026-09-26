"""Translate engine ``OrderIntent`` objects into 3Commas webhook payloads.

Two 3Commas products are supported:

* ``signal_bot`` – "Signal Bot" custom-signal JSON (enter_long / exit_long /
  enter_short / exit_short). Recommended: one bot can serve many pairs.
* ``dca_bot``    – classic DCA bot "TradingView custom signal" JSON
  (start deal / ``close_at_market_price``). Long *or* short per bot.

The payload layout follows the 3Commas documentation at the time of writing;
double-check field names against the JSON that the 3Commas UI shows for your
bot before going live.

Sending is transport agnostic: inside QuantConnect use ``self.notify.web``,
locally ``send()`` uses ``urllib`` (stdlib only).
"""
from __future__ import annotations

import json
import urllib.request
from datetime import timezone
from typing import Any, Dict, Optional

from ..types import OrderIntent

SIGNAL_BOT_URL = "https://api.3commas.io/signal_bots/webhooks"
DCA_BOT_URL = "https://api.3commas.io/trade_signal/trading_view"


class ThreeCommasBridge:
    def __init__(
        self,
        mode: str = "signal_bot",
        secret: str = "",
        bot_uuid: str = "",
        bot_id: Optional[int] = None,
        email_token: str = "",
        exchange: str = "BINANCE",
        symbol_map: Optional[Dict[str, str]] = None,
        send_amount: bool = False,
        max_lag: int = 300,
        url: Optional[str] = None,
        enabled: bool = True,
    ) -> None:
        if mode not in ("signal_bot", "dca_bot"):
            raise ValueError("3commas mode must be 'signal_bot' or 'dca_bot'")
        self.mode = mode
        self.secret, self.bot_uuid = secret, bot_uuid
        self.bot_id, self.email_token = bot_id, email_token
        self.exchange = exchange
        self.symbol_map = dict(symbol_map or {})
        self.send_amount = send_amount
        self.max_lag = int(max_lag)
        self.url = url or (SIGNAL_BOT_URL if mode == "signal_bot" else DCA_BOT_URL)
        self.enabled = enabled

    # -------------------------------------------------------------- payloads
    def instrument(self, symbol: str) -> str:
        """Engine symbol → 3Commas instrument (e.g. BTCUSD → BTCUSDT or USDT_BTC)."""
        return self.symbol_map.get(symbol, symbol)

    def build(self, intent: OrderIntent) -> Dict[str, Any]:
        if self.mode == "signal_bot":
            return self._signal_bot(intent)
        return self._dca_bot(intent)

    def _signal_bot(self, intent: OrderIntent) -> Dict[str, Any]:
        verb = "enter" if intent.action == "open" else "exit"
        ts = intent.time
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        payload: Dict[str, Any] = {
            "secret": self.secret,
            "max_lag": str(self.max_lag),
            "timestamp": ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "trigger_price": f"{intent.price:.8f}".rstrip("0").rstrip("."),
            "tv_exchange": self.exchange,
            "tv_instrument": self.instrument(intent.symbol),
            "action": f"{verb}_{intent.direction.label}",
            "bot_uuid": self.bot_uuid,
        }
        if self.send_amount and intent.action == "open":
            payload["order"] = {
                "amount": f"{intent.quantity:.8f}".rstrip("0").rstrip("."),
                "currency_type": "base",
                "order_type": "market",
            }
        return payload

    def _dca_bot(self, intent: OrderIntent) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "message_type": "bot",
            "bot_id": self.bot_id,
            "email_token": self.email_token,
            "delay_seconds": 0,
            "pair": self.instrument(intent.symbol),
        }
        if intent.action == "close":
            payload["action"] = "close_at_market_price"
        return payload

    # -------------------------------------------------------------- transport
    def send(self, payload: Dict[str, Any], timeout: float = 10.0) -> int:
        """POST the payload (stdlib). Returns the HTTP status code."""
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https URL)
            return resp.status


def build_bridge(config: Dict[str, Any]) -> Optional[ThreeCommasBridge]:
    cfg = config.get("threecommas")
    if not cfg or not cfg.get("enabled", False):
        return None
    return ThreeCommasBridge(**cfg)


__all__ = ["ThreeCommasBridge", "build_bridge"]
