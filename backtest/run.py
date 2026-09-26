"""Run the modular strategy locally.

Examples
    python -m backtest.run                                  # synthetic data, all setups
    python -m backtest.run --setup trend_follow --setup breakout
    python -m backtest.run --csv SPY=data/SPY.csv --csv QQQ=data/QQQ.csv
    python -m backtest.run --out results/                   # write trades.csv / equity.csv
    python -m backtest.run --dry-3commas                    # print webhook payloads
    python -m backtest.run --list-blocks
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from . import metrics  # noqa: I001  (package import sets sys.path first)
from .broker import SimBroker
from .data import load_csv, merge, synthetic_bars

from framework import Bar, Trade, available_blocks, build_engine
from framework.bridge import ThreeCommasBridge
from strategy_config import CONFIG


@dataclass
class BacktestResult:
    curve: List[Tuple[datetime, float]]
    trades: List[Trade]
    fees: float
    payloads: List[dict] = field(default_factory=list)

    def summary(self, bars_per_year: float = 252) -> Dict[str, object]:
        return {
            "equity": metrics.equity_stats(self.curve, bars_per_year),
            "trades": metrics.trade_stats(self.trades),
            "by_setup": metrics.by_setup(self.trades),
            "exit_reasons": metrics.exit_reasons(self.trades),
        }


def run_backtest(config: dict, series: Sequence[List[Bar]], cash: Optional[float] = None,
                 commission_pct: float = 0.0005, slippage_pct: float = 0.0002,
                 bridge: Optional[ThreeCommasBridge] = None, verbose: bool = False) -> BacktestResult:
    engine = build_engine(config, log=print if verbose else None)
    broker = SimBroker(cash or config["backtest"]["cash"], commission_pct, slippage_pct)
    curve: List[Tuple[datetime, float]] = []
    payloads: List[dict] = []

    def execute(intents):
        for intent in intents:
            if bridge is not None:
                payloads.append(bridge.build(intent))
            price, fee = broker.fill(intent)
            engine.confirm(intent.id, price, fee)
            if verbose:
                print(f"{intent.time:%Y-%m-%d} {intent.setup:15} {intent.action:5} "
                      f"{intent.direction.label:5} {intent.symbol:6} qty={intent.quantity:g} "
                      f"@ {price:.2f} ({intent.reason})")

    last_time = None
    for step in merge(series):
        for bar in step:
            broker.mark(bar.symbol, bar.close)
        for bar in step:
            execute(engine.on_bar(bar, broker.equity()))
        last_time = step[0].time
        curve.append((last_time, broker.equity()))

    if last_time is not None and engine.positions:
        execute(engine.close_all(dict(broker.prices), last_time, "end_of_data"))
        curve[-1] = (last_time, broker.equity())
    return BacktestResult(curve, engine.trades, broker.fees_paid, payloads)


# ---------------------------------------------------------------------- CLI
def _pct(x: float) -> str:
    return f"{100 * x:6.2f}%"


def print_report(result: BacktestResult, bars_per_year: float) -> None:
    s = result.summary(bars_per_year)
    eq, tr = s["equity"], s["trades"]
    print("\n=== Portfolio ===")
    if eq:
        print(f"Equity        {eq['start_equity']:,.0f} -> {eq['end_equity']:,.0f}")
        print(f"Total return  {_pct(eq['total_return'])}   CAGR {_pct(eq['cagr'])}")
        print(f"Max drawdown  {_pct(eq['max_drawdown'])}   Sharpe {eq['sharpe']:.2f}   "
              f"Sortino {eq['sortino']:.2f}   Calmar {eq['calmar']:.2f}")
    print(f"Trades        {tr.get('trades', 0)}   fees {result.fees:,.2f}")

    print("\n=== Per setup ===")
    print(f"{'setup':18}{'trades':>7}{'win%':>8}{'net pnl':>13}{'PF':>7}{'avg R':>8}")
    for name, st in s["by_setup"].items():
        pf = st["profit_factor"]
        print(f"{name:18}{st['trades']:>7}{100 * st['win_rate']:>7.1f}%{st['net_pnl']:>13,.2f}"
              f"{(pf if pf != float('inf') else 0):>7.2f}{st['avg_r']:>8.2f}")
    print("\n=== Exit reasons ===")
    print("  " + ", ".join(f"{k}: {v}" for k, v in s["exit_reasons"].items()))


def write_outputs(result: BacktestResult, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "equity.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "equity"])
        w.writerows((t.isoformat(), f"{v:.2f}") for t, v in result.curve)
    with open(os.path.join(out_dir, "trades.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["setup", "symbol", "direction", "qty", "entry_time", "entry_price",
                    "exit_time", "exit_price", "reason", "fees", "pnl", "r"])
        for t in result.trades:
            w.writerow([t.setup, t.symbol, t.direction.label, t.quantity, t.entry_time.isoformat(),
                        f"{t.entry_price:.4f}", t.exit_time.isoformat(), f"{t.exit_price:.4f}",
                        t.reason, f"{t.fees:.2f}", f"{t.pnl:.2f}",
                        "" if t.r_multiple is None else f"{t.r_multiple:.2f}"])
    print(f"\nWrote {out_dir}/equity.csv and {out_dir}/trades.csv")


def main(argv: Optional[Sequence[str]] = None) -> BacktestResult:
    p = argparse.ArgumentParser(description="Local backtest of the modular strategy framework")
    p.add_argument("--csv", action="append", default=[], metavar="SYMBOL=PATH",
                   help="OHLCV csv per symbol (repeatable). Without it synthetic data is used.")
    p.add_argument("--bars", type=int, default=2500, help="synthetic bars per symbol")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--cash", type=float)
    p.add_argument("--commission", type=float, default=0.0005, help="fraction of notional")
    p.add_argument("--slippage", type=float, default=0.0002, help="fraction of price")
    p.add_argument("--bars-per-year", type=float, default=252)
    p.add_argument("--setup", action="append", help="only run these setups (repeatable)")
    p.add_argument("--config", help="JSON file overriding strategy_config.CONFIG")
    p.add_argument("--out", help="directory for trades.csv / equity.csv")
    p.add_argument("--dry-3commas", action="store_true", help="print the webhook payloads that would be sent")
    p.add_argument("--list-blocks", action="store_true")
    p.add_argument("--describe", action="store_true", help="print the configured setups")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    if args.list_blocks:
        for kind, names in available_blocks().items():
            print(f"{kind:7}: {', '.join(names)}")
        raise SystemExit(0)

    config = copy.deepcopy(CONFIG)
    if args.config:
        with open(args.config) as fh:
            config = json.load(fh)
    if args.setup:
        known = {s["name"] for s in config["setups"]}
        unknown = set(args.setup) - known
        if unknown:
            p.error(f"unknown setup(s) {sorted(unknown)}; known: {sorted(known)}")
        config["setups"] = [s for s in config["setups"] if s["name"] in args.setup]

    if args.describe:
        for setup in build_engine(config).setups:
            print(setup.describe())

    if args.csv:
        series = []
        for item in args.csv:
            symbol, _, path = item.partition("=")
            series.append(load_csv(path, symbol))
        tickers = {bars[0].symbol for bars in series if bars}
        config["universe"] = [u for u in config["universe"] if u["ticker"] in tickers] + [
            {"ticker": t} for t in tickers - {u["ticker"] for u in config["universe"]}]
    else:
        series = [synthetic_bars(u["ticker"], args.bars, seed=args.seed) for u in config["universe"]]

    bridge = None
    if args.dry_3commas:
        bridge = ThreeCommasBridge(**{**config.get("threecommas", {}), "enabled": True})

    result = run_backtest(config, series, args.cash, args.commission, args.slippage, bridge, args.verbose)
    print_report(result, args.bars_per_year)
    if bridge is not None:
        print("\n=== 3Commas payloads (first 5) ===")
        for payload in result.payloads[:5]:
            print(json.dumps(payload))
    if args.out:
        write_outputs(result, args.out)
    return result


if __name__ == "__main__":
    main()
