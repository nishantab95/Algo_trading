from __future__ import annotations
from flask import Blueprint,jsonify,request
from app.backtesting.models import BacktestConfig

def _ok(data,warnings=None,status=200): return jsonify({"success":True,"data":data,"warnings":warnings or []}),status
def _bad(exc,status=400): return jsonify({"success":False,"error":str(exc),"details":{}}),status
def create_strategy_library_blueprint(service,backtests):
    bp=Blueprint("strategy_library_api",__name__)
    @bp.get("/api/strategy-library")
    def list_library(): return _ok(service.list(request.args.get("category"),request.args.get("status"),request.args.get("direction"),request.args.get("search")))
    @bp.get("/api/strategy-library/<strategy_id>")
    def detail(strategy_id):
        try: return _ok(service.get(strategy_id))
        except Exception as exc: return _bad(exc,404)
    @bp.post("/api/strategy-library/<strategy_id>/toggle")
    def toggle(strategy_id):
        try: return _ok(service.toggle(strategy_id,bool((request.get_json(silent=True) or {}).get("enabled",True))))
        except Exception as exc: return _bad(exc)
    @bp.post("/api/strategy-library/<strategy_id>/validate")
    def validate(strategy_id):
        try:
            payload=request.get_json(silent=True) or {}; result=service.validate(strategy_id,payload.get("available_columns"),payload.get("direction_mode")); return _ok(result,result.get("warnings"))
        except Exception as exc: return _bad(exc)
    @bp.post("/api/strategy-library/<strategy_id>/backtest")
    def backtest(strategy_id):
        try:
            payload=request.get_json(silent=True) or {}; payload["strategy_id"]=strategy_id; result=backtests.run(BacktestConfig(**payload)); return _ok(result.summary(),result.warnings,201)
        except Exception as exc: return _bad(exc)
    @bp.get("/api/strategy-categories")
    def categories(): return _ok(service.categories())
    @bp.get("/api/strategy-primitives")
    def primitives(): return _ok(service.primitives())
    return bp
