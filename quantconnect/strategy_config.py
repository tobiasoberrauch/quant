"""Single configuration used by QuantConnect (main.py) AND the local backtester.

Add / remove setups here – no code changes needed. Every block is referenced by
its registered ``type`` name; all other keys are constructor parameters.
Run ``python -m backtest.run --list-blocks`` to see what is available.
"""

CONFIG = {
    "backtest": {"start": (2015, 1, 1), "end": (2024, 12, 31), "cash": 100_000},
    # "minute" | "hour" | "daily"
    "resolution": "daily",
    # bars used to warm up indicators before trading (longest lookback + margin)
    "warmup_bars": 250,
    # "qc"       – QuantConnect places the orders (backtest / QC live brokerage)
    # "3commas"  – QC only generates signals and forwards them to 3Commas (live)
    # "both"     – orders in QC and mirror to 3Commas
    "execution": "qc",
    "universe": [
        {"ticker": "SPY", "type": "equity"},
        {"ticker": "QQQ", "type": "equity"},
        {"ticker": "IWM", "type": "equity"},
        # {"ticker": "BTCUSD", "type": "crypto", "market": "COINBASE", "lot_size": 0.0001},
        # {"ticker": "EURUSD", "type": "forex", "market": "OANDA", "lot_size": 1000},
    ],
    "risk": {
        "max_open_positions": 6,
        "max_positions_per_symbol": 2,
        "max_gross_exposure": 1.0,
        "max_daily_loss_pct": 0.03,
        "allow_opposing": False,
    },
    "setups": [
        {
            "name": "trend_follow",
            "enabled": True,
            "direction": "long",
            "signals": [{"type": "ema_cross", "fast": 20, "slow": 50}],
            "filters": [
                {"type": "trend", "period": 200},
                {"type": "adx", "period": 14, "min_adx": 18},
            ],
            "exits": [
                {"type": "atr_stop", "period": 14, "mult": 2.5},
                {"type": "trailing_atr", "period": 14, "mult": 3.5},
                {"type": "signal_exit", "signal": {"type": "ema_cross", "fast": 20, "slow": 50}},
            ],
            "sizer": {"type": "fixed_risk", "risk_pct": 0.01, "max_alloc_pct": 0.3},
        },
        {
            "name": "mean_reversion",
            "enabled": True,
            "direction": "long",
            "symbols": ["SPY", "QQQ"],
            "signals": [{"type": "rsi_reversion", "period": 2, "lower": 10, "upper": 90}],
            "filters": [{"type": "trend", "period": 200}],
            "exits": [
                {"type": "atr_stop", "period": 14, "mult": 2.0},
                {"type": "r_target", "r": 1.5},
                {"type": "time_exit", "max_bars": 7},
            ],
            "sizer": {"type": "fixed_risk", "risk_pct": 0.0075, "max_alloc_pct": 0.3},
        },
        {
            "name": "breakout",
            "enabled": True,
            "direction": "both",
            "cooldown_bars": 5,
            "signals": [{"type": "donchian_breakout", "period": 55}],
            "filters": [
                {"type": "volatility", "period": 20, "min_pct": 0.3, "max_pct": 5.0},
                {"type": "trend", "period": 100, "ma": "ema"},
            ],
            "exits": [
                {"type": "atr_stop", "period": 20, "mult": 2.0},
                {"type": "break_even", "trigger_r": 1.0},
                {"type": "trailing_atr", "period": 20, "mult": 3.0},
            ],
            "sizer": {"type": "fixed_risk", "risk_pct": 0.0075, "max_alloc_pct": 0.3},
        },
    ],
    # Bridge to 3Commas (used only in QC live mode or via backtest/run.py --dry-3commas)
    "threecommas": {
        "enabled": False,
        "mode": "signal_bot",          # or "dca_bot"
        "secret": "<SIGNAL_BOT_SECRET>",
        "bot_uuid": "<BOT_UUID>",
        "exchange": "BINANCE",
        "symbol_map": {"BTCUSD": "BTCUSDT"},
        "send_amount": False,          # False = let the 3Commas bot decide the size
    },
}
