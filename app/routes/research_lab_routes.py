from __future__ import annotations

import json
from flask import Blueprint,request
from app.research_lab.correlation import compare_strategies
from app.routes.common import failure,success


def create_research_lab_blueprint(experiments,runner,decisions,exports,database):
    bp=Blueprint("research_lab_api",__name__)
    @bp.get("/api/research/experiments")
    def list_experiments():return success(experiments.list())
    @bp.post("/api/research/experiments")
    def create_experiment():
        try:return success(experiments.create(request.get_json(silent=True) or {}),status=201)
        except Exception as exc:return failure(exc)
    @bp.get("/api/research/experiments/<experiment_id>")
    def experiment(experiment_id):
        try:return success(experiments.get(experiment_id))
        except Exception as exc:return failure(exc,404)
    @bp.post("/api/research/experiments/<experiment_id>/run")
    def run_experiment(experiment_id):
        try:return success(runner.run(experiment_id))
        except Exception as exc:return failure(exc)
    @bp.post("/api/research/experiments/<experiment_id>/cancel")
    def cancel_experiment(experiment_id):
        try:return success(experiments.cancel(experiment_id))
        except Exception as exc:return failure(exc)
    @bp.get("/api/research/experiments/<experiment_id>/summary")
    def summary(experiment_id):
        try:return success(experiments.get(experiment_id).get("summary"))
        except Exception as exc:return failure(exc,404)
    @bp.post("/api/research/walk-forward/run")
    def run_walk_forward():
        payload=request.get_json(silent=True) or {}
        try:return success(runner.run(payload["experiment_id"])["walk_forward"])
        except Exception as exc:return failure(exc)
    @bp.get("/api/research/walk-forward/<experiment_id>")
    def walk_forward(experiment_id):
        rows=database.query("SELECT summary_json FROM research_validation_summaries WHERE experiment_id=?",(experiment_id,));return success(json.loads(rows[0]["summary_json"])["walk_forward"]) if rows else failure("No walk-forward result",404)
    @bp.get("/api/research/walk-forward/<experiment_id>/folds")
    def folds(experiment_id):return success(database.query("SELECT * FROM walk_forward_folds WHERE experiment_id=? ORDER BY fold_number",(experiment_id,)))
    @bp.post("/api/research/parameter-sweep/run")
    def run_sweep():
        payload=request.get_json(silent=True) or {}
        try:return success(runner.run(payload["experiment_id"])["parameter_stability"])
        except Exception as exc:return failure(exc)
    @bp.get("/api/research/parameter-sweep/<experiment_id>")
    def sweep(experiment_id):return success(database.query("SELECT * FROM parameter_sweep_results WHERE experiment_id=? ORDER BY rank",(experiment_id,)))
    @bp.post("/api/research/robustness/run")
    def run_robustness_route():
        payload=request.get_json(silent=True) or {}
        try:return success(runner.run(payload["experiment_id"])["robustness"])
        except Exception as exc:return failure(exc)
    @bp.get("/api/research/robustness/<experiment_id>")
    def robustness(experiment_id):return success(database.query("SELECT * FROM robustness_results WHERE experiment_id=? ORDER BY id",(experiment_id,)))
    @bp.get("/api/research/regime/<experiment_id>")
    def regimes(experiment_id):return success(database.query("SELECT * FROM regime_results WHERE experiment_id=? ORDER BY id",(experiment_id,)))
    @bp.get("/api/research/symbol-analysis/<experiment_id>")
    def symbols(experiment_id):return success(database.query("SELECT * FROM symbol_analysis_results WHERE experiment_id=? ORDER BY contribution_pct DESC",(experiment_id,)))
    @bp.get("/api/research/correlation")
    def correlations():return success(database.query("SELECT * FROM strategy_correlation_results ORDER BY created_at DESC"))
    @bp.post("/api/research/correlation/run")
    def run_correlation():
        p=request.get_json(silent=True) or {}
        try:
            result=compare_strategies(p["strategy_a"],p["strategy_b"],p.get("signals_a",[]),p.get("signals_b",[]),p.get("equity_a"),p.get("equity_b"))
            from app.research_lab.experiment import now
            with database.transaction() as c:c.execute("INSERT INTO strategy_correlation_results(strategy_a,strategy_b,signal_correlation,equity_correlation,trade_overlap_pct,drawdown_overlap_pct,redundancy_score,recommendation,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(result["strategy_a"],result["strategy_b"],result["signal_correlation"],result["equity_correlation"],result["trade_overlap_pct"],result["drawdown_overlap_pct"],result["redundancy_score"],result["recommendation"],now()))
            return success(result)
        except Exception as exc:return failure(exc)
    @bp.post("/api/research/decision/<experiment_id>/draft")
    def draft_decision(experiment_id):
        try:
            exp=experiments.get(experiment_id);summary=exp.get("summary")
            if not summary:raise ValueError("Experiment validation is incomplete")
            return success(decisions.draft(exp,summary["recommendation"],summary["evidence"]["evidence_score"]),status=201)
        except Exception as exc:return failure(exc)
    @bp.post("/api/research/decision/<experiment_id>/approve")
    def approve_decision(experiment_id):
        payload=request.get_json(silent=True) or {}
        try:
            decision_id=payload.get("decision_id") or database.query("SELECT id FROM research_decisions WHERE experiment_id=? AND status='pending' ORDER BY created_at DESC LIMIT 1",(experiment_id,))[0]["id"]
            return success(decisions.approve(decision_id,"user"))
        except Exception as exc:return failure(exc)
    @bp.post("/api/research/decision/<experiment_id>/reject")
    def reject_decision(experiment_id):
        payload=request.get_json(silent=True) or {}
        try:
            decision_id=payload.get("decision_id") or database.query("SELECT id FROM research_decisions WHERE experiment_id=? AND status='pending' ORDER BY created_at DESC LIMIT 1",(experiment_id,))[0]["id"]
            return success(decisions.reject(decision_id,"user"))
        except Exception as exc:return failure(exc)
    @bp.post("/api/research/reports/export")
    def export_reports():return success(exports.export_all())
    @bp.post("/api/research/experiments/<experiment_id>/report")
    def export_report(experiment_id):
        try:return success({"path":exports.export_experiment(experiments.get(experiment_id))})
        except Exception as exc:return failure(exc)
    return bp
