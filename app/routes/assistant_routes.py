from __future__ import annotations

from flask import Blueprint,request

from app.routes.common import failure,success


def create_assistant_blueprint(service,drafts,registry):
    bp=Blueprint("assistant_api",__name__)
    @bp.get("/api/assistant/status")
    def status(): return success(service.status())
    @bp.post("/api/assistant/chat")
    def chat():
        payload=request.get_json(silent=True) or {}
        try: return success(service.chat(str(payload.get("message","")),payload.get("conversation_id"),payload.get("action_payload")))
        except Exception as exc: return failure(exc)
    @bp.get("/api/assistant/conversations")
    def conversations(): return success(service.conversations())
    @bp.get("/api/assistant/conversations/<conversation_id>")
    def conversation(conversation_id):
        try:return success(service.conversation(conversation_id))
        except Exception as exc:return failure(exc,404)
    @bp.post("/api/assistant/action-drafts/<draft_id>/approve")
    def approve(draft_id):
        try:return success(drafts.approve(draft_id,"user"))
        except Exception as exc:return failure(exc)
    @bp.post("/api/assistant/action-drafts/<draft_id>/reject")
    def reject(draft_id):
        try:return success(drafts.reject(draft_id,"user"))
        except Exception as exc:return failure(exc)
    @bp.get("/api/assistant/tools")
    def tools(): return success(registry.list())
    return bp
