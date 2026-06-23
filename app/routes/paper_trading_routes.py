from __future__ import annotations

from flask import Blueprint,request
from app.routes.common import failure,success


def create_stage5_paper_blueprint(broker,portfolio,analytics,reports):
    bp=Blueprint("stage5_paper_api",__name__)
    def body():return request.get_json(silent=True) or {}

    @bp.get("/api/paper/account")
    def account():return success(broker.account())
    @bp.post("/api/paper/account/reset")
    def reset():
        try:return success(broker.reset(body().get("confirm") is True))
        except Exception as exc:return failure(exc)
    @bp.get("/api/paper/account/snapshots")
    def snapshots():return success(broker.snapshots())
    @bp.get("/api/paper/orders")
    def orders():return success(broker.orders())
    @bp.post("/api/paper/orders")
    def create_order():
        try:return success(broker.create_order(body()),status=201)
        except Exception as exc:return failure(exc)
    @bp.get("/api/paper/orders/<int:order_id>")
    def order(order_id):
        try:return success(broker.order(order_id))
        except Exception as exc:return failure(exc,404)
    @bp.post("/api/paper/orders/<int:order_id>/approve")
    def approve(order_id):
        try:return success(broker.approve_order(order_id,"user"))
        except Exception as exc:return failure(exc)
    @bp.post("/api/paper/orders/<int:order_id>/cancel")
    def cancel(order_id):
        try:return success(broker.cancel_order(order_id))
        except Exception as exc:return failure(exc)
    @bp.get("/api/paper/positions")
    def positions():return success(broker.positions())
    @bp.get("/api/paper/positions/<int:position_id>")
    def position(position_id):
        try:return success(broker.position(position_id))
        except Exception as exc:return failure(exc,404)
    def draft_exit(position_id,partial=False):
        try:
            p=broker.position(position_id);payload=body();qty=int(payload.get("quantity",p["quantity"] if not partial else 0))
            if qty<=0 or qty>p["quantity"]:raise ValueError("Valid exit quantity is required")
            return success(broker.create_order({"symbol":p["symbol"],"side":"SELL","quantity":qty,"order_type":"market","strategy_id":p["strategy_id"],"combo_id":p["combo_id"],"source":"manual_exit","metadata":{"exit_reason":"partial_exit" if partial else "manual_exit"}}),status=201)
        except Exception as exc:return failure(exc)
    @bp.post("/api/paper/positions/<int:position_id>/exit")
    def exit_position(position_id):return draft_exit(position_id)
    @bp.post("/api/paper/positions/<int:position_id>/partial-exit")
    def partial_exit(position_id):return draft_exit(position_id,True)
    @bp.post("/api/paper/positions/<int:position_id>/risk")
    def position_risk(position_id):
        payload=body()
        if payload.pop("confirm",False) is not True:return failure("Explicit confirmation is required")
        try:return success(broker.update_position_risk(position_id,payload))
        except Exception as exc:return failure(exc)
    @bp.post("/api/paper/exit-sweep")
    def exit_sweep():
        try:return success(broker.exit_sweep())
        except Exception as exc:return failure(exc)
    @bp.get("/api/paper/portfolio/summary")
    def portfolio_summary():return success(portfolio.summary())
    @bp.get("/api/paper/portfolio/equity-curve")
    def portfolio_equity():return success(portfolio.equity_curve())
    @bp.get("/api/paper/portfolio/exposure")
    def portfolio_exposure():return success(portfolio.exposure())
    @bp.get("/api/paper/portfolio/pnl")
    def portfolio_pnl():return success(portfolio.pnl())
    @bp.get("/api/paper/journal")
    def journal():return success(broker.journal(dict(request.args)))
    @bp.get("/api/paper/journal/<int:trade_id>")
    def journal_trade(trade_id):
        rows=[x for x in broker.journal() if x["id"]==trade_id]
        return success(rows[0]) if rows else failure("Unknown paper journal trade",404)
    def journal_update(trade_id,changes):
        payload=body()
        if payload.get("approved_by_user") is not True:return failure("Explicit user approval is required")
        try:return success(broker.update_journal(trade_id,changes(payload)))
        except Exception as exc:return failure(exc)
    @bp.post("/api/paper/journal/<int:trade_id>/notes")
    def notes(trade_id):return journal_update(trade_id,lambda p:{"notes":p.get("notes","")})
    @bp.post("/api/paper/journal/<int:trade_id>/tags")
    def tags(trade_id):return journal_update(trade_id,lambda p:{"mistake_tags_json":p.get("tags",[])})
    @bp.post("/api/paper/journal/<int:trade_id>/rule-followed")
    def rule_followed(trade_id):return journal_update(trade_id,lambda p:{"rule_followed":p.get("rule_followed","unknown")})
    @bp.post("/api/paper/journal/export")
    def export_journal():return success({"path":reports.export_journal()})
    @bp.get("/api/paper/analytics/summary")
    def analytics_summary():return success(analytics.summary())
    @bp.get("/api/paper/analytics/by-strategy")
    def by_strategy():return success(analytics.grouped("strategy_id"))
    @bp.get("/api/paper/analytics/by-symbol")
    def by_symbol():return success(analytics.grouped("symbol"))
    @bp.get("/api/paper/analytics/mistakes")
    def mistakes():return success(analytics.mistakes())
    @bp.get("/api/paper/analytics/promotion-review/<strategy_id>")
    def review(strategy_id):return success(analytics.promotion_review(strategy_id,persist=False))
    @bp.post("/api/paper/reports/export")
    def export_reports():return success(reports.export_all())
    return bp
