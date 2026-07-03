from __future__ import annotations

from flask import Blueprint, request

from app.routes.common import failure, success


def create_shadow_live_blueprint(shadow_live_service):
    blueprint = Blueprint("shadow_live_api", __name__)

    def body() -> dict:
        return request.get_json(silent=True) or {}

    def actor(payload: dict | None = None) -> str:
        payload = payload if payload is not None else body()
        return str(payload.get("actor", "user")).strip().lower() or "user"

    @blueprint.get("/api/shadow-live")
    def shadow_live_events():
        try:
            limit = int(request.args.get("limit", 100))
        except ValueError:
            limit = 100
        return success(shadow_live_service.events(limit))

    @blueprint.post("/api/shadow-live/run")
    def shadow_live_run():
        payload = body()
        try:
            return success(shadow_live_service.run(payload, actor(payload)))
        except Exception as exc:
            return failure(exc, 400)

    @blueprint.get("/api/shadow-live/report")
    def shadow_live_report():
        return success(shadow_live_service.report())

    return blueprint
