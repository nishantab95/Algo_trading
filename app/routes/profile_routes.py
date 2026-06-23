from __future__ import annotations

from flask import Blueprint,request
from app.routes.common import failure,success


def create_profile_blueprint(profile,drafts):
    bp=Blueprint("profile_api",__name__)
    @bp.get("/api/profile")
    def get_profile(): return success(profile.get())
    @bp.post("/api/profile/draft-update")
    def draft_update():
        payload=request.get_json(silent=True) or {}; validation=profile.validate(payload)
        try:return success(drafts.create("update_profile",payload,validation=validation),status=201)
        except Exception as exc:return failure(exc)
    @bp.post("/api/profile/update")
    def update():
        payload=request.get_json(silent=True) or {}
        if not payload.get("draft_id"): return failure("Approved draft_id is required")
        try:return success(drafts.approve(payload["draft_id"],"user"))
        except Exception as exc:return failure(exc)
    return bp
