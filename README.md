# Modular Trading Framework – QuantConnect · TradingView · 3Commas

Prototyp einer **modularen Trading-Architektur**: mehrere Strategien („Setups“)
werden aus denselben, wiederverwendbaren Bausteinen zusammengesteckt – ohne Code
zu duplizieren. Neue Setups entstehen per Konfiguration, neue Bausteine per
Decorator.

| Teil | Pfad | Zweck |
|---|---|---|
| Framework-Kern | `quantconnect/framework/` | Plattformunabhängiges Python (nur stdlib): Indikatoren, Bausteine, Setups, Engine, Risk-Manager |
| QuantConnect-Adapter | `quantconnect/main.py` | LEAN-Algorithmus: Daten → Engine → Orders / 3Commas |
| Konfiguration | `quantconnect/strategy_config.py` | **Eine** Config für QC *und* lokalen Backtest |
| 3Commas-Bridge | `quantconnect/framework/bridge/threecommas.py` | Signal-Bot- und DCA-Bot-Webhook-Payloads |
| Lokaler Backtester | `backtest/` | Backtest ohne QC (CSV oder synthetische Daten), Reports, CSV-Export |
| TradingView | `pinescript/modular_strategy.pine` | Gleiche Architektur in Pine v5 inkl. 3Commas-Alerts |
| Tests | `tests/` | 34 Unit-/Integrationstests inkl. QC-Adapter gegen einen API-Stub |

---

## Architektur

```
                 ┌──────────────────── strategy_config.py ────────────────────┐
                 │ universe · risk · setups[ signals, filters, exits, sizer ] │
                 └──────────────────────────────┬─────────────────────────────┘
                                                │ build_engine()
 Daten (QC / CSV)                               ▼
  ──── Bar ────►  ┌─────────────────────── TradingEngine ─────────────────────────┐
                  │ IndicatorHub (pro Symbol, geteilte Indikatoren: ema/atr/…)    │
                  │                                                               │
                  │ Setup "trend_follow"   Setup "mean_reversion"   Setup "…"     │
                  │  ├ Signals ─┐           ├ Signals               …             │
                  │  ├ Filters ─┤ Entry     ├ Filters                             │
                  │  ├ Exits   ─┤ Stops/TP  ├ Exits                               │
                  │  └ Sizer   ─┘ Menge     └ Sizer                               │
                  │                                                               │
                  │ RiskManager (Portfolio): max Positionen, Exposure, Daily-Loss │
                  └──────────────────────────────┬────────────────────────────────┘
                                                 │ OrderIntent (open/close)
                      ┌──────────────────────────┼──────────────────────────┐
                      ▼                          ▼                          ▼
              QC market_order()          SimBroker (lokal)        ThreeCommasBridge
              on_order_event →           fill → confirm()         → Webhook (live)
              engine.confirm()
```

### Die vier Bausteintypen

| Typ | Interface | Eingebaut |
|---|---|---|
| `signal` | `evaluate(ctx) -> LONG/SHORT/None` | `ema_cross`, `ema_trend`, `rsi_reversion`, `donchian_breakout`, `bollinger_reversion` |
| `filter` | `allows(ctx, direction) -> bool` | `trend`, `adx`, `volatility`, `session`, `rsi_range` |
| `exit` | `on_entry(pos, ctx)` setzt Stop/Target, `on_bar(pos, ctx)` verschiebt/liefert Exit-Grund | `atr_stop`, `percent_stop`, `r_target`, `percent_target`, `trailing_atr`, `break_even`, `time_exit`, `signal_exit` |
| `sizer` | `size(ctx, dir, entry, stop) -> qty` | `fixed_risk`, `fixed_fraction`, `fixed_quantity` |

**Wichtige Designentscheidungen**

* **Geteilte Indikatoren:** Bausteine deklarieren nur Specs wie `("atr", 14)`.
  Der `IndicatorHub` erzeugt jede Spec genau einmal pro Symbol – drei Setups mit
  ATR(14) teilen sich eine Instanz.
* **Virtuelle Positionen pro (Setup, Symbol):** Mehrere Setups teilen ein Konto;
  jedes hat eigenes Stop-/Target-Management und eine eigene Trade-Statistik.
  Der Broker sieht die Netto-Position (Test sichert Gleichheit ab).
* **Intent → Fill → Confirm:** Die Engine erzeugt `OrderIntent`s, die
  Ausführungsschicht meldet den echten Fill-Preis + Gebühr zurück
  (`confirm`) oder lehnt ab (`reject` stellt den Zustand wieder her).
* **Exits in Prioritätsreihenfolge:** Stops (0) → Targets (1) → Management (2) →
  diskretionär (3). `r_target` kennt so immer den Initial-Stop.
* **Konservative Fills:** Stop wird vor Target geprüft, wenn beide in derselben
  Kerze liegen; Gaps über den Stop füllen zum Open.
* **Portfolio-Risiko** getrennt von Setups: max. Positionen, max. Positionen je
  Symbol, Brutto-Exposure (Order wird herunterskaliert), Daily-Loss-Stop,
  gegenläufige Positionen standardmäßig verboten (Broker würde sie netten).

---

## Schnellstart (lokal, ohne QuantConnect)

Voraussetzung: Python ≥ 3.9, keine Pakete nötig.

```bash
python -m backtest.run                          # synthetische Daten, alle Setups
python -m backtest.run --describe               # Setups ausgeben
python -m backtest.run --list-blocks            # verfügbare Bausteine
python -m backtest.run --setup breakout -v      # nur ein Setup, jede Order loggen
python -m backtest.run --csv SPY=data/SPY.csv --csv QQQ=data/QQQ.csv --out results/
python -m backtest.run --dry-3commas            # Webhook-Payloads anzeigen
python -m unittest discover -s tests            # Tests
```

CSV-Format: Spalten `Date/Datetime/Timestamp, Open, High, Low, Close[, Volume]`
(z. B. Yahoo-Finance- oder Binance-Export).

> Die synthetischen Daten sind ein Random-Walk mit Regimewechseln und dienen nur
> dazu, jeden Codepfad zu durchlaufen – Performancezahlen darauf sind bedeutungslos.

Beispielausgabe:

```
=== Portfolio ===
Equity        100,000 -> 90,594
Total return   -9.41%   CAGR  -1.03%
Max drawdown   23.07%   Sharpe -0.15   Sortino -0.21   Calmar -0.04
Trades        270   fees 5,721.79

=== Per setup ===
setup              trades    win%      net pnl     PF   avg R
breakout              143   26.6%    -5,862.24   0.90   -0.01
mean_reversion        105   48.6%    -3,392.42   0.90   -0.00
trend_follow           22   27.3%      -151.17   0.99    0.02
```

---

## QuantConnect

Der Ordner `quantconnect/` **ist** das QC-Projekt (Python unterstützt
Unterordner).

* **Web-IDE:** neues Python-Projekt anlegen, `main.py`, `strategy_config.py` und
  den Ordner `framework/` mit identischer Struktur hochladen.
* **LEAN CLI:** `lean init`, dann den Ordner als Projekt verwenden:
  `lean backtest quantconnect` bzw. `lean cloud push --project quantconnect`.

Ablauf in `main.py`:

1. `initialize`: Config lesen, Wertpapiere hinzufügen (`equity`, `crypto`,
   `forex`), Engine bauen, Warm-up setzen.
2. `on_data`: TradeBar/QuoteBar → `Bar` → `engine.on_bar()` (während Warm-up
   nur Indikatoren füttern, keine Entries).
3. Jeder `OrderIntent` wird zu `market_order(..., tag="#<id>|setup|…")`.
4. `on_order_event` liest die Intent-ID aus dem Tag und ruft
   `engine.confirm(id, fill_price, fee)` bzw. `engine.reject(id)`.
5. `on_end_of_algorithm` loggt die Statistik je Setup.

`execution` in der Config:

| Wert | Verhalten |
|---|---|
| `qc` | QC handelt selbst (Backtest oder QC-Live-Brokerage) |
| `3commas` | QC erzeugt nur Signale und sendet sie live per `notify.web` an 3Commas |
| `both` | QC handelt **und** spiegelt an 3Commas |

Hinweise: Bei Daily-Auflösung füllt QC Market-Orders zum nächsten Open
(Market-on-Open), lokal wird zum Close gefüllt – Ergebnisse weichen daher leicht
ab. Stops/Targets werden von der Engine auf Bar-Basis überwacht (keine
Broker-seitigen Stop-Orders) – für Intraday-Auflösung ausreichend genau, für
Daily konservativ.

---

## TradingView + 3Commas

`pinescript/modular_strategy.pine` bildet dieselben Schichten ab:
Core-Indikatoren → geteilte Filter → Signale → Setups (je eigene Entry-ID,
Stop, Target, Trailing, Time-Exit, Filterauswahl per Checkbox) → 3Commas-JSON.

1. Script in den Pine-Editor kopieren, auf den Chart legen.
2. In den Einstellungen Setups aktivieren/konfigurieren, 3Commas *Secret* und
   *Bot UUID* eintragen.
3. **Einen** Alert anlegen: Bedingung = diese Strategie („Order fills“),
   Nachricht `{{strategy.order.alert_message}}`,
   Webhook `https://api.3commas.io/signal_bots/webhooks`.

Jede Order sendet dann `enter_long / exit_long / enter_short / exit_short`
an den Signal Bot. Neues Setup in Pine: Input-Gruppe + Signalzeile + ein
`f_run(...)`-Aufruf.

### 3Commas aus Python

```python
from framework.bridge import ThreeCommasBridge
bridge = ThreeCommasBridge(secret="…", bot_uuid="…", symbol_map={"BTCUSD": "BTCUSDT"})
payload = bridge.build(intent)   # dict
bridge.send(payload)             # POST via urllib (lokal) – in QC: self.notify.web(...)
```

Modi: `signal_bot` (empfohlen, Long+Short, beliebig viele Paare) und `dca_bot`
(Start-Deal / `close_at_market_price`). Feldnamen vor dem Live-Gang mit dem JSON
abgleichen, das 3Commas im Bot-Setup anzeigt.

---

## Erweitern

### Neues Setup (nur Config)

```python
{
    "name": "bb_reversion",
    "direction": "long",
    "symbols": ["SPY"],
    "signals": [{"type": "bollinger_reversion", "period": 20, "k": 2.0}],
    "filters": [{"type": "adx", "period": 14, "min_adx": 0, "max_adx": 25},
                {"type": "session", "start": "10:00", "end": "15:30"}],
    "exits":   [{"type": "atr_stop", "mult": 1.5}, {"type": "r_target", "r": 1.0},
                {"type": "time_exit", "max_bars": 10}],
    "sizer":   {"type": "fixed_risk", "risk_pct": 0.005},
}
```

`combine: "all"` (alle Signale müssen übereinstimmen) oder `"any"`,
`direction: long|short|both`, `cooldown_bars`, `enabled`.

### Neuer Baustein (ein Decorator)

```python
# quantconnect/framework/blocks/signals.py
@register("signal", "macd_cross")
class MacdCross(Signal):
    def __init__(self, fast=12, slow=26):
        self.fast, self.slow = fast, slow

    def indicators(self):
        return [("ema", self.fast), ("ema", self.slow)]

    def evaluate(self, ctx):
        ...  # ctx.ind("ema", self.fast).value, ctx.close, ctx.prev_bar …
        return Direction.LONG  # / Direction.SHORT / None
```

Neue Indikatoren: Klasse von `Indicator` ableiten (`_compute(bar)` gibt `None`
bis warm) und in `INDICATORS` eintragen.

---

## Projektstruktur

```
quantconnect/
  main.py                    QC-Algorithmus (Adapter)
  strategy_config.py         Universe, Risk, Setups, 3Commas
  framework/
    types.py                 Bar, Direction, Position, OrderIntent, Trade, Context
    indicators.py            SMA, EMA, RSI, ATR, ADX, Donchian, Bollinger + IndicatorHub
    blocks/                  base (Registry) · signals · filters · exits · sizing
    setup.py                 Setup = Komposition aus Bausteinen
    risk.py                  Portfolio-RiskManager
    engine.py                TradingEngine
    builder.py               Config → Engine
    bridge/threecommas.py    3Commas-Payloads + Versand
backtest/                    data · broker · metrics · run (CLI)
pinescript/                  modular_strategy.pine
tests/                       unittest-Suite
```

## Status & nächste Schritte

Getestet: Framework, lokaler Backtester, 3Commas-Payloads und der QC-Adapter
gegen einen LEAN-API-Stub (34 Tests). **Nicht** getestet in dieser Umgebung:
ein echter QuantConnect-Lauf und das Kompilieren des Pine-Scripts in
TradingView – beides beim ersten Import prüfen.

Mögliche Ausbaustufen:

* Multi-Timeframe-Filter (Consolidator in QC / `request.security` in Pine)
* Broker-seitige Stop-Orders in QC statt Bar-Überwachung
* Parameter-Optimierung / Walk-Forward über die Config
* Persistenz des Engine-Zustands für Live-Neustarts (QC ObjectStore)
* Weitere Bausteine: MACD, Supertrend, VWAP, Volumenfilter, Pyramiding
