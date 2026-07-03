from __future__ import annotations

from flask import Blueprint, request

from app.brokers.broker_errors import BrokerError, BrokerPermissionError
from app.routes.common import failure, success


def create_tiny_live_blueprint(tiny_live_service):
    blueprint = Blueprint("tiny_live_api", __name__)

    def body() -> dict:
        return request.get_json(silent=True) or {}

    def actor(payload: dict | None = None) -> str:
        payload = payload if payload is not None else body()
        return str(payload.get("actor", "user")).strip().lower() or "user"

    def broker_failure(exc: Exception):
        status = 403 if isinstance(exc, BrokerPermissionError) else 400
        return failure(exc, status)

    @blueprint.get("/api/tiny-live/status")
    def tiny_live_status():
        return success(tiny_live_service.status())

    @blueprint.post("/api/tiny-live/unlock")
    def tiny_live_unlock():
        payload = body()
        try:
            return success(tiny_live_service.unlock(str(payload.get("phrase", "")), actor(payload)))
        except BrokerError as exc:
            return broker_failure(exc)
        except Exception as exc:
            return failure(exc, 400)

    @blueprint.post("/api/tiny-live/lock")
    def tiny_live_lock():
        payload = body()
        try:
            return success(tiny_live_service.lock(actor(payload)))
        except BrokerError as exc:
            return broker_failure(exc)
        except Exception as exc:
            return failure(exc, 400)

    @blueprint.get("/api/tiny-live/limits")
    def tiny_live_limits():
        return success(tiny_live_service.limits())

    @blueprint.post("/api/tiny-live/limits")
    def tiny_live_update_limits():
        payload = body()
        try:
            changes = payload.get("limits", payload)
            return success(tiny_live_service.update_limits(changes, actor(payload)))
        except BrokerError as exc:
            return broker_failure(exc)
        except Exception as exc:
            return failure(exc, 400)

    @blueprint.post("/api/tiny-live/order/preflight")
    def tiny_live_order_preflight():
        payload = body()
        try:
            return success(tiny_live_service.preflight_order(payload, actor(payload)))
        except BrokerError as exc:
            return broker_failure(exc)
        except Exception as exc:
            return failure(exc, 400)

    return blueprint
