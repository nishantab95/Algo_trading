"""
Central execution controller and interactive Flask trading terminal.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from datetime import datetime

import pandas as pd

import config_settings as cfg

PROJECT_ROOT = cfg.PROJECT_ROOT
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import bot
import data
import preprocessing
import report
import strategy as strategy_selector

from app import bootstrap_application
from app.core.config import SETTINGS
from app.core.logging_config import log_event
from app.routes.broker_routes import create_broker_blueprint
from app.routes.backtest_routes import create_backtest_blueprint
from app.routes.strategy_library_routes import create_strategy_library_blueprint
from app.routes.combo_strategy_routes import create_combo_strategy_blueprint
from app.routes.assistant_routes import create_assistant_blueprint
from app.routes.rag_routes import create_rag_blueprint
from app.routes.profile_routes import create_profile_blueprint
from app.routes.dashboard_builder_routes import create_dashboard_builder_blueprint
from app.routes.app_search_routes import create_app_search_blueprint
from app.routes.dashboard_routes import create_dashboard_blueprint
from app.routes.data_routes import create_data_blueprint
from app.routes.paper_routes import create_paper_blueprint
from app.routes.strategy_routes import create_strategy_blueprint
from app.services.data_service import DataService
from app.services.backtest_service import BacktestService
from app.services.strategy_library_service import StrategyLibraryService
from app.services.combo_strategy_service import ComboStrategyService
from app.services.paper_trading_service import PaperTradingService
from app.services.report_service import ReportService
from app.assistant.action_drafts import ActionDraftService
from app.assistant.service import AssistantService
from app.assistant.tool_registry import ToolRegistry
from app.assistant.tool_executor import ToolExecutor
from app.assistant.tools.readonly_tools import ReadOnlyTools
from app.assistant.tools.trade_history_tools import TradeHistoryService
from app.backtesting.models import BacktestConfig
from app.dashboard_builder.dashboard_service import DashboardService
from app.llm.lmstudio_client import LMStudioClient
from app.profile.profile_service import TradingProfileService
from app.rag.indexer import RAGIndexer
from app.rag.retriever import RAGRetriever
from app.search.search_service import AppSearchService

PIPELINE_LOCK = threading.Lock()

STRATEGY_META = {
    "Volatility_Breakout": "Expansion breakout above volatility bands with participation confirmation.",
    "Golden_Cross": "Long-trend regime shift from EMA50 crossing above EMA200.",
    "EMA_Crossover": "Fast EMA crossover signal for short-cycle trend capture.",
    "RSI_Oversold": "Mean-reversion buy signal after RSI recovers from oversold.",
    "RSI_Overbought": "Short signal when RSI rolls down from overheated levels.",
    "MACD_Histogram_Momentum": "Momentum acceleration when MACD histogram flips positive.",
    "Bollinger_Mean_Reversion": "Lower-band re-entry after downside exhaustion.",
    "Volume_Spike": "Unusual volume participation breakout scan.",
    "Trend_Filter": "Always-on trend bias using EMA structure and price regime.",
    "Turtle_Breakout": "Classic 20-day channel breakout continuation rule.",
    "BB_Squeeze_Breakout": "Volatility compression release through upper band.",
    "SuperTrend_Mimic": "ATR-aware trend impulse approximation.",
    "Momentum_20": "Twenty-session relative momentum direction model.",
    "EMA21_Mean_Reversion": "Stretched deviation reversion around the 21 EMA.",
    "Support_Bounce": "Support-zone recovery with strong close location.",
}

APP_STATE = {
    "status": "Ready",
    "last_run": "",
    "winning_strategy": "",
    "selection_score": 0.0,
    "last_error": "",
    "pipeline_busy": False,
    "pipeline_message": "Idle",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_csv_records(path: str, limit: int | None = None) -> list[dict]:
    if not os.path.exists(path):
        return []
    df = pd.read_csv(path)
    df = df.replace({float("inf"): 0, float("-inf"): 0}).fillna(0)
    if limit is not None:
        df = df.head(limit)
    return df.to_dict(orient="records")


def _reports_payload() -> dict:
    global_summary = _read_csv_records(cfg.STRATEGY_REPORT_FILE)
    asset_leaderboard = _read_csv_records(cfg.ASSET_REPORT_FILE, limit=600)
    return {"global_summary": global_summary, "asset_leaderboard": asset_leaderboard}


def _strategy_cards() -> list[dict]:
    enabled = set(cfg.enabled_strategy_columns())
    rows = []
    for strategy_name in cfg.all_strategy_columns():
        rows.append(
            {
                "name": strategy_name,
                "label": strategy_name.replace("_", " "),
                "description": STRATEGY_META.get(strategy_name, cfg.CUSTOM_STRATEGIES.get(strategy_name, "Custom injected model.")),
                "enabled": strategy_name in enabled,
                "custom": strategy_name in cfg.CUSTOM_STRATEGIES,
            }
        )
    return rows


def load_cached_report() -> bool:
    try:
        if not os.path.exists(cfg.STRATEGY_REPORT_FILE):
            return False
        df = pd.read_csv(cfg.STRATEGY_REPORT_FILE)
        if df.empty:
            return False
        ranked = strategy_selector.score_strategies(df)
        APP_STATE["winning_strategy"] = str(ranked.iloc[0]["Strategy"])
        APP_STATE["selection_score"] = round(float(ranked.iloc[0]["Selection_Score"]), 3)
        APP_STATE["status"] = "Ready"
        APP_STATE["last_error"] = ""
        return True
    except Exception as exc:
        APP_STATE["last_error"] = str(exc)
        return False


def _state_payload() -> dict:
    reports = _reports_payload()
    return {
        **APP_STATE,
        "paths": {
            "data_dir": cfg.DATA_DIR,
            "reports_dir": cfg.REPORTS_DIR,
            "consolidated_file": cfg.CONSOLIDATED_FILE,
        },
        "zerodha": {
            "connected": cfg.ZERODHA_CONNECTED,
            "api_key": cfg.API_KEY[:4] + "****" if cfg.API_KEY else "",
            "mode": "LIVE" if cfg.ZERODHA_CONNECTED else "PAPER",
        },
        "account": bot.account_state(),
        "strategies": _strategy_cards(),
        "universe_size": len(cfg.get_full_ticker_universe()),
        "ticker_universe": cfg.get_full_ticker_universe(),
        "custom_strategies": cfg.CUSTOM_STRATEGIES,
        "reports": reports,
    }


def _run_full_recalibration() -> None:
    APP_STATE["pipeline_busy"] = True
    APP_STATE["pipeline_message"] = "Rebuilding features and dual reports"
    try:
        preprocessing.consolidate_universe()
        summary = report.generate_performance_report()
        if summary.empty:
            raise RuntimeError("Report generation returned no rows.")
        ranked = strategy_selector.score_strategies(summary)
        APP_STATE["winning_strategy"] = str(ranked.iloc[0]["Strategy"])
        APP_STATE["selection_score"] = round(float(ranked.iloc[0]["Selection_Score"]), 3)
        APP_STATE["last_run"] = _now()
        APP_STATE["status"] = "Ready"
        APP_STATE["last_error"] = ""
        APP_STATE["pipeline_message"] = "Idle"
    except Exception as exc:
        APP_STATE["status"] = "Error"
        APP_STATE["last_error"] = str(exc)
        APP_STATE["pipeline_message"] = "Failed"
        print(traceback.format_exc())
        raise
    finally:
        APP_STATE["pipeline_busy"] = False


def _create_legacy_flask_app():
    try:
        from flask import Flask, jsonify, render_template, request
    except ImportError:
        print("[ERROR] Flask is not installed. Run: pip install flask")
        sys.exit(1)

    app = Flask(__name__, template_folder=os.path.join(PROJECT_ROOT, "templates"))

    @app.route("/")
    def index():
        return render_template("index.html", initial_state=json.dumps(_state_payload()))

    @app.route("/api/state")
    def api_state():
        load_cached_report()
        return jsonify(_state_payload())

    @app.route("/api/get_reports")
    def api_get_reports():
        return jsonify({"ok": True, "reports": _reports_payload()})

    @app.route("/api/download_ticker", methods=["POST"])
    def api_download_ticker():
        payload = request.get_json(silent=True) or {}
        ticker = str(payload.get("ticker", "")).strip()
        try:
            result = data.download_custom_ticker(ticker)
            with PIPELINE_LOCK:
                _run_full_recalibration()
            return jsonify({"ok": True, "message": f"{ticker.upper()} imported and reports refreshed.", "download": result, "state": _state_payload()})
        except Exception as exc:
            APP_STATE["last_error"] = str(exc)
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/api/add_custom_strategy", methods=["POST"])
    def api_add_custom_strategy():
        payload = request.get_json(silent=True) or {}
        name = str(payload.get("name", "")).strip()
        condition = str(payload.get("condition", "")).strip()
        try:
            result = preprocessing.inject_custom_strategy(name, condition)
            with PIPELINE_LOCK:
                _run_full_recalibration()
            return jsonify({"ok": True, "message": f"Strategy {result['strategy_name']} compiled and injected.", "strategy": result, "state": _state_payload()})
        except Exception as exc:
            APP_STATE["last_error"] = str(exc)
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/api/connect_zerodha", methods=["POST"])
    def api_connect_zerodha():
        payload = request.get_json(silent=True) or {}
        api_key = str(payload.get("api_key", "")).strip()
        api_secret = str(payload.get("api_secret", "")).strip()
        token = str(payload.get("token", "")).strip()
        try:
            session = bot.initialize_kite_session(api_key, api_secret, token)
            return jsonify({"ok": True, "message": "Zerodha session updated.", "session": session, "state": _state_payload()})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/api/toggle_strategy", methods=["POST"])
    def api_toggle_strategy():
        payload = request.get_json(silent=True) or {}
        strategy_name = str(payload.get("strategy", "")).strip()
        enabled = bool(payload.get("enabled", True))
        try:
            cfg.set_strategy_enabled(strategy_name, enabled)
            load_cached_report()
            return jsonify({"ok": True, "message": f"{strategy_name} {'enabled' if enabled else 'disabled'}.", "state": _state_payload()})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/api/place_order", methods=["POST"])
    def api_place_order():
        payload = request.get_json(silent=True) or {}
        try:
            result = bot.execute_order(
                str(payload.get("ticker", "")).strip(),
                str(payload.get("side", "BUY")).strip(),
                int(payload.get("quantity", 1)),
            )
            return jsonify({"ok": True, "message": "Order processed.", "order": result, "state": _state_payload()})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/api/run_scan", methods=["POST"])
    def api_run_scan():
        try:
            winning = APP_STATE["winning_strategy"] or strategy_selector.select_winning_strategy()
            summary = bot.run_daily_pipeline(cfg.get_full_ticker_universe()[:60], winning)
            return jsonify({"ok": True, "message": "Signal scan complete.", "summary": summary, "state": _state_payload()})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
    @app.route("/api/reset_session", methods=["POST"])
    def api_reset_session():
        bot.reset_session()
        return jsonify({"ok": True, "message": "Paper session reset.", "state": _state_payload()})
    return app


# Stage 1 application services are initialized once and backed by SQLite.
_FOUNDATION = bootstrap_application()
_DATABASE = _FOUNDATION["database"]
_STRATEGY_SERVICE = _FOUNDATION["strategies"]
_DATA_SERVICE = DataService()
_REPORT_SERVICE = ReportService(_DATABASE)
_PAPER_SERVICE = PaperTradingService(bot.TRADING_ENGINE._latest_price_from_csv, _DATABASE)
_BACKTEST_SERVICE = BacktestService(_DATABASE)
_STRATEGY_LIBRARY = StrategyLibraryService(_DATABASE, _BACKTEST_SERVICE)
_STRATEGY_LIBRARY.initialize()
_COMBO_SERVICE = ComboStrategyService(_DATABASE, _STRATEGY_LIBRARY, _BACKTEST_SERVICE)
_COMBO_SERVICE.initialize()
_PROFILE_SERVICE = TradingProfileService(_DATABASE)
_DASHBOARD_SERVICE = DashboardService(_DATABASE)
_RAG_INDEXER = RAGIndexer(_DATABASE, PROJECT_ROOT)
_RAG_RETRIEVER = RAGRetriever(_DATABASE)
_APP_SEARCH_SERVICE = AppSearchService(_DATABASE, _RAG_INDEXER)
_TRADE_HISTORY_SERVICE = TradeHistoryService(_DATABASE)
_TOOL_REGISTRY = ToolRegistry()
_READONLY_TOOLS = ReadOnlyTools(_DATABASE, _PROFILE_SERVICE, _DASHBOARD_SERVICE, _APP_SEARCH_SERVICE, _RAG_RETRIEVER,
                                _STRATEGY_LIBRARY, _COMBO_SERVICE, _BACKTEST_SERVICE, _PAPER_SERVICE,
                                _TRADE_HISTORY_SERVICE, lambda: _stage1_state_payload())


def _run_approved_backtest(payload): return _BACKTEST_SERVICE.run(BacktestConfig(**payload)).summary()
def _approved_paper_order(payload):
    if str(payload.get("mode","PAPER")).upper() != "PAPER": raise PermissionError("Assistant orders are paper-only")
    return _PAPER_SERVICE.place_order(str(payload["symbol"]),str(payload.get("side","BUY")),int(payload["quantity"]),strategy_id=payload.get("strategy_id"))
def _apply_strategy_change(payload):
    changes=payload.get("changes",payload)
    if set(changes)-{"enabled","strategy_id"}: raise ValueError("Stage 4 strategy changes are limited to approval-protected enable/disable")
    return _STRATEGY_LIBRARY.toggle(payload["strategy_id"],bool(changes["enabled"]))
def _apply_combo_change(payload):
    return _COMBO_SERVICE.update(payload["combo_id"],payload.get("changes",{}))

def _save_named_config(table,payload):
    import json, uuid
    from datetime import datetime, timezone
    singular="watchlist" if table=="watchlists" else "screener"
    item_id=str(payload.get("id") or f"{singular}_"+uuid.uuid4().hex[:10])
    name=str(payload.get("name") or item_id); now=datetime.now(timezone.utc).isoformat()
    value=payload.get("symbols",[]) if table=="watchlists" else payload.get("config",payload)
    value_col="symbols_json" if table=="watchlists" else "config_json"
    with _DATABASE.transaction() as c:
        c.execute(f"INSERT INTO {table}(id,name,{value_col},created_at,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,{value_col}=excluded.{value_col},updated_at=excluded.updated_at",(item_id,name,json.dumps(value),now,now))
    return {"id":item_id,"name":name,"value":value}

def _update_risk_setting(payload):
    allowed={"risk_per_trade_pct","max_daily_loss","max_open_positions"}
    changes=payload.get("changes",payload)
    if set(changes)-allowed: raise ValueError("Only profile risk settings may be changed in Stage 4")
    return _PROFILE_SERVICE.apply(changes)


_DRAFT_SERVICE = ActionDraftService(_DATABASE, {
    "update_profile": _PROFILE_SERVICE.apply,
    "save_dashboard_layout": _DASHBOARD_SERVICE.save,
    "delete_dashboard_layout": lambda p: _DASHBOARD_SERVICE.delete(p["layout_id"]),
    "add_dashboard_widget": lambda p: _DASHBOARD_SERVICE.add_widget(p["layout_id"], p),
    "remove_dashboard_widget": lambda p: _DASHBOARD_SERVICE.remove_widget(p["layout_id"],p["widget_id"]),
    "toggle_strategy": lambda p: _STRATEGY_LIBRARY.toggle(p["strategy_id"],bool(p["enabled"])),
    "toggle_combo": lambda p: _COMBO_SERVICE.toggle(p["combo_id"],bool(p["enabled"])),
    "apply_strategy_change": _apply_strategy_change,
    "apply_combo_change": _apply_combo_change,
    "run_backtest": _run_approved_backtest,
    "place_paper_order": _approved_paper_order,
    "cancel_paper_order": lambda p: _PAPER_SERVICE.cancel_order(str(p["order_id"])),
    "reset_paper_account": lambda _p: _PAPER_SERVICE.reset(),
    "add_trade_journal_note": _TRADE_HISTORY_SERVICE.annotate,
    "save_screener": lambda p: _save_named_config("saved_screeners",p),
    "update_watchlist": lambda p: _save_named_config("watchlists",p),
    "update_risk_setting": _update_risk_setting,
})
_TOOL_EXECUTOR = ToolExecutor(_TOOL_REGISTRY,_READONLY_TOOLS,_DRAFT_SERVICE)
_ASSISTANT_SERVICE = AssistantService(_DATABASE,LMStudioClient(),_RAG_RETRIEVER,_TOOL_EXECUTOR,_DRAFT_SERVICE,_PROFILE_SERVICE,_TRADE_HISTORY_SERVICE)


def _stage1_state_payload() -> dict:
    load_cached_report()
    paper = _PAPER_SERVICE.snapshot()
    account = paper["account"]
    strategies = _STRATEGY_SERVICE.list_all()
    custom_items = _STRATEGY_SERVICE.custom.list()
    position_rows = [
        {**row, "ticker": row["symbol"], "average_price": row["avg_price"],
         "highest_price_seen": row["highest_price"], "stop_loss_price": round(row["avg_price"] * 0.95, 2),
         "take_profit_price": round(row["avg_price"] * 1.15, 2), "trailing_stop_pct": 0.07,
         "invested_value": round(row["quantity"] * row["avg_price"], 2),
         "current_value": round(row["quantity"] * row["last_price"], 2),
         "unrealized_pnl_pct": round((row["last_price"] / row["avg_price"] - 1) * 100, 2) if row["avg_price"] else 0}
        for row in paper["positions"]
    ]
    return {
        **APP_STATE,
        "mode": "PAPER",
        "live_trading_enabled": SETTINGS.live_trading_enabled,
        "kill_switch": SETTINGS.kill_switch,
        "risk_status": "HALTED" if SETTINGS.kill_switch else "PROTECTED",
        "data_freshness": _DATA_SERVICE.freshness(),
        "reports_stale": _DATA_SERVICE.reports_stale(),
        "account": {
            "mode": "PAPER", "connected": False, "market_open": bot.is_market_open(),
            "initial_capital": account["starting_capital"], "cash_balance": account["cash"],
            "portfolio_value": account["total_equity"], "active_positions": len(paper["positions"]),
            "unrealized_pnl": account["unrealized_pnl"], "realized_pnl": account["realized_pnl"],
            "positions": position_rows, "orders": paper["orders"], "trades": paper["trades"],
            "logs": [],
        },
        "strategies": [
            {"name": row["strategy_id"], "label": row["name"].replace("_", " "),
             "description": row["description"], "enabled": row["enabled"], "custom": False,
             "category": row["category"], "direction": row["direction"], "timeframe": row["timeframe"],
             "status": row["status"]}
            for row in strategies
        ] + [
            {"name": row["strategy_id"], "label": row["name"].replace("_", " "),
             "description": row["description"] or row["expression"], "enabled": row["enabled"], "custom": True,
             "category": "custom", "direction": "rule", "timeframe": "1d", "status": row["validation_status"]}
            for row in custom_items
        ],
        "custom_strategies": custom_items,
        "universe_size": len(cfg.get_full_ticker_universe()),
        "paths": {"data_dir": cfg.DATA_DIR, "reports_dir": cfg.REPORTS_DIR, "consolidated_file": cfg.CONSOLIDATED_FILE},
        "zerodha": {"connected": False, "mode": "DISABLED", "api_key": ""},
        "reports": _reports_payload(),
    }


def _run_stage1_paper_scan() -> dict:
    report_frame = strategy_selector.load_performance_report()
    enabled = {row["strategy_id"] for row in _STRATEGY_SERVICE.list_all() if row["enabled"]}
    enabled.update(row["strategy_id"] for row in _STRATEGY_SERVICE.custom.list() if row["enabled"] and row["validation_status"] == "valid")
    eligible = report_frame[report_frame["Strategy"].isin(enabled)]
    if eligible.empty:
        raise RuntimeError("No enabled strategy has a current performance report.")
    winning = str(strategy_selector.score_strategies(eligible, apply_runtime_filter=False).iloc[0]["Strategy"])
    exits = _PAPER_SERVICE.exit_sweep()
    checked = candidates = placed = 0
    warnings: list[str] = []
    for ticker in cfg.get_full_ticker_universe()[:60]:
        if len(_PAPER_SERVICE.positions()) >= cfg.MAX_PORTFOLIO_POSITIONS:
            break
        latest = bot._load_latest_bar(ticker)
        if latest is None:
            continue
        checked += 1
        if int(latest.get(winning, 0)) != 1:
            continue
        candidates += 1
        price = float(latest["Close"])
        atr = latest.get("ATR_14")
        if atr is None or pd.isna(atr) or float(atr) <= 0:
            warnings.append(f"{ticker}: ATR_14 unavailable; equal-slot sizing used")
            qty = max(int((_PAPER_SERVICE.account()["cash"] / cfg.MAX_PORTFOLIO_POSITIONS) / price), 1)
        else:
            risk_amount = _PAPER_SERVICE.account()["cash"] * cfg.PER_TRADE_RISK_PCT
            qty = max(int(risk_amount / (float(atr) * 2.0)), 1)
        try:
            _PAPER_SERVICE.place_order(ticker, "BUY", qty, strategy_id=winning)
            placed += 1
        except Exception as exc:
            warnings.append(f"{ticker}: {exc}")
    APP_STATE.update({"last_run": _now(), "status": "Ready", "winning_strategy": winning})
    return {"winning_strategy": winning, "signals_checked": checked, "buy_candidates": candidates,
            "orders_placed": placed, **exits, "warnings": warnings, "mode": "PAPER"}


# This later definition intentionally replaces the prototype route assembly above.
def create_flask_app():
    from flask import Flask
    app = Flask(__name__, template_folder=os.path.join(PROJECT_ROOT, "templates"), static_folder=os.path.join(PROJECT_ROOT, "static"))
    app.register_blueprint(create_dashboard_blueprint(_stage1_state_payload))
    app.register_blueprint(create_data_blueprint(_REPORT_SERVICE))
    app.register_blueprint(create_strategy_blueprint(_STRATEGY_SERVICE))
    app.register_blueprint(create_paper_blueprint(_PAPER_SERVICE, _run_stage1_paper_scan))
    app.register_blueprint(create_broker_blueprint(_DATABASE))
    app.register_blueprint(create_backtest_blueprint(_BACKTEST_SERVICE))
    app.register_blueprint(create_strategy_library_blueprint(_STRATEGY_LIBRARY, _BACKTEST_SERVICE))
    app.register_blueprint(create_combo_strategy_blueprint(_COMBO_SERVICE, _BACKTEST_SERVICE))
    app.register_blueprint(create_assistant_blueprint(_ASSISTANT_SERVICE,_DRAFT_SERVICE,_TOOL_REGISTRY))
    app.register_blueprint(create_rag_blueprint(_RAG_INDEXER,_RAG_RETRIEVER))
    app.register_blueprint(create_profile_blueprint(_PROFILE_SERVICE,_DRAFT_SERVICE))
    app.register_blueprint(create_dashboard_builder_blueprint(_DASHBOARD_SERVICE,_DRAFT_SERVICE))
    app.register_blueprint(create_app_search_blueprint(_APP_SEARCH_SERVICE,_TRADE_HISTORY_SERVICE,_DRAFT_SERVICE))

    @app.get("/api/get_reports")
    def get_reports():
        from app.routes.common import success
        return success(_reports_payload())

    return app


def _startup_maintenance() -> None:
    """Refresh data/report artifacts without delaying dashboard availability."""
    try:
        sync_result = data.download_all()
        log_event("info", "main", "data_sync", "Raw data synchronization completed", sync_result)
        if _DATA_SERVICE.reports_stale() or not load_cached_report():
            log_event("info", "main", "startup_recalibration", "Cached report missing or stale; rebuilding reports")
            _REPORT_SERVICE.recalibrate()
            load_cached_report()
    except Exception as exc:
        APP_STATE.update({"status":"Warning","last_error":str(exc)})
        log_event("error", "main", "startup_maintenance_failed", str(exc))


def main() -> None:
    cfg.ensure_directories()

    print("=" * 80)
    print("  INTERACTIVE ALGO TRADING TERMINAL")
    print("=" * 80)
    print(f"Dashboard: http://{cfg.DASHBOARD_HOST}:{cfg.DASHBOARD_PORT}")
    print(f"Data dir : {cfg.DATA_DIR}")
    print(f"Reports  : {cfg.REPORTS_DIR}")
    print("=" * 80)

    app = create_flask_app()
    threading.Thread(target=_startup_maintenance, name="startup-maintenance", daemon=True).start()
    app.run(host=cfg.DASHBOARD_HOST, port=cfg.DASHBOARD_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
