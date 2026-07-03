from __future__ import annotations

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS paper_account (
        id INTEGER PRIMARY KEY CHECK (id = 1), cash REAL NOT NULL, starting_capital REAL NOT NULL,
        realized_pnl REAL NOT NULL DEFAULT 0, unrealized_pnl REAL NOT NULL DEFAULT 0,
        total_equity REAL NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS paper_positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL UNIQUE, quantity INTEGER NOT NULL,
        avg_price REAL NOT NULL, last_price REAL NOT NULL, highest_price REAL NOT NULL,
        unrealized_pnl REAL NOT NULL DEFAULT 0, opened_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN'
    );
    CREATE TABLE IF NOT EXISTS paper_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, client_order_id TEXT NOT NULL UNIQUE,
        broker_order_id TEXT, mode TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
        quantity INTEGER NOT NULL, order_type TEXT NOT NULL, requested_price REAL, fill_price REAL,
        status TEXT NOT NULL, rejection_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, side TEXT NOT NULL,
        quantity INTEGER NOT NULL, entry_price REAL NOT NULL, exit_price REAL NOT NULL,
        gross_pnl REAL NOT NULL, costs REAL NOT NULL DEFAULT 0, net_pnl REAL NOT NULL,
        entry_time TEXT, exit_time TEXT NOT NULL, exit_reason TEXT, strategy_id TEXT
    );
    CREATE TABLE IF NOT EXISTS strategy_registry (
        strategy_id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, category TEXT NOT NULL,
        direction TEXT NOT NULL, timeframe TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL, description TEXT NOT NULL, config_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS custom_strategies (
        id INTEGER PRIMARY KEY AUTOINCREMENT, strategy_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL UNIQUE,
        expression TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
        validation_status TEXT NOT NULL, validation_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT NOT NULL, source TEXT NOT NULL,
        event_type TEXT NOT NULL, message TEXT NOT NULL, context_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS risk_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, severity TEXT NOT NULL, event_type TEXT NOT NULL,
        symbol TEXT, strategy_id TEXT, reason TEXT NOT NULL, context_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS pipeline_manifests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_type TEXT NOT NULL, source_data_path TEXT,
        ticker_count INTEGER NOT NULL DEFAULT 0, earliest_date TEXT, latest_date TEXT,
        skipped_tickers_json TEXT NOT NULL DEFAULT '[]', report_generated_at TEXT, code_version TEXT,
        status TEXT NOT NULL, notes TEXT, created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_orders_created ON paper_orders(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_logs_created ON system_logs(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_risk_created ON risk_events(created_at DESC);
    """),
    (2, """
    CREATE TABLE IF NOT EXISTS backtest_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE, strategy_id TEXT NOT NULL,
        strategy_name TEXT NOT NULL, universe_name TEXT NOT NULL, symbols_json TEXT NOT NULL,
        timeframe TEXT NOT NULL, start_date TEXT, end_date TEXT, initial_capital REAL NOT NULL,
        execution_price_model TEXT NOT NULL, direction_mode TEXT NOT NULL, max_positions INTEGER NOT NULL,
        position_sizing_method TEXT NOT NULL, risk_per_trade_pct REAL NOT NULL, cost_model_name TEXT NOT NULL,
        slippage_bps REAL NOT NULL, benchmark_symbol TEXT, status TEXT NOT NULL, total_trades INTEGER DEFAULT 0,
        winning_trades INTEGER DEFAULT 0, losing_trades INTEGER DEFAULT 0, net_profit REAL DEFAULT 0,
        net_return_pct REAL DEFAULT 0, cagr REAL DEFAULT 0, sharpe REAL DEFAULT 0, sortino REAL DEFAULT 0,
        calmar REAL DEFAULT 0, max_drawdown_pct REAL DEFAULT 0, profit_factor REAL DEFAULT 0,
        expectancy REAL DEFAULT 0, avg_win REAL DEFAULT 0, avg_loss REAL DEFAULT 0, win_rate REAL DEFAULT 0,
        exposure_pct REAL DEFAULT 0, turnover REAL DEFAULT 0, created_at TEXT NOT NULL, completed_at TEXT,
        config_json TEXT NOT NULL, notes TEXT
    );
    CREATE TABLE IF NOT EXISTS backtest_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, strategy_id TEXT NOT NULL,
        symbol TEXT NOT NULL, direction TEXT NOT NULL, quantity INTEGER NOT NULL, entry_signal_time TEXT,
        entry_time TEXT NOT NULL, entry_price REAL NOT NULL, entry_reason TEXT, stop_loss REAL,
        target REAL, trailing_stop REAL, exit_signal_time TEXT, exit_time TEXT NOT NULL,
        exit_price REAL NOT NULL, exit_reason TEXT NOT NULL, gross_pnl REAL NOT NULL, costs REAL NOT NULL,
        net_pnl REAL NOT NULL, return_pct REAL NOT NULL, holding_period_bars INTEGER NOT NULL,
        mae REAL DEFAULT 0, mfe REAL DEFAULT 0, brokerage REAL NOT NULL DEFAULT 0,
        taxes_and_charges REAL NOT NULL DEFAULT 0, slippage_cost REAL NOT NULL DEFAULT 0,
        spread_cost REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS backtest_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, trade_id INTEGER, symbol TEXT NOT NULL,
        side TEXT NOT NULL, order_type TEXT NOT NULL, requested_time TEXT NOT NULL, requested_price REAL,
        fill_time TEXT, fill_price REAL, quantity INTEGER NOT NULL, status TEXT NOT NULL,
        rejection_reason TEXT, slippage REAL DEFAULT 0, costs REAL DEFAULT 0, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS backtest_equity_curve (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, timestamp TEXT NOT NULL,
        cash REAL NOT NULL, position_value REAL NOT NULL, total_equity REAL NOT NULL,
        drawdown_pct REAL NOT NULL, benchmark_value REAL, benchmark_drawdown_pct REAL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS backtest_daily_summary (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, date TEXT NOT NULL,
        starting_equity REAL NOT NULL, ending_equity REAL NOT NULL, realized_pnl REAL NOT NULL,
        unrealized_pnl REAL NOT NULL, gross_exposure REAL NOT NULL, net_exposure REAL NOT NULL,
        trades_opened INTEGER NOT NULL, trades_closed INTEGER NOT NULL, costs REAL NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS backtest_metric_breakdown (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, metric_name TEXT NOT NULL,
        metric_value REAL, metric_status TEXT NOT NULL, explanation TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_backtest_runs_created ON backtest_runs(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_backtest_trades_run ON backtest_trades(run_id, entry_time);
    CREATE INDEX IF NOT EXISTS idx_backtest_orders_run ON backtest_orders(run_id, requested_time);
    CREATE INDEX IF NOT EXISTS idx_backtest_equity_run ON backtest_equity_curve(run_id, timestamp);
    """),
    (3, """
    CREATE TABLE IF NOT EXISTS strategy_definitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, strategy_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
        category TEXT NOT NULL, subcategory TEXT NOT NULL, direction TEXT NOT NULL, timeframe TEXT NOT NULL,
        asset_class TEXT NOT NULL, status TEXT NOT NULL, description TEXT NOT NULL, learning_note TEXT NOT NULL,
        config_json TEXT NOT NULL, parameters_json TEXT NOT NULL, required_columns_json TEXT NOT NULL,
        tags_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS strategy_validation_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, strategy_id TEXT NOT NULL, valid INTEGER NOT NULL,
        status TEXT NOT NULL, warnings_json TEXT NOT NULL, errors_json TEXT NOT NULL, checked_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS combo_strategy_definitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, combo_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
        category TEXT NOT NULL, description TEXT NOT NULL, logic_json TEXT NOT NULL,
        components_json TEXT NOT NULL, entry_json TEXT NOT NULL, exit_json TEXT NOT NULL,
        risk_json TEXT NOT NULL, status TEXT NOT NULL, tags_json TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS strategy_signal_explanations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, strategy_id TEXT NOT NULL, symbol TEXT NOT NULL,
        signal_time TEXT NOT NULL, signal_value INTEGER NOT NULL, explanation TEXT NOT NULL,
        context_json TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS strategy_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL UNIQUE, description TEXT NOT NULL,
        count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_strategy_definitions_category ON strategy_definitions(category,status,enabled);
    CREATE INDEX IF NOT EXISTS idx_strategy_validation_id ON strategy_validation_results(strategy_id,checked_at DESC);
    CREATE INDEX IF NOT EXISTS idx_combo_category ON combo_strategy_definitions(category,status,enabled);
    """),
    (4, """
    CREATE TABLE IF NOT EXISTS assistant_conversations (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS assistant_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, role TEXT NOT NULL,
        content TEXT NOT NULL, tool_calls_json TEXT NOT NULL DEFAULT '[]',
        retrieved_context_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
        FOREIGN KEY(conversation_id) REFERENCES assistant_conversations(id)
    );
    CREATE TABLE IF NOT EXISTS assistant_action_drafts (
        id TEXT PRIMARY KEY, conversation_id TEXT, action_type TEXT NOT NULL, status TEXT NOT NULL,
        draft_json TEXT NOT NULL, validation_json TEXT NOT NULL, risk_check_json TEXT NOT NULL,
        approval_required INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
        approved_at TEXT, rejected_at TEXT, executed_at TEXT,
        FOREIGN KEY(conversation_id) REFERENCES assistant_conversations(id)
    );
    CREATE TABLE IF NOT EXISTS rag_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
        title TEXT NOT NULL, content TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
        content_hash TEXT NOT NULL, indexed_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(source_type, source_id)
    );
    CREATE TABLE IF NOT EXISTS rag_chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL, chunk_index INTEGER NOT NULL,
        content TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', indexed_at TEXT NOT NULL,
        FOREIGN KEY(document_id) REFERENCES rag_documents(id) ON DELETE CASCADE,
        UNIQUE(document_id, chunk_index)
    );
    CREATE TABLE IF NOT EXISTS app_search_index (
        id INTEGER PRIMARY KEY AUTOINCREMENT, result_type TEXT NOT NULL, source_id TEXT NOT NULL,
        title TEXT NOT NULL, summary TEXT NOT NULL, keywords TEXT NOT NULL DEFAULT '',
        metadata_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL,
        UNIQUE(result_type, source_id)
    );
    CREATE TABLE IF NOT EXISTS trading_profile (
        id INTEGER PRIMARY KEY CHECK(id=1), profile_name TEXT NOT NULL, config_json TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS dashboard_layouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, layout_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '', layout_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS dashboard_widgets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, layout_id TEXT NOT NULL, widget_id TEXT NOT NULL,
        widget_type TEXT NOT NULL, title TEXT NOT NULL, config_json TEXT NOT NULL DEFAULT '{}',
        position_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        FOREIGN KEY(layout_id) REFERENCES dashboard_layouts(layout_id) ON DELETE CASCADE,
        UNIQUE(layout_id, widget_id)
    );
    CREATE INDEX IF NOT EXISTS idx_assistant_messages_conversation ON assistant_messages(conversation_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_action_drafts_status ON assistant_action_drafts(status, created_at);
    CREATE INDEX IF NOT EXISTS idx_rag_documents_source ON rag_documents(source_type, source_id);
    CREATE INDEX IF NOT EXISTS idx_search_type ON app_search_index(result_type, updated_at);
    CREATE INDEX IF NOT EXISTS idx_dashboard_widgets_layout ON dashboard_widgets(layout_id);
    """),
    (5, """
    CREATE TABLE IF NOT EXISTS trade_history_annotations (
        trade_id TEXT PRIMARY KEY, notes TEXT NOT NULL DEFAULT '', tags_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    """),
    (6, """
    CREATE TABLE IF NOT EXISTS watchlists (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, symbols_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS saved_screeners (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, config_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_watchlists_updated ON watchlists(updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_saved_screeners_updated ON saved_screeners(updated_at DESC);
    """),
    (7, """
    CREATE TABLE IF NOT EXISTS paper_accounts (
        id TEXT PRIMARY KEY, account_name TEXT NOT NULL, starting_capital REAL NOT NULL,
        cash REAL NOT NULL, blocked_cash REAL NOT NULL DEFAULT 0, realized_pnl REAL NOT NULL DEFAULT 0,
        unrealized_pnl REAL NOT NULL DEFAULT 0, total_equity REAL NOT NULL, buying_power REAL NOT NULL,
        gross_exposure REAL NOT NULL DEFAULT 0, net_exposure REAL NOT NULL DEFAULT 0,
        open_positions_count INTEGER NOT NULL DEFAULT 0, daily_pnl REAL NOT NULL DEFAULT 0,
        weekly_pnl REAL NOT NULL DEFAULT 0, monthly_pnl REAL NOT NULL DEFAULT 0,
        max_drawdown REAL NOT NULL DEFAULT 0, peak_equity REAL NOT NULL, status TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    ALTER TABLE paper_orders ADD COLUMN account_id TEXT NOT NULL DEFAULT 'default';
    ALTER TABLE paper_orders ADD COLUMN strategy_id TEXT;
    ALTER TABLE paper_orders ADD COLUMN combo_id TEXT;
    ALTER TABLE paper_orders ADD COLUMN assistant_action_id TEXT;
    ALTER TABLE paper_orders ADD COLUMN source TEXT NOT NULL DEFAULT 'manual';
    ALTER TABLE paper_orders ADD COLUMN product_type TEXT NOT NULL DEFAULT 'delivery';
    ALTER TABLE paper_orders ADD COLUMN limit_price REAL;
    ALTER TABLE paper_orders ADD COLUMN stop_price REAL;
    ALTER TABLE paper_orders ADD COLUMN estimated_value REAL NOT NULL DEFAULT 0;
    ALTER TABLE paper_orders ADD COLUMN estimated_costs REAL NOT NULL DEFAULT 0;
    ALTER TABLE paper_orders ADD COLUMN approval_required INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE paper_orders ADD COLUMN approved_by_user INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE paper_orders ADD COLUMN approved_at TEXT;
    ALTER TABLE paper_orders ADD COLUMN submitted_at TEXT;
    ALTER TABLE paper_orders ADD COLUMN filled_at TEXT;
    ALTER TABLE paper_orders ADD COLUMN cancelled_at TEXT;
    ALTER TABLE paper_orders ADD COLUMN expires_at TEXT;
    ALTER TABLE paper_orders ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';
    ALTER TABLE paper_positions ADD COLUMN account_id TEXT NOT NULL DEFAULT 'default';
    ALTER TABLE paper_positions ADD COLUMN strategy_id TEXT;
    ALTER TABLE paper_positions ADD COLUMN combo_id TEXT;
    ALTER TABLE paper_positions ADD COLUMN current_price REAL;
    ALTER TABLE paper_positions ADD COLUMN market_value REAL NOT NULL DEFAULT 0;
    ALTER TABLE paper_positions ADD COLUMN cost_basis REAL NOT NULL DEFAULT 0;
    ALTER TABLE paper_positions ADD COLUMN unrealized_pnl_pct REAL NOT NULL DEFAULT 0;
    ALTER TABLE paper_positions ADD COLUMN realized_pnl REAL NOT NULL DEFAULT 0;
    ALTER TABLE paper_positions ADD COLUMN lowest_price REAL;
    ALTER TABLE paper_positions ADD COLUMN stop_loss REAL;
    ALTER TABLE paper_positions ADD COLUMN target REAL;
    ALTER TABLE paper_positions ADD COLUMN trailing_stop REAL;
    ALTER TABLE paper_positions ADD COLUMN entry_reason TEXT;
    ALTER TABLE paper_positions ADD COLUMN risk_amount REAL NOT NULL DEFAULT 0;
    ALTER TABLE paper_positions ADD COLUMN source TEXT NOT NULL DEFAULT 'manual';
    ALTER TABLE paper_positions ADD COLUMN closed_at TEXT;
    ALTER TABLE paper_positions ADD COLUMN entry_order_id INTEGER;
    CREATE TABLE IF NOT EXISTS paper_fills (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, symbol TEXT NOT NULL,
        side TEXT NOT NULL, quantity INTEGER NOT NULL, requested_price REAL, fill_price REAL NOT NULL,
        slippage REAL NOT NULL DEFAULT 0, spread_cost REAL NOT NULL DEFAULT 0, fees REAL NOT NULL DEFAULT 0,
        total_cost REAL NOT NULL DEFAULT 0, fill_time TEXT NOT NULL, fill_reason TEXT NOT NULL,
        created_at TEXT NOT NULL, FOREIGN KEY(order_id) REFERENCES paper_orders(id)
    );
    CREATE TABLE IF NOT EXISTS paper_order_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, from_status TEXT,
        to_status TEXT NOT NULL, reason TEXT, context_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS paper_trade_journal (
        id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL, symbol TEXT NOT NULL,
        strategy_id TEXT, combo_id TEXT, source TEXT NOT NULL, entry_order_id INTEGER,
        exit_order_id INTEGER, entry_time TEXT, exit_time TEXT, entry_price REAL NOT NULL,
        exit_price REAL NOT NULL, quantity INTEGER NOT NULL, gross_pnl REAL NOT NULL,
        costs REAL NOT NULL DEFAULT 0, net_pnl REAL NOT NULL, return_pct REAL NOT NULL,
        holding_period REAL NOT NULL DEFAULT 0, entry_reason TEXT, exit_reason TEXT,
        setup_type TEXT, mistake_tags_json TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '',
        screenshot_path TEXT, confidence TEXT, rule_followed TEXT NOT NULL DEFAULT 'unknown',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS paper_account_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL, snapshot_time TEXT NOT NULL,
        cash REAL NOT NULL, position_value REAL NOT NULL, total_equity REAL NOT NULL,
        realized_pnl REAL NOT NULL, unrealized_pnl REAL NOT NULL, daily_pnl REAL NOT NULL,
        daily_return_pct REAL NOT NULL, drawdown_pct REAL NOT NULL, open_positions INTEGER NOT NULL,
        orders_count INTEGER NOT NULL, trades_count INTEGER NOT NULL, costs REAL NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS paper_strategy_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT, strategy_id TEXT NOT NULL, account_id TEXT NOT NULL,
        status TEXT NOT NULL, trades_count INTEGER NOT NULL, days_tested INTEGER NOT NULL,
        net_pnl REAL NOT NULL, expectancy REAL NOT NULL, profit_factor REAL NOT NULL,
        max_drawdown REAL NOT NULL, cost_drag REAL NOT NULL, rule_following_rate REAL NOT NULL,
        promotion_status TEXT NOT NULL, warnings_json TEXT NOT NULL DEFAULT '[]',
        reviewed_at TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS paper_reset_archives (
        id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL, snapshot_json TEXT NOT NULL,
        archived_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS paper_risk_settings (
        account_id TEXT PRIMARY KEY, config_json TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_paper_fills_order ON paper_fills(order_id);
    CREATE INDEX IF NOT EXISTS idx_paper_journal_strategy ON paper_trade_journal(strategy_id,exit_time);
    CREATE INDEX IF NOT EXISTS idx_paper_snapshots_time ON paper_account_snapshots(account_id,snapshot_time);
    CREATE INDEX IF NOT EXISTS idx_paper_order_events_order ON paper_order_events(order_id,created_at);
    """),
    (8, """
    CREATE TABLE IF NOT EXISTS research_experiments (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        strategy_id TEXT, combo_id TEXT, universe TEXT NOT NULL, symbols_json TEXT NOT NULL,
        start_date TEXT, end_date TEXT, train_start TEXT, train_end TEXT, test_start TEXT, test_end TEXT,
        execution_model TEXT NOT NULL, cost_model TEXT NOT NULL, slippage_bps REAL NOT NULL,
        spread_bps REAL NOT NULL, fees_enabled INTEGER NOT NULL, initial_capital REAL NOT NULL,
        max_positions INTEGER NOT NULL, sizing_model TEXT NOT NULL, risk_settings_json TEXT NOT NULL,
        parameter_grid_json TEXT NOT NULL, validation_config_json TEXT NOT NULL, status TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS research_data_manifests (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, data_source TEXT NOT NULL,
        symbols_json TEXT NOT NULL, symbol_count INTEGER NOT NULL, date_start TEXT, date_end TEXT,
        rows_per_symbol_json TEXT NOT NULL, missing_dates_json TEXT NOT NULL,
        skipped_symbols_json TEXT NOT NULL, stale_symbols_json TEXT NOT NULL, data_hash TEXT NOT NULL,
        code_version TEXT NOT NULL, config_hash TEXT NOT NULL, warnings_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL, FOREIGN KEY(experiment_id) REFERENCES research_experiments(id)
    );
    CREATE TABLE IF NOT EXISTS walk_forward_folds (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, fold_number INTEGER NOT NULL,
        train_start TEXT NOT NULL, train_end TEXT NOT NULL, test_start TEXT NOT NULL, test_end TEXT NOT NULL,
        selected_parameters_json TEXT NOT NULL, train_metrics_json TEXT NOT NULL, test_metrics_json TEXT NOT NULL,
        trades_count INTEGER NOT NULL, test_return_pct REAL NOT NULL, test_sharpe REAL NOT NULL,
        test_sortino REAL NOT NULL, test_max_drawdown REAL NOT NULL, test_profit_factor REAL NOT NULL,
        test_expectancy REAL NOT NULL, test_win_rate REAL NOT NULL, test_costs REAL NOT NULL,
        status TEXT NOT NULL, warnings_json TEXT NOT NULL, created_at TEXT NOT NULL,
        FOREIGN KEY(experiment_id) REFERENCES research_experiments(id), UNIQUE(experiment_id,fold_number)
    );
    CREATE TABLE IF NOT EXISTS parameter_sweep_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id TEXT NOT NULL, parameter_set_id TEXT NOT NULL,
        parameters_json TEXT NOT NULL, full_metrics_json TEXT NOT NULL, train_metrics_json TEXT NOT NULL,
        test_metrics_json TEXT NOT NULL, walk_forward_metrics_json TEXT NOT NULL, rank INTEGER NOT NULL,
        stability_score REAL NOT NULL, overfit_warning TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS robustness_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id TEXT NOT NULL, scenario_name TEXT NOT NULL,
        config_json TEXT NOT NULL, metrics_json TEXT NOT NULL, return_pct REAL NOT NULL,
        max_drawdown REAL NOT NULL, profit_factor REAL NOT NULL, expectancy REAL NOT NULL,
        trades_count INTEGER NOT NULL, pass_fail TEXT NOT NULL, warnings_json TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS regime_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id TEXT NOT NULL, regime_name TEXT NOT NULL,
        date_start TEXT, date_end TEXT, trades_count INTEGER NOT NULL, return_pct REAL NOT NULL,
        win_rate REAL NOT NULL, profit_factor REAL NOT NULL, expectancy REAL NOT NULL,
        max_drawdown REAL NOT NULL, warnings_json TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS symbol_analysis_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id TEXT NOT NULL, symbol TEXT NOT NULL,
        trades_count INTEGER NOT NULL, net_pnl REAL NOT NULL, return_pct REAL NOT NULL,
        win_rate REAL NOT NULL, profit_factor REAL NOT NULL, expectancy REAL NOT NULL,
        max_drawdown REAL NOT NULL, contribution_pct REAL NOT NULL, warnings_json TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS strategy_correlation_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, strategy_a TEXT NOT NULL, strategy_b TEXT NOT NULL,
        signal_correlation REAL NOT NULL, equity_correlation REAL NOT NULL, trade_overlap_pct REAL NOT NULL,
        drawdown_overlap_pct REAL NOT NULL, redundancy_score REAL NOT NULL, recommendation TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS research_decisions (
        id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, strategy_id TEXT, combo_id TEXT,
        decision TEXT NOT NULL, evidence_score REAL NOT NULL, decision_reason TEXT NOT NULL,
        warnings_json TEXT NOT NULL, approved_by_user INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending', approved_at TEXT, rejected_at TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS research_validation_summaries (
        experiment_id TEXT PRIMARY KEY, summary_json TEXT NOT NULL, evidence_score REAL NOT NULL,
        recommendation TEXT NOT NULL, warnings_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_research_experiments_created ON research_experiments(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_walk_forward_experiment ON walk_forward_folds(experiment_id,fold_number);
    CREATE INDEX IF NOT EXISTS idx_robustness_experiment ON robustness_results(experiment_id,scenario_name);
    """),

    (9, """
    CREATE TABLE IF NOT EXISTS broker_reconciliations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reconciliation_id TEXT NOT NULL UNIQUE,
        mode TEXT NOT NULL,
        broker TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT NOT NULL,
        status TEXT NOT NULL,
        funds_status TEXT NOT NULL,
        positions_status TEXT NOT NULL,
        orders_status TEXT NOT NULL,
        trades_status TEXT NOT NULL,
        mismatches_json TEXT NOT NULL DEFAULT '[]',
        warnings_json TEXT NOT NULL DEFAULT '[]',
        errors_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS live_readiness_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        check_id TEXT NOT NULL UNIQUE,
        check_name TEXT NOT NULL,
        status TEXT NOT NULL,
        severity TEXT NOT NULL,
        message TEXT NOT NULL,
        details_json TEXT NOT NULL DEFAULT '{}',
        checked_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS live_readiness_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL UNIQUE,
        mode TEXT NOT NULL,
        overall_status TEXT NOT NULL,
        checks_json TEXT NOT NULL DEFAULT '[]',
        critical_failures_json TEXT NOT NULL DEFAULT '[]',
        warnings_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_broker_reconciliations_created ON broker_reconciliations(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_live_readiness_checks_name ON live_readiness_checks(check_name, checked_at DESC);
    CREATE INDEX IF NOT EXISTS idx_live_readiness_runs_created ON live_readiness_runs(created_at DESC);
    """),
]
