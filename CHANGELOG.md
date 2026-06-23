# Changelog

## Unreleased — Stage 1–3 verification

### Stage 1 stabilization

- Added additive SQLite migrations, durable paper account state, broker separation, risk scaffolding, consistent API helpers, structured logs, and corrected reset/exit-sweep/ATR behavior.
- Kept live execution disabled by default and removed paper fallback after live-order failure.

### Stage 2 backtesting

- Added the completed-trade, cash-backed Stage 2 engine with explicit execution timing, sizing, exits, costs, slippage, equity curve, benchmark comparison, persistence, exports, APIs, and Backtesting Lab.
- Retained the legacy signal-day report only as a clearly separate compatibility diagnostic.

### Stage 3 strategy factory

- Added 233 config-driven base definitions and 120 combo definitions with visible unsupported states.
- Added strategy/combo registries, primitive and combination engines, validation, explanations, persistence, Stage 2 routing, APIs, Strategy Library, and Combo Builder.

### Verification fixes

- Added the missing named momentum, volume, price-action, and pullback primitives.
- Added stable catalog loader functions used by acceptance count commands.
- Expanded explanations with symbol, signal time, passed filters, risk/exit context, and freshness warnings.
- Added primitive parameter/future-use checks and application-level duplicate combo-ID rejection.
- Expanded Stage 3 coverage from 36 to 50 named pytest functions and added dedicated Combo Builder styling.

### Remaining known issues

- Runtime tests, migrations, catalog imports, Flask startup, APIs, and browser UI smoke tests remain unverified because no Python runtime is installed in the verification environment.
- Intraday, fundamentals, sector/index context, pairs, and options-chain strategies remain visibly unsupported until their required datasets exist.
- Live trading remains disabled and is outside Stage 1–3 acceptance.
- Backtest results are historical simulations and do not guarantee profit.
