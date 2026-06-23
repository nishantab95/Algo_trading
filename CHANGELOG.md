# Changelog

## Unreleased — Stage 4 local assistant and command center

### Environment and verification

- Verified `C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe` as Python 3.10.11.
- Verified the Stage 1–3 baseline: 95 tests passed, 233 base strategies, and 120 combos.
- Added 41 dedicated Stage 4 tests; the full suite reached 136 passing tests.
- Kept dependencies minimal: standard-library HTTP and SQLite; no LangChain, vector database, or ML/DL package.

### Stage 4 implementation

- Added offline-safe LM Studio chat/status integration.
- Added local RAG and app-wide structured search.
- Added controlled read-only, draft, approval-required, and forbidden tool boundaries.
- Added persisted conversations, action drafts, profiles, dashboards/widgets, search records, and trade annotations through migrations 4–5.
- Added approval-protected profile, dashboard, strategy/combo, backtest, paper-order, reset, and trade-note boundaries.
- Added integrated Assistant, Search, Profile, and Custom Dashboard workspaces.
- Made startup maintenance non-blocking, fixed source-aware RAG ranking, and removed pandas resampling warnings.

### Stage 4 limitations

- LM Studio runs separately; deterministic search remains available offline.
- Full visual browser interaction remains a manual acceptance item when browser automation is unavailable.
- Live trading and predictive ML/DL remain outside the assistant.

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
- Expanded Stage 3 coverage from 36 to 51 named pytest functions and added dedicated Combo Builder styling.
- Standardized Stage 1 success/failure envelopes with mandatory warnings/details fields.
- Added behavior tests proving reset and exit-only sweep cannot invoke the scan callback, plus recalibration routing and the complete Stage 2 export bundle.
- Added `not` support consistently across the combo engine, validator, UI, and tests.
- Corrected all-winner profit factor handling: it is now explicitly undefined instead of incorrectly reported as a currency amount.
- Stage 1–3 execution was later verified with the project venv: 95 tests passed before Stage 4.

### Remaining known issues

- Runtime tests, migrations, catalog imports, API composition, and real HTTP startup are verified with the project venv; visual browser interaction remains a manual check.
- Intraday, fundamentals, sector/index context, pairs, and options-chain strategies remain visibly unsupported until their required datasets exist.
- Live trading remains disabled and is outside Stage 1–3 acceptance.
- Backtest results are historical simulations and do not guarantee profit.
