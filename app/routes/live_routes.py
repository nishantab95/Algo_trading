from __future__ import annotations

from flask import Blueprint, request

from app.brokers.broker_errors import BrokerError
from app.routes.common import failure, success
from app.services.live_readiness_service import LiveReadinessService


def create_live_blueprint(readiness_service: LiveReadinessService):
    blueprint = Blueprint("live_api", __name__)

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
        payload = request.get_json(silent=True) or {}
        try:
            return success(readiness_service.run_readiness(payload.get("mode")))
        except BrokerError as exc:
            return failure(exc, 400)
        except Exception as exc:
            return failure(exc, 400)

    return blueprint
