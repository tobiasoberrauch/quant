"""Market data for local runs: CSV loader + deterministic synthetic generator."""
from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List

from framework import Bar

_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d %H:%M", "%Y%m%d")


def _parse_time(text: str) -> datetime:
    text = text.strip()
    if text.isdigit() and len(text) >= 10:  # unix timestamp (s or ms)
        ts = int(text)
        return datetime.fromtimestamp(ts / 1000 if ts > 10**11 else ts, timezone.utc).replace(tzinfo=None)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return datetime.fromisoformat(text)


def load_csv(path: str, symbol: str) -> List[Bar]:
    """Load OHLCV bars. Header names are matched case-insensitively:
    date/time/datetime/timestamp, open, high, low, close (or adj close), volume."""
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        cols = {name.lower().strip(): name for name in reader.fieldnames or []}

        def col(*names: str) -> str:
            for n in names:
                if n in cols:
                    return cols[n]
            raise ValueError(f"{path}: none of the columns {names} found (have {list(cols)})")

        t, o, h, l, c = (col("date", "datetime", "time", "timestamp"), col("open"), col("high"),
                         col("low"), col("close", "adj close"))
        v = cols.get("volume")
        bars = []
        for row in reader:
            try:
                bars.append(Bar(symbol, _parse_time(row[t]), float(row[o]), float(row[h]),
                                float(row[l]), float(row[c]), float(row[v]) if v and row[v] else 0.0))
            except (ValueError, TypeError):
                continue  # skip malformed / null rows
    bars.sort(key=lambda b: b.time)
    return bars


def synthetic_bars(symbol: str, n: int = 2500, start: datetime = datetime(2015, 1, 2),
                   price: float = 100.0, seed: int = 7, step: timedelta = timedelta(days=1)) -> List[Bar]:
    """Regime-switching random walk (bull / bear / chop) – good enough to
    exercise every code path. Deterministic for a given ``seed`` and symbol."""
    rng = random.Random(f"{seed}-{symbol}")
    regimes = [(0.0006, 0.009), (-0.0005, 0.016), (0.0, 0.011)]  # (drift, vol) per bar
    regime, bars, t = rng.randrange(3), [], start
    for _ in range(n):
        if rng.random() < 0.01:
            regime = rng.randrange(3)
        drift, vol = regimes[regime]
        open_ = price * math.exp(rng.gauss(0, vol * 0.3))
        close = open_ * math.exp(drift + rng.gauss(0, vol))
        high = max(open_, close) * math.exp(abs(rng.gauss(0, vol * 0.5)))
        low = min(open_, close) * math.exp(-abs(rng.gauss(0, vol * 0.5)))
        bars.append(Bar(symbol, t, round(open_, 4), round(high, 4), round(low, 4), round(close, 4),
                        float(rng.randint(1_000_000, 5_000_000))))
        price = close
        t += step
        if step >= timedelta(days=1):
            while t.weekday() >= 5:
                t += timedelta(days=1)
    return bars


def merge(series: Iterable[List[Bar]]) -> List[List[Bar]]:
    """Group bars of several symbols into time steps (sorted)."""
    by_time: Dict[datetime, List[Bar]] = {}
    for bars in series:
        for bar in bars:
            by_time.setdefault(bar.time, []).append(bar)
    return [by_time[t] for t in sorted(by_time)]
