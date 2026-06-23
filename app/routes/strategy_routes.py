from __future__ import annotations

from flask import Blueprint, request

from app.core.logging_config import log_event
from app.routes.common import failure, success


def create_strategy_blueprint(strategy_service):
    blueprint = Blueprint("strategy_api", __name__)

    @blueprint.get("/api/strategies")
    def strategies(): return success(strategy_service.list_all())

    @blueprint.get("/api/custom_strategies")
    def custom_strategies(): return success(strategy_service.custom.list())

    @blueprint.post("/api/add_custom_strategy")
    def add_custom_strategy():
        payload = request.get_json(silent=True) or {}
        try:
            item = strategy_service.custom.save(str(payload.get("name", "")), str(payload.get("condition", payload.get("expression", ""))), str(payload.get("description", "")))
            if item["validation_status"] != "valid": return failure(item["validation_error"] or "Invalid strategy expression")
            return success(item, "Custom strategy saved.", 201)
        except Exception as exc:
            log_event("error", "strategy_routes", "custom_strategy_failed", str(exc)); return failure(exc)

    @blueprint.post("/api/toggle_strategy")
    def toggle_strategy():
        payload = request.get_json(silent=True) or {}; strategy_id = str(payload.get("strategy", payload.get("strategy_id", ""))); enabled = bool(payload.get("enabled", True))
        try:
            custom_ids = {item["strategy_id"] for item in strategy_service.custom.list()}
            if strategy_id in custom_ids: item = strategy_service.custom.set_enabled(strategy_id, enabled)
            else: strategy_service.registry.set_enabled(strategy_id, enabled); item = {"strategy_id": strategy_id, "enabled": enabled}
            return success(item, "Strategy state updated.")
        except Exception as exc:
            log_event("error", "strategy_routes", "toggle_failed", str(exc), {"strategy_id": strategy_id}); return failure(exc)
    return blueprint
