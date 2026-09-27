"""Modular trading framework: shared building blocks, pluggable setups.

Pure Python, no third-party dependencies – runs unchanged inside QuantConnect
LEAN and in the local backtester (``backtest/``).
"""
from .blocks import Exit, Filter, Signal, Sizer, register
from .builder import available_blocks, build_engine, build_setup, build_setups
from .engine import TradingEngine
from .indicators import INDICATORS, Indicator, IndicatorHub
from .risk import RiskManager
from .setup import Setup
from .types import Bar, Context, Direction, OrderIntent, Position, Trade

__all__ = [
    "Bar", "Context", "Direction", "OrderIntent", "Position", "Trade",
    "Indicator", "IndicatorHub", "INDICATORS",
    "Signal", "Filter", "Exit", "Sizer", "register",
    "Setup", "RiskManager", "TradingEngine",
    "build_engine", "build_setup", "build_setups", "available_blocks",
]
