from __future__ import annotations

from flask import Blueprint

from app.core.config import SETTINGS
from app.routes.common import failure, success


def create_broker_blueprint(database):
    blueprint = Blueprint("broker_api", __name__)

    @blueprint.post("/api/connect_zerodha")
    def connect_zerodha():
        if not SETTINGS.live_trading_enabled:
            return failure("Live trading is disabled by Stage 1 safety policy.", 403)
        return failure("Live broker activation is intentionally unavailable in Stage 1.", 501)

    @blueprint.get("/api/logs")
    def logs(): return success(database.query("SELECT * FROM system_logs ORDER BY created_at DESC LIMIT 250"))
    @blueprint.get("/api/risk_events")
    def risk_events(): return success(database.query("SELECT * FROM risk_events ORDER BY created_at DESC LIMIT 250"))
    return blueprint
