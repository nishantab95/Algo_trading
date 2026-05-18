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


def create_flask_app():
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


def main() -> None:
    cfg.ensure_directories()
    data.download_all()
    if not load_cached_report():
        print("[MAIN] No cached report found; building reports from canonical data.")
        _run_full_recalibration()

    print("=" * 80)
    print("  INTERACTIVE ALGO TRADING TERMINAL")
    print("=" * 80)
    print(f"Dashboard: http://{cfg.DASHBOARD_HOST}:{cfg.DASHBOARD_PORT}")
    print(f"Data dir : {cfg.DATA_DIR}")
    print(f"Reports  : {cfg.REPORTS_DIR}")
    print("=" * 80)

    app = create_flask_app()
    app.run(host=cfg.DASHBOARD_HOST, port=cfg.DASHBOARD_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
