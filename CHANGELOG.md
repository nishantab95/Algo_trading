# Changelog
## Unreleased - Stage 7 Batch 3 Broker Reconciliation and Live Readiness

- Added additive migration 9 for `broker_reconciliations`, `live_readiness_checks`, and `live_readiness_runs`.
- Added persisted broker reconciliation with fail-closed broker-unavailable, stale-state, cash, quantity, missing-broker, unknown, and status-mismatch handling.
- Added safe local live-state placeholders and shadow-live paper state hooks for later batches without creating any live-order path.
- Added `LiveGuard` and persisted readiness checks covering prior-stage markers, broker mode/read-only state, reconciliation, live-disabled default, tiny-live lock, Batch 4 placeholders, assistant restrictions, no live fallback to paper, secret hygiene, and no ML/DL prediction dependency.
- Added reconciliation APIs and readiness APIs with consistent envelopes; no route submits a live order, unlocks tiny-live, or changes broker credentials.
- Added 30 focused Stage 7 Batch 3 tests. Focused result: `30 passed`; final full result: `278 passed` with the exact project interpreter.
- Live orders remain disabled. Tiny-live remains blocked/not ready until Batch 4 implements unlock, strict limits, live risk manager, and kill switch.

## Unreleased - Stage 7 Batch 2 Broker Modes and Broker Factory

- Added explicit broker modes: `live_disabled`, `paper`, `broker_readonly`, `shadow_live`, and `tiny_live`, defaulting to `live_disabled`.
- Added broker-specific safe errors and lightweight sanitized broker models for status, order request shape, quote shape, read-only state, and future reconciliation-ready state.
- Hardened `BaseBroker` with explicit connect, read, order, trade, quote, mutation, and health-check methods that fail closed by default.
- Hardened `MockBroker` with connected/disconnected state, profile/funds/holdings/positions/orders/trades/quotes fixtures, read failure simulation, broker rejection simulation, and mutation-attempt counters.
- Added a safe factory and canonical `app/services/broker_service.py`; `app/brokers/broker_service.py` remains a compatibility import.
- Expanded safe broker APIs for status, mode, profile, funds, holdings, positions, orders, trades, and symbol quote reads. No route places live orders, changes credentials, or unlocks tiny-live.
- Added 26 focused Stage 7 Batch 2 tests. Focused result: `26 passed`; final full result: `248 passed` with the exact project interpreter.
- API smoke passed for the expanded broker endpoints; no UI work was included in this batch.
- Live orders remain disabled. Tiny-live is locked. Assistant actors cannot switch to live-like modes or execute broker actions.

## Unreleased â€” Stage 1â€“6 browser UI acceptance gate

- Recorded the 2026-06-29 browser UI gate batch with the exact project interpreter and pytest baseline.
- Static template inspection confirmed the required Stage 1â€“6 panes and paper/research markers in `templates/index.html`.
- Browser-console inspection was not available because the in-app browser could not attach, so Stage 7 should not begin yet.

## Unreleased Ã¢â‚¬â€ Stage 1Ã¢â‚¬â€œ6 stabilization and acceptance audit

- Backed up the dirty worktree and live SQLite database before stabilization checks; no user changes were discarded.
- Verified the exact project interpreter as Python 3.10.11, installed requirements, and confirmed 233 unique base strategies and 120 unique combos.
- Fixed Stage 6 robustness execution so deterministic skipped-signal and peak-to-trough stress scenarios transform the actual Stage 2 input; unavailable benchmark-regime and expanded-universe evidence is now labeled unavailable and excluded from scoring.
- Fixed Stage 5 paper-buy reservations to include adverse fill movement and fees before approval, preventing near-all-cash orders from failing inside the fill transaction.
- Added the required `details` object to Stage 2 API failure envelopes.
- Added migration idempotency, dashboard/state, same-close research labeling, opposite-signal exit, insufficient-cash, positive benchmark, API failure, cost-inclusive paper approval, and robustness regression tests.
- Final full suite: 222 passed. Focused suites and live localhost UI/API/static-asset checks also passed during the audit.
- Updated README and the technical report with exact commands, acceptance evidence, limitations, and the Stage 7 gate.
- Remaining manual check: pixel-level interaction, navigation clicks, and browser-console inspection because the in-app browser control surface could not attach.

## Unreleased Ã¢â‚¬â€ Stage 6 validation and walk-forward research lab

- Added additive migration 8 for experiments, reproducibility manifests, walk-forward folds, parameter sweeps, robustness/regime/symbol evidence, correlations, summaries, and research decisions.
- Added fixed/percentage/rolling/final train-test splits and anchored/rolling/expanding unseen-period validation over the existing Stage 2 backtester.
- Added parameter stability and isolated-optimum warnings, cost/fill/delay/liquidity/universe robustness scenarios, and failed-fold persistence.
- Added fail-closed regime analysis, symbol coverage/concentration evidence, correlation/redundancy scoring, and false-discovery warnings.
- Added conservative evidence scoring and approval-only reject/continue/paper-test/tiny-live-later research labels; no live enablement exists.
- Added research CSV/Markdown reports, APIs, assistant read/draft boundaries, and the professional Research Lab UI.
- Added 31 focused Stage 6 tests; the complete Stage 1Ã¢â‚¬â€œ6 suite passes 210 tests with synthetic/local data only.
- Documented limitations: unavailable unaudited regime evidence, placeholder trade-drop/stress scenarios, and strategy-definition parameter regeneration boundaries.

## Unreleased Ã¢â‚¬â€ Stage 5 paper trading and portfolio operations

- Added additive migration 7 for future-ready paper accounts, fills, order events, snapshots, journal, strategy reviews, reset archives, risk settings, and Stage 5 order/position fields.
- Added an approval-gated, long-only paper broker simulator with market, limit, stop, and stop-limit lifecycle handling.
- Added slippage, spread, fee, stale-data, liquidity, cash, quantity, exposure, duplicate-position, averaging-down, required-stop, and kill-switch controls with durable risk events.
- Added weighted-average positions, partial/full exits, stop/target/trailing exit sweep, cash/equity accounting, drawdown, and snapshots.
- Added completed-trade journal annotations, CSV reports, after-cost analytics, warnings, and configurable strategy paper reviews.
- Integrated Stage 5 read/draft/approval tools into the Stage 4 assistant without granting direct execution or live access.
- Added the professional Paper Trading & Portfolio Operations terminal and Stage 5 API surface.
- Added 40 focused Stage 5 tests using synthetic prices only; the complete Stage 1Ã¢â‚¬â€œ5 suite now passes 179 tests with no broker, LM Studio, internet, or live-order dependency.
- Updated README and technical documentation. Remaining limitations include full-quantity deterministic fills and simplified period/calendar accounting.

## Unreleased Ã¢â‚¬â€ Stage 4 local assistant and command center

### Environment and verification

- Verified `C:\Users\nisha\AI_ML_PROJECTS\algo_project\algo_env\Scripts\python.exe` as Python 3.10.11.
- Verified the Stage 1Ã¢â‚¬â€œ3 baseline: 95 tests passed, 233 base strategies, and 120 combos.
- Added 44 dedicated Stage 4 tests; the full suite reached 139 passing tests.
- Kept dependencies minimal: standard-library HTTP and SQLite; no LangChain, vector database, or ML/DL package.

### Stage 4 implementation

- Added offline-safe LM Studio chat/status integration.
- Added local RAG and app-wide structured search.
- Added controlled read-only, draft, approval-required, and forbidden tool boundaries.
- Added persisted conversations, action drafts, profiles, dashboards/widgets, search records, and trade annotations through migrations 4Ã¢â‚¬â€œ5.
- Added approval-protected profile, dashboard, strategy/combo, backtest, paper-order, reset, and trade-note boundaries.
- Added watchlist and saved-screener persistence through additive migration 6 and included both in local retrieval.
- Corrected draft-tool action mapping, enforced failed risk checks at approval, and completed deterministic executors for watchlists, screeners, risk settings, and paper-order cancellation.
- Made app-wide search initialize an empty local index deterministically, removing test-order and first-use dependence on a prior manual RAG reindex.
- Added integrated Assistant, Search, Profile, and Custom Dashboard workspaces.
- Made startup maintenance non-blocking, fixed source-aware RAG ranking, and removed pandas resampling warnings.

### Stage 4 limitations

- LM Studio runs separately; deterministic search remains available offline.
- Full visual browser interaction remains a manual acceptance item when browser automation is unavailable.
- Live trading and predictive ML/DL remain outside the assistant.

## Unreleased Ã¢â‚¬â€ Stage 1Ã¢â‚¬â€œ3 verification

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
- Stage 1Ã¢â‚¬â€œ3 execution was later verified with the project venv: 95 tests passed before Stage 4.

### Remaining known issues

- Runtime tests, migrations, catalog imports, API composition, and real HTTP startup are verified with the project venv; visual browser interaction remains a manual check.
- Intraday, fundamentals, sector/index context, pairs, and options-chain strategies remain visibly unsupported until their required datasets exist.
- Live trading remains disabled and is outside Stage 1Ã¢â‚¬â€œ3 acceptance.
- Backtest results are historical simulations and do not guarantee profit.
