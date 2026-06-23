# Algo Trading Terminal

A local-first personal investing and algorithmic-research terminal for Indian equities. Stage 1 provides a durable paper account, strategy registry, risk boundary, structured records, safer APIs, and a professional Flask dashboard foundation.

This is a learning and research platform. It is **not** a production trading system, investment recommendation, profitability claim, or unattended live-execution service.

## Stage 1 capabilities

- Daily OHLCV import from a configurable local source or Yahoo Finance.
- Fifteen registered technical strategies, all marked `live_disabled`.
- Indicator engineering, signal reports, and relative strategy ranking.
- SQLite-backed paper cash, positions, orders, trades, strategies, logs, risk events, and pipeline manifests.
- Persistent validated custom strategies.
- Risk checks for duplicate positions, position count, order value, kill switch, and disabled live mode.
- Explicit paper reset, exit-only sweep, recalibration, and consistent JSON API envelopes.
- Fail-closed Zerodha boundary: a live failure never becomes a paper fill.

## Stage 2 decision-grade backtesting

Stage 2 adds a separate event-driven portfolio simulator. Unlike the legacy CSV report, it records completed entry/exit trades, enforces cash and maximum positions, models sizing and liquidity, charges configurable costs, applies adverse slippage/spread, creates an equity curve, and compares against an available benchmark.

The legacy `report.py` output remains available for compatibility and is explicitly a signal-day diagnostic. It is not equivalent to a Stage 2 completed-trade backtest and should not be used as if it were a portfolio simulation.

### Run from the UI

Start the application, open the **Backtests** workspace, select a registered strategy and symbols, choose dates and assumptions, then select **Run backtest**. Results, trades, metric health, warnings, equity, and run history are stored in SQLite and exported under `reports/backtests/<run_id>/`.

### Run through the API

```powershell
$body = @{
  strategy_id = "RSI_Oversold"
  symbols = @("RELIANCE", "TCS", "INFY")
  start_date = "2020-01-01"
  end_date = "2025-12-31"
  initial_capital = 1000000
  execution_price_model = "next_open"
  direction_mode = "long_only"
  position_sizing_method = "risk_percent"
  max_positions = 10
  stop_loss_pct = 0.05
  target_pct = 0.15
  trailing_stop_pct = 0.07
  cost_model_name = "india_equity_delivery_approx"
  slippage_bps = 7
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5000/api/backtests/run -ContentType application/json -Body $body
```

The database migration runs automatically at application startup. It is additive and does not delete Stage 1 records.

### Execution models

- `next_open`: a close-observed signal executes at the next available open. This is the default for daily data.
- `next_close`: a close-observed signal executes at the next available close. The engine does not use that day's intrabar high/low for an entry made at its close.
- `signal_close_for_research_only`: executes at the observation close and is prominently warned as potentially unachievable.

Signals persisted by Stage 1 were shifted into their actionable row. The Stage 2 data adapter reconstructs their observation row, after which the selected execution model owns the delay. Synthetic engine inputs should provide observation-time signals directly.

### Costs and slippage

Named presets include zero-cost research, approximate Indian equity intraday, and approximate Indian equity delivery. Models separate brokerage, taxes/exchange charges, slippage, spread, and total costs. Rates are configurable approximations; always verify current broker, exchange, and statutory charges before operational use.

Buy fills move upward and sell fills downward by configured slippage plus half-spread. Liquidity filters can reject low-volume trades or orders above the configured share of average traded value.

### Interpreting results

Prioritize completed-trade sample size, expectancy, drawdown, exposure, cost drag, and stability—not headline return. Sharpe, Sortino, Calmar, profit factor, win rate, and benchmark-relative return all have defensive zero/no-data handling. A good historical metric is evidence about one simulation, not proof of future performance.

The robustness endpoint reruns normal, 2×/3× slippage, delayed entry, delayed exit, half sizing, and split-window scenarios. Warnings identify fragile results such as low trade count, negative expectancy, excessive drawdown, benchmark underperformance, or an edge that disappears under 2× slippage.

## Install

Python 3.10+ is recommended.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The raw source defaults to `D:\Markets\nifty`. Configure a portable source with:

```powershell
$env:ALGO_RAW_SOURCE = "D:\your\ohlcv\folder"
```

## Run

```powershell
python main.py
```

Open `http://127.0.0.1:5000`. The application remains loopback-local and paper-only. Runtime state is stored in `data/app_state.sqlite3`; structured logs are written to that database and `logs/app.log`.

## Paper account

Manual orders and scans route only to the durable paper broker. The UI labels the mode as PAPER. Reset from Settings or call:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5000/api/reset_session -ContentType application/json -Body '{"confirm":true}'
```

Reset clears active paper positions and restores starting cash. Historical orders/trades and the reset event remain available for audit.

## Custom strategies

Use Strategy Lab or POST a name and expression to `/api/add_custom_strategy`. Expressions are AST-validated before persistence. Invalid rules are retained with their validation error but cannot be enabled. Valid enabled rules reload on restart.

Example:

```text
(RSI_14 < 30) & (Close > EMA_200)
```

## Test

```powershell
pytest -q
```

Tests cover schema initialization, persistence, reset, ATR sizing, registry loading, custom rules, duplicate risk, broker fail-closed behavior, API envelopes, and corrected UI actions.

## Live-trading warning

Live trading is disabled by default and the Stage 1 broker route refuses activation. Do not enable `ALGO_LIVE_TRADING_ENABLED`. Broker reconciliation, durable live order lifecycle, partial fills, exchange calendars, comprehensive loss controls, authentication, and operational monitoring are still required.

## Current limitations

- Existing performance reports are signal-day research statistics, not realistic portfolio trade simulations.
- Report selection is in-sample and does not demonstrate future profitability.
- Recalibration remains synchronous and can take several minutes.
- Paper mark-to-market uses the latest local daily close.
- The existing dashboard is being incrementally decomposed; some future navigation areas remain presentation placeholders.
- Intrabar OHLC paths are unknown. If stop and target are both reachable in one bar, the engine chooses the stop first as a conservative convention.
- Short simulations are fully cash-secured and do not model leverage, securities lending availability, or real borrow fees.
- The India fee presets are approximations rather than broker contract notes.
- Walk-forward support evaluates fixed configurations across folds; it does not optimize parameters.
- Corporate actions, historical index membership, delistings, market impact, partial fills, and exchange holiday calendars need deeper modeling.
- Backtest profit never guarantees paper or live profit.

## Roadmap

Stage 3 should build research orchestration around this engine: versioned datasets, historical-universe membership, richer data-quality gates, experiment comparison, parameter-search controls with nested out-of-sample evaluation, and strategy-combination research. Live execution should remain disabled.
