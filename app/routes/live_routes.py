from __future__ import annotations

from flask import Blueprint, request

from app.brokers.broker_errors import BrokerError, BrokerPermissionError
from app.routes.common import failure, success
from app.services.live_readiness_service import LiveReadinessService


def create_live_blueprint(readiness_service: LiveReadinessService, kill_switch_service=None):
    blueprint = Blueprint("live_api", __name__)

    def body() -> dict:
        return request.get_json(silent=True) or {}

    def actor(payload: dict | None = None) -> str:
        payload = payload if payload is not None else body()
        return str(payload.get("actor", "user")).strip().lower() or "user"

    @blueprint.get("/api/live/readiness")
    def latest_readiness():
        latest = readiness_service.latest_run()
        if latest is not None:
            return success(latest)
        try:
            return success(readiness_service.run_readiness(request.args.get("mode")))
        except BrokerError as exc:
            return failure(exc, 400)
        except Exception as exc:
            return failure(exc, 400)

    @blueprint.post("/api/live/readiness/check")
    def run_readiness_check():
        payload = body()
        try:
            return success(readiness_service.run_readiness(payload.get("mode")))
        except BrokerError as exc:
            return failure(exc, 400)
        except Exception as exc:
            return failure(exc, 400)

    @blueprint.get("/api/live/kill-switch")
    def kill_switch_status():
        if kill_switch_service is None:
            return failure("Kill switch service is unavailable; live-like actions fail closed.", 503)
        return success(kill_switch_service.status())

    @blueprint.post("/api/live/kill-switch/trigger")
    def trigger_kill_switch():
        if kill_switch_service is None:
            return failure("Kill switch service is unavailable; live-like actions fail closed.", 503)
        payload = body()
        try:
            return success(kill_switch_service.trigger(payload.get("reason", "manual_trigger"), actor(payload)))
        except BrokerPermissionError as exc:
            return failure(exc, 403)
        except BrokerError as exc:
            return failure(exc, 400)
        except Exception as exc:
            return failure(exc, 400)

    @blueprint.post("/api/live/kill-switch/deactivate")
    def deactivate_kill_switch():
        if kill_switch_service is None:
            return failure("Kill switch service is unavailable; live-like actions fail closed.", 503)
        payload = body()
        try:
            return success(kill_switch_service.deactivate(confirm=payload.get("confirm") is True, actor=actor(payload)))
        except BrokerPermissionError as exc:
            return failure(exc, 403)
        except BrokerError as exc:
            return failure(exc, 400)
        except Exception as exc:
            return failure(exc, 400)

    return blueprint
