"""Build setups and the engine from a plain dict config (see ``strategy_config.py``)."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .blocks import BLOCKS, create_block
from .engine import TradingEngine
from .risk import RiskManager
from .setup import Setup


def build_setup(cfg: Dict[str, Any]) -> Setup:
    name = cfg.get("name") or "unnamed"
    try:
        return Setup(
            name=name,
            signals=[create_block("signal", s) for s in cfg.get("signals", [])],
            filters=[create_block("filter", f) for f in cfg.get("filters", [])],
            exits=[create_block("exit", e) for e in cfg.get("exits", [])],
            sizer=create_block("sizer", cfg["sizer"]) if cfg.get("sizer") else None,
            symbols=cfg.get("symbols"),
            combine=cfg.get("combine", "all"),
            direction=cfg.get("direction", "both"),
            cooldown_bars=cfg.get("cooldown_bars", 0),
        )
    except ValueError as exc:
        raise ValueError(f"setup '{name}': {exc}") from None


def build_setups(config: Dict[str, Any]) -> List[Setup]:
    return [build_setup(s) for s in config.get("setups", []) if s.get("enabled", True)]


def build_engine(config: Dict[str, Any], log: Optional[Callable[[str], None]] = None) -> TradingEngine:
    lot_sizes = {u["ticker"]: float(u.get("lot_size", 1.0)) for u in config.get("universe", [])}
    risk = RiskManager(**config.get("risk", {}))
    engine = TradingEngine(build_setups(config), risk, lot_sizes, log)
    for u in config.get("universe", []):
        engine.add_symbol(u["ticker"])
    return engine


def available_blocks() -> Dict[str, List[str]]:
    return {kind: sorted(names) for kind, names in BLOCKS.items()}
