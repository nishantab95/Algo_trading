from __future__ import annotations
from flask import Blueprint,jsonify,request
from app.backtesting.models import BacktestConfig

def _ok(data,warnings=None,status=200): return jsonify({"success":True,"data":data,"warnings":warnings or []}),status
def _bad(exc,status=400): return jsonify({"success":False,"error":str(exc),"details":{}}),status
def create_combo_strategy_blueprint(service,backtests):
    bp=Blueprint("combo_strategy_api",__name__)
    @bp.get("/api/combo-strategies")
    def combos(): return _ok(service.list())
    @bp.post("/api/combo-strategies")
    def create():
        try: return _ok(service.save(request.get_json(silent=True) or {}),status=201)
        except Exception as exc: return _bad(exc)
    @bp.get("/api/combo-strategies/<combo_id>")
    def detail(combo_id):
        try: return _ok(service.get(combo_id))
        except Exception as exc: return _bad(exc,404)
    @bp.put("/api/combo-strategies/<combo_id>")
    def update(combo_id):
        try: return _ok(service.update(combo_id,request.get_json(silent=True) or {}))
        except Exception as exc: return _bad(exc)
    @bp.post("/api/combo-strategies/<combo_id>/validate")
    def validate(combo_id):
        try:
            result=service.validate(combo_id); return _ok(result,result.get("warnings"))
        except Exception as exc: return _bad(exc)
    @bp.post("/api/combo-strategies/<combo_id>/backtest")
    def backtest(combo_id):
        try:
            payload=request.get_json(silent=True) or {}; payload["strategy_id"]=combo_id; result=backtests.run(BacktestConfig(**payload)); return _ok(result.summary(),result.warnings,201)
        except Exception as exc: return _bad(exc)
    @bp.post("/api/combo-strategies/<combo_id>/duplicate")
    def duplicate(combo_id):
        try: return _ok(service.duplicate(combo_id),status=201)
        except Exception as exc: return _bad(exc)
    @bp.post("/api/combo-strategies/<combo_id>/toggle")
    def toggle(combo_id):
        try: return _ok(service.toggle(combo_id,bool((request.get_json(silent=True) or {}).get("enabled",True))))
        except Exception as exc: return _bad(exc)
    return bp
