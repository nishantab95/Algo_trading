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

Prioritize completed-trade sample size, expectancy, drawdown, exposure, cost drag, and stabilityâ€”not headline return. Sharpe, Sortino, Calmar, profit factor, win rate, and benchmark-relative return all have defensive zero/no-data handling. A good historical metric is evidence about one simulation, not proof of future performance.

The robustness endpoint reruns normal, 2Ã—/3Ã— slippage, delayed entry, delayed exit, half sizing, and split-window scenarios. Warnings identify fragile results such as low trade count, negative expectancy, excessive drawdown, benchmark underperformance, or an edge that disappears under 2Ã— slippage.

## Stage 3 strategy research factory

Stage 3 adds a config-driven library of more than 230 base research definitions and 120 combo definitions. The count describes catalog coverageâ€”not quality or profitability. Strategies supported by current daily OHLCV and technical columns can generate observation-time signals for the Stage 2 engine. Definitions requiring fundamentals, historical constituents, sector mappings, intraday bars, pivots, market profile, pairs, or option chains remain visible with `needs_data`, `needs_intraday_data`, or `simulation_only` status.

### Strategy registry model

Each definition stores metadata, data requirements, parameters, entry/filter logic, default exits, risk settings, tags, learning notes, and an explanation template. Reusable primitives evaluate comparisons, crossovers, trend structure, momentum, volatility, volume, price action, support/resistance, and logical combinations without future-row access.

Use the **Library** workspace to search and filter definitions, inspect requirements and JSON logic, validate a candidate, enable supported definitions, and open one in the Stage 2 Backtesting Lab.

### Add a base strategy

Add a `CatalogStrategy` configuration through the appropriate module under `app/strategies/builtin/`, using primitives exposed by `/api/strategy-primitives`. Required columns must be declared. Run validation and synthetic tests before marking it active. Never mark an unavailable-data idea active merely to increase the count.

```python
CatalogStrategy(
    strategy_id="TREND_EMA_009_021",
    name="EMA 9/21 Bullish Crossover",
    category="trend",
    subcategory="ema_crossover",
    direction="long",
    entry={"primitive": "crossover_above", "args": ["EMA_9", "EMA_21"]},
    filters={"primitive": "greater_than", "args": ["Close", "EMA_200"]},
)
```

### Combo Builder

The **Combo builder** workspace combines primitives or base strategies using `all`, `any`, `weighted_vote`, `min_confirmations`, or `score_threshold`. Each component can carry a weight. Saved combos include exits and risk settings, persist in SQLite, and must validate before they can be enabled or passed into Stage 2.

```text
combo config â†’ validate components â†’ generate component signals
â†’ combine observation-time signals â†’ Stage 2 backtest â†’ persisted reports
```

Validation checks metadata, primitive names, entry logic, required columns, timeframe, direction compatibility, and component references. Unsupported definitions are not silently skipped. Their status and reason appear in the API and UI. Simulation-only options definitions cannot route to paper or live execution.

Many research candidates increase multiple-testing risk. A large library makes disciplined out-of-sample controls more important; it does not make historical results more trustworthy by itself.

## Stage 4 local assistant, RAG, search, profile, and dashboards

Stage 4 adds a local LM Studio assistant around the rule-based platform. The assistant is an explainer, search interface, drafting helper, dashboard helper, and profile assistant. It is **not** the trading engine. Strategy definitions remain the trading brain, Stage 2 remains the evidence engine, the risk manager remains the gatekeeper, and the user remains the final decision-maker.

The assistant uses lightweight SQLite-backed keyword retrieval across documentation, strategies, combos, backtests, paper activity, risk events, logs, profiles, dashboards, and conversations. No embedding model, vector database, LangChain, or ML/DL prediction package is used.

Configure LM Studio with environment variables before starting the app:

```powershell
$env:LLM_ENABLED = "true"
$env:LLM_PROVIDER = "lmstudio"
$env:LLM_BASE_URL = "http://localhost:1234/v1"
$env:LLM_MODEL = "qwen3.5-9b"
$env:LLM_TIMEOUT_SECONDS = "60"
$env:LLM_ACTION_APPROVAL_REQUIRED = "true"
$env:RAG_ENABLED = "true"
$env:RAG_MODE = "sqlite_fts"
```

LM Studio may be offline: Flask still starts, local RAG/search remains available, and chat returns a clear offline response. Use **Search â†’ Reindex** to rebuild local retrieval records. Use **Profile** and **Dashboards** to create preview drafts; approve or reject the exact draft before any database mutation executes.

Assistant capabilities include searching RSI/EMA strategies, explaining backtests, showing paper/backtest trade history, reviewing risk events, drafting strategy/combo changes, drafting paper orders, updating the trading profile, and building allowlisted dashboards. It cannot place live orders, enable live trading, alter broker credentials, disable the risk manager, run arbitrary Python, approve its own actions, or bypass validation/backtesting.

## Install

Project venv Python path:

```text
C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe
```

Use only this interpreter. Do not create another project venv.

```powershell
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" -m pip install --upgrade pip
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" -m pip install -r requirements.txt
```

The raw source defaults to `D:\Markets\nifty`. Configure a portable source with:

```powershell
$env:ALGO_RAW_SOURCE = "D:\your\ohlcv\folder"
```

## Run

```powershell
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" main.py
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
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" -m pytest -q
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" -m pytest tests/test_backtesting_stage2.py -q
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" -m pytest tests/test_strategy_factory_stage3.py -q
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" -m pytest tests/test_stage4_assistant_rag.py -q
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" -m pytest tests/test_stage5_paper_trading.py -q
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" -m pytest tests/test_stage6_research_lab.py -q
```

Tests cover schema initialization, persistence, reset, ATR sizing, registry loading, custom rules, duplicate risk, broker fail-closed behavior, API envelopes, and corrected UI actions.

The standardized API contract always includes `success`, `data`, and `warnings` on success, or `success`, `error`, and `details` on failure. Compatibility aliases remain temporarily available for the original dashboard JavaScript.

Stage 2 and Stage 3 suites additionally cover execution timing, completed-trade lifecycle, costs, sizing, metrics, 230+ strategy definitions, 120 combos, primitive truth tables, validation, explanations, persistence, and Stage 2 routing.

Verify the config-driven catalog counts without starting Flask:

```powershell
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" -c "from app.strategies.catalog import load_base_strategy_catalog; print('base_count=', len(load_base_strategy_catalog()))"
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" -c "from app.strategies.combos.combo_registry import load_combo_strategy_catalog; print('combo_count=', len(load_combo_strategy_catalog()))"
```

The repository currently contains 233 base definitions (230 named equity/portfolio research definitions plus three options simulations) and 120 combo definitions. The acceptance audit also confirmed both counts at runtime with the commands above.

Runtime checks confirmed 233 base strategies and 120 combos. Before Stage 4, 95 tests passed; after the Stage 4 safety audit, the full suite passed with 139 tests (44 dedicated Stage 4 tests), including a real `main.py` HTTP startup test.

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
- Catalogued strategies with unavailable dependencies cannot generate signals until those datasets exist.
- Combo market and sector filters remain unavailable without synchronized context data.
- Bulk-testing a large catalog without false-discovery controls invites spurious winners.
- Keyword RAG is transparent and lightweight but less semantic than embedding retrieval.
- LM Studio must run separately for generated answers; deterministic app search works offline.
- Stage 4 trade-history annotations and the Stage 5 behavioral journal are separate views over their respective persisted records.
- Assistant actions are local approval drafts; the app currently has no multi-user authentication boundary.

## Roadmap

Stage 4 is implemented and remains the assistant/search layer. Stage 5 now adds the durable paper-operations layer described below. Live trading remains disabled.

## Stage 5 paper trading and portfolio operations

Stage 5 replaces the toy â€œclick buy, show a positionâ€ pattern with an approval-gated broker simulator. The durable flow is: order draft â†’ deterministic validation â†’ risk check â†’ explicit user approval â†’ submitted paper order â†’ simulated fill â†’ cash and position accounting â†’ account snapshot â†’ journal and analytics. It never calls the live Zerodha broker.

The default account is long-only, cash-backed, and unleveraged. Cash cannot become negative. Account state, orders, status-transition events, fills, positions, reset archives, snapshots, completed-trade journal entries, and strategy reviews are stored in SQLite through additive migration 7. A reset requires `{ "confirm": true }` and archives the prior account state before clearing Stage 5 operational records.

Supported orders are market, limit, stop, and stop-limit. Market fills apply configurable slippage, spread, and fees. Limit orders wait for the price condition; stop orders wait for the trigger; stop-limit orders trigger before testing their limit. Rejections record a rule and reason for invalid quantity, unavailable/stale price, insufficient cash, excessive order value, duplicate position, prohibited averaging down, liquidity, price range, position count, missing stop, or kill-switch state. Partial fill is represented in the lifecycle for future liquidity modeling; the current deterministic simulator fills an accepted quantity in full.

Position accounting supports increases when explicitly enabled, weighted average price, partial and full exits, realized and unrealized P&L, high/low watermarks, stop loss, target, and trailing stop. The exit sweep is exit-only: it cannot create entries. Portfolio APIs expose cash, equity, exposure by symbol/strategy, P&L, snapshots, drawdown, and equity history.

The paper journal supports notes, mistake tags, rule-following state, filters, and CSV export. Analytics include after-cost P&L, returns, win rate, profit factor, expectancy, payoff, drawdown, holding time, cost drag, grouped results, mistake frequency, and warnings. Strategy reviews recommend `needs_more_data`, `rejected`, or `candidate_for_tiny_live`; recommendations never enable live trading and a persisted status change remains approval-protected.

The local assistant can summarize paper state and prepare paper-order, exit, journal, risk-setting, or strategy-review drafts. It cannot approve its own action, place or close a paper position directly, reset the account directly, call a live broker, or enable live trading.

Run Stage 5 with the project interpreter:

```powershell
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" -m pytest tests/test_stage5_paper_trading.py -q
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" -m pytest -q
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" main.py
```

Paper results are simulations, not forecasts or profit guarantees. Fill quality, liquidity, exchange behavior, corporate actions, connectivity, and broker reconciliation differ materially in live markets. Live trading remains disabled.

Verified Stage 5 result: 40 dedicated paper-operations tests and 179 combined Stage 1â€“5 tests pass with the exact project interpreter.

## Stage 6 strategy validation and walk-forward research lab

Stage 6 asks whether a rule-based strategy remains stable after honest validationâ€”not which historical curve looks best. It persists immutable research experiments and delegates every simulated trade to the existing Stage 2 completed-trade `BacktestService`; it does not contain a second backtester, predictive ML model, or live-order path.

Each experiment saves the strategy/combo, universe, symbols, dates, execution/cost assumptions, sizing, risk settings, parameter grid, validation configuration, and status. A reproducibility manifest records symbol/date coverage, row counts, missing/stale/skipped symbols, data/config hashes, code version, and warnings for survivorship, corporate actions, and unavailable historical index membership.

Supported train/test modes are fixed-date, percentage, rolling-time, and final holdout. In-sample, unseen out-of-sample, and full-period metrics are reported separately. Anchored and rolling/expanding walk-forward folds enforce `train_end < test_start`; failed folds are persisted rather than silently dropped.

Parameter sweeps rank explicit grids and penalize isolated optima. Robustness scenarios stress slippage, spread, fees, entry delay, fill quality, liquidity, skipped trades, universe size, regimes, and drawdown periods through Stage 2. Symbol analysis exposes coverage and contributor concentration. Regime analysis never invents benchmark evidence: when audited benchmark history is unavailable it returns an explicit unavailable warning.

Correlation/redundancy analysis measures deterministic signal/equity correlation and overlap. False-discovery warnings account for the large strategy catalog, adaptive selection, low trade counts, unreliable/unavailable p-values, and missing OOS confirmation. The conservative evidence score combines OOS performance, walk-forward and parameter stability, cost robustness, drawdown, trade count, coverage, regime availability, multiple-testing risk, and optional paper alignment.

Recommendations are limited to `reject`, `needs_more_data`, `continue_research`, `paper_test_candidate`, or the research-only label `tiny_live_candidate_later`. They cannot enable live trading. The user must explicitly approve a persisted research label; the assistant can explain evidence and draft an experiment or recommendation but cannot alter results or approve itself.

Run Stage 6 with the exact project interpreter:

```powershell
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" -m pytest tests/test_stage6_research_lab.py -q
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" -m pytest -q
& "C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe" main.py
```

Validation results remain conditional on data quality and simulation assumptions. They do not prove profitability or authorize live trading.

## Stage 1â€“6 capability and operating guide

- **Foundation:** SQLite migrations and durable paper state initialize automatically. The default mode is PAPER and live trading remains disabled.
- **Backtesting Lab:** choose a strategy, symbols, dates, execution timing, costs, sizing, and risk assumptions; run the completed-trade Stage 2 engine and inspect trades, equity, drawdown, benchmark, and exports.
- **Strategy Library:** browse all supported and unsupported definitions. `needs_data`, `needs_intraday_data`, and `simulation_only` entries remain visible but cannot emit fake active signals.
- **Combo Builder:** compose validated base strategies and primitives, then route combo backtests through the same Stage 2 engine.
- **Assistant, RAG, and Search:** reindex local documentation and platform records, search deterministically, or use LM Studio when available. Mutating assistant tools create persisted drafts that require explicit user approval.
- **Paper Trading Terminal:** review and approve paper-only orders, positions, exits, portfolio accounting, journal entries, snapshots, analytics, and reports. Exit sweeps never create entries.
- **Research Lab:** save reproducible experiments, run train/test and walk-forward validation, inspect parameter stability and applied robustness scenarios, and draft approval-gated research decisions.

Acceptance result on 2026-06-24: 222 tests passed with Python 3.10.11 from the exact project venv. Flask served the dashboard and all Stage 1â€“6 API/static-asset smoke checks passed. Pixel-level browser interaction and browser-console inspection still require a manual check because the in-app browser could not attach during the audit.


## Stage 1–6 Browser UI Acceptance Gate

**Batch date/time:** 2026-06-29 16:15:23 +05:30

**Exact interpreter:** `C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe`

**Python version:** 3.10.11

**Verification results**

- Full pytest: `222 passed`
- App startup: `main.py` printed the Flask serving banner, but the localhost browser-console walk was not fully verifiable in this environment
- Browser UI pages checked by static template scan: Main Dashboard, Backtesting Lab, Strategy Library, Combo Builder, Assistant, App Search, Profile, Custom Dashboard, Paper Trading Terminal, Portfolio, Trade Journal, Paper Analytics, Research Lab, Walk-Forward, Robustness Lab, Validation Report
- Browser console: not available in this batch because the in-app browser could not attach
- Static/fallback checks: required panes and paper/research markers are present in `templates/index.html`; no repository-side Stage 1–6 UI bug was identified
- Remaining issues: interactive browser navigation and console inspection still need a successful manual pass before Stage 7 can start

Stage 7 should not begin yet. Browser UI gate is incomplete.
This software provides historical simulation and paper-trading research only. It offers no profit guarantee, and no Stage 1â€“6 result authorizes live trading.
