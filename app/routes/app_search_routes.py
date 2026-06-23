from __future__ import annotations

from flask import Blueprint,request
from app.routes.common import failure,success


def create_app_search_blueprint(search,trade_history,drafts):
    bp=Blueprint("app_search_api",__name__)
    @bp.post("/api/search")
    def app_search():
        payload=request.get_json(silent=True) or {}
        try:return success(search.search(str(payload.get("query","")),payload.get("filters",payload),int(payload.get("limit",30))))
        except Exception as exc:return failure(exc)
    @bp.get("/api/search/suggestions")
    def suggestions(): return success(search.suggestions(request.args.get("q","")))
    @bp.get("/api/trade-history")
    def trades(): return success(trade_history.list(dict(request.args)))
    @bp.get("/api/trade-history/<path:trade_id>")
    def trade(trade_id):
        try:return success(trade_history.get(trade_id))
        except Exception as exc:return failure(exc,404)
    @bp.post("/api/trade-history/<path:trade_id>/notes")
    def notes(trade_id): return success(drafts.create("add_trade_journal_note",{"trade_id":trade_id,"note":(request.get_json(silent=True) or {}).get("note","")}))
    @bp.post("/api/trade-history/<path:trade_id>/tags")
    def tags(trade_id): return success(drafts.create("add_trade_journal_note",{"trade_id":trade_id,"tags":(request.get_json(silent=True) or {}).get("tags",[])}))
    return bp
