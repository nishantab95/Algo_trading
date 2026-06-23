from __future__ import annotations

from flask import Blueprint,request
from app.routes.common import failure,success


def create_rag_blueprint(indexer,retriever):
    bp=Blueprint("rag_api",__name__)
    @bp.post("/api/rag/reindex")
    def reindex():
        try:return success(indexer.reindex())
        except Exception as exc:return failure(exc)
    @bp.get("/api/rag/status")
    def status(): return success(indexer.status())
    @bp.post("/api/rag/search")
    def search():
        payload=request.get_json(silent=True) or {}
        try:return success(retriever.search(str(payload.get("query","")),payload.get("source_type"),int(payload.get("limit",10))))
        except Exception as exc:return failure(exc)
    return bp
