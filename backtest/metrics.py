"""Performance statistics."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, List, Sequence, Tuple

from framework import Trade


def equity_stats(curve: Sequence[Tuple[datetime, float]], bars_per_year: float = 252) -> Dict[str, float]:
    if len(curve) < 2:
        return {}
    values = [v for _, v in curve]
    rets = [values[i] / values[i - 1] - 1 for i in range(1, len(values)) if values[i - 1] > 0]
    mean = sum(rets) / len(rets)
    std = math.sqrt(sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1))
    downside = math.sqrt(sum(min(r, 0) ** 2 for r in rets) / max(len(rets), 1))
    peak, max_dd = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        max_dd = max(max_dd, 1 - v / peak)
    years = max((curve[-1][0] - curve[0][0]).days / 365.25, 1e-9)
    total = values[-1] / values[0] - 1
    cagr = (values[-1] / values[0]) ** (1 / years) - 1 if values[-1] > 0 else -1.0
    return {
        "start_equity": values[0],
        "end_equity": values[-1],
        "total_return": total,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "sharpe": mean / std * math.sqrt(bars_per_year) if std else 0.0,
        "sortino": mean / downside * math.sqrt(bars_per_year) if downside else 0.0,
        "calmar": cagr / max_dd if max_dd else 0.0,
    }


def trade_stats(trades: List[Trade]) -> Dict[str, float]:
    if not trades:
        return {"trades": 0}
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl <= 0]
    rs = [t.r_multiple for t in trades if t.r_multiple is not None]
    return {
        "trades": len(trades),
        "win_rate": len(wins) / len(trades),
        "net_pnl": sum(t.pnl for t in trades),
        "profit_factor": sum(wins) / -sum(losses) if losses and sum(losses) else float("inf"),
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "avg_r": sum(rs) / len(rs) if rs else 0.0,
        "fees": sum(t.fees for t in trades),
    }


def by_setup(trades: List[Trade]) -> Dict[str, Dict[str, float]]:
    groups: Dict[str, List[Trade]] = {}
    for t in trades:
        groups.setdefault(t.setup, []).append(t)
    return {name: trade_stats(ts) for name, ts in sorted(groups.items())}


def exit_reasons(trades: List[Trade]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for t in trades:
        out[t.reason] = out.get(t.reason, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
