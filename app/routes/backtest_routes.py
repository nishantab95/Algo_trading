from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.backtesting.models import BacktestConfig
from app.core.logging_config import log_event


def _ok(data, warnings=None, status=200): return jsonify({"success": True, "data": data, "error": None, "warnings": warnings or []}), status
def _error(exc, status=400): return jsonify({"success": False, "data": None, "error": str(exc), "details": {}, "warnings": []}), status


def create_backtest_blueprint(service):
    blueprint = Blueprint("backtest_api", __name__)

    @blueprint.get("/api/backtests")
    def list_runs(): return _ok(service.list_runs())

    @blueprint.get("/api/backtests/<run_id>")
    def details(run_id):
        try: return _ok(service.details(run_id))
        except Exception as exc: return _error(exc, 404)

    @blueprint.get("/api/backtests/<run_id>/trades")
    def trades(run_id): return _ok(service.trades(run_id))

    @blueprint.get("/api/backtests/<run_id>/equity")
    def equity(run_id): return _ok(service.equity(run_id))

    @blueprint.get("/api/backtests/<run_id>/metrics")
    def metrics(run_id): return _ok(service.metrics(run_id))

    @blueprint.post("/api/backtests/run")
    def run_backtest():
        try:
            result = service.run(BacktestConfig(**(request.get_json(silent=True) or {})))
            return _ok(result.summary(), result.warnings, 201)
        except Exception as exc:
            log_event("error", "backtest_routes", "backtest_failed", str(exc)); return _error(exc)

    @blueprint.post("/api/backtests/compare")
    def compare():
        try: return _ok(service.compare(list((request.get_json(silent=True) or {}).get("run_ids", []))))
        except Exception as exc: return _error(exc)

    @blueprint.post("/api/backtests/robustness")
    def robustness():
        try:
            result = service.robustness(BacktestConfig(**(request.get_json(silent=True) or {})))
            return _ok(result, result.get("flags", []))
        except Exception as exc: return _error(exc)

    @blueprint.post("/api/backtests/walk_forward")
    def walk_forward():
        payload = request.get_json(silent=True) or {}
        config_payload = payload.get("config") or {key:value for key,value in payload.items() if key not in {"train_days","test_days","expanding"}}
        try:
            result = service.walk_forward(BacktestConfig(**config_payload), int(payload.get("train_days",504)), int(payload.get("test_days",126)), bool(payload.get("expanding",True)))
            return _ok(result)
        except Exception as exc: return _error(exc)
    return blueprint
