import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "quantconnect"))

from framework import Bar  # noqa: E402

T0 = datetime(2024, 1, 1)


def bar(i, o, h, l, c, symbol="TEST"):
    return Bar(symbol, T0 + timedelta(days=i), o, h, l, c, 1000)


def closes_to_bars(closes, symbol="TEST", spread=0.5):
    return [bar(i, c, c + spread, c - spread, c, symbol) for i, c in enumerate(closes)]
