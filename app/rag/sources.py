from __future__ import annotations

import json
from pathlib import Path


def markdown_sources(project_root: str | Path) -> list[dict]:
    root = Path(project_root); paths = [root / "README.md", root / "TECHNICAL_REPORT.md", root / "CHANGELOG.md"]
    paths.extend(sorted((root / "docs").glob("*.md")) if (root / "docs").exists() else [])
    return [{"source_type": "docs", "source_id": path.relative_to(root).as_posix(), "title": path.stem.replace("_", " "),
             "content": path.read_text(encoding="utf-8"), "metadata": {"path": str(path)}} for path in paths if path.exists()]


TABLE_SOURCES = {
    "strategy_definitions": ("strategy", "strategy_id", "name", ("description", "learning_note", "config_json")),
    "combo_strategy_definitions": ("combo", "combo_id", "name", ("description", "components_json", "logic_json")),
    "backtest_runs": ("backtest", "run_id", "strategy_name", ("config_json", "notes")),
    "backtest_trades": ("backtest_trade", "id", "symbol", ("entry_reason", "exit_reason")),
    "backtest_metric_breakdown": ("backtest_metric", "id", "metric_name", ("metric_value", "metric_status", "explanation")),
    "paper_account": ("paper_account", "id", "id", ("cash", "total_equity", "realized_pnl", "unrealized_pnl")),
    "paper_orders": ("paper_order", "id", "symbol", ("side", "status", "rejection_reason")),
    "paper_positions": ("paper_position", "id", "symbol", ("status",)),
    "paper_trades": ("paper_trade", "id", "symbol", ("strategy_id", "exit_reason")),
    "risk_events": ("risk_event", "id", "event_type", ("reason", "context_json")),
    "system_logs": ("system_log", "id", "event_type", ("message", "context_json")),
    "assistant_conversations": ("conversation", "id", "title", ()),
    "dashboard_layouts": ("dashboard", "layout_id", "name", ("description", "layout_json")),
    "dashboard_widgets": ("dashboard_widget", "id", "title", ("widget_type", "config_json")),
    "trading_profile": ("profile", "id", "profile_name", ("config_json",)),
    "watchlists": ("watchlist", "id", "name", ("symbols_json",)),
    "saved_screeners": ("screener", "id", "name", ("config_json",)),
    "trade_history_annotations": ("trade_journal", "trade_id", "trade_id", ("notes", "tags_json")),
    "paper_fills": ("paper_fill", "id", "symbol", ("side", "fill_price", "fees", "fill_reason")),
    "paper_trade_journal": ("paper_journal", "id", "symbol", ("strategy_id", "net_pnl", "exit_reason", "mistake_tags_json", "notes")),
    "paper_account_snapshots": ("paper_snapshot", "id", "snapshot_time", ("total_equity", "daily_pnl", "drawdown_pct")),
    "paper_strategy_reviews": ("paper_review", "id", "strategy_id", ("promotion_status", "warnings_json")),
}


def database_sources(database) -> list[dict]:
    available = {row["name"] for row in database.query("SELECT name FROM sqlite_master WHERE type='table'")}
    documents = []
    for table, (source_type, id_col, title_col, content_cols) in TABLE_SOURCES.items():
        if table not in available: continue
        for row in database.query(f"SELECT * FROM {table}"):
            content = "\n".join(f"{key}: {row.get(key)}" for key in content_cols if row.get(key) not in (None, ""))
            metadata = {key: value for key, value in row.items() if key not in content_cols and isinstance(value, (str, int, float, type(None)))}
            documents.append({"source_type": source_type, "source_id": str(row[id_col]), "title": str(row.get(title_col) or row[id_col]),
                              "content": content or json.dumps(metadata, default=str), "metadata": metadata})
    return documents
