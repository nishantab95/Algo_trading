from __future__ import annotations

from flask import Blueprint, request

from app.brokers.broker_factory import BrokerFactory
from app.brokers.broker_service import BrokerService
from app.core.config import SETTINGS
from app.core.errors import BrokerError
from app.routes.common import failure, success


def create_broker_blueprint(database, broker_service: BrokerService | None = None):
    blueprint = Blueprint("broker_api", __name__)
    service = broker_service or BrokerService(BrokerFactory(database=database))

    def body() -> dict:
        return request.get_json(silent=True) or {}

    def actor() -> str:
        return str(body().get("actor", "user")).strip().lower() or "user"

    @blueprint.get("/api/broker/status")
    def broker_status():
        return success(service.status())

    @blueprint.get("/api/broker/modes")
    def broker_modes():
        return success(service.modes())

    @blueprint.get("/api/broker/mode")
    def broker_mode():
        return success(service.mode())

    @blueprint.post("/api/broker/mode")
    def set_broker_mode():
        payload = body()
        try:
            return success(service.set_mode(str(payload.get("mode", "")), actor()))
        except PermissionError as exc:
            return failure(exc, 403)
        except (BrokerError, ValueError) as exc:
            return failure(exc, 400)

    @blueprint.get("/api/broker/quotes")
    def broker_quotes():
        symbols = request.args.get("symbols", "")
        return success(service.quotes([symbol for symbol in symbols.split(",") if symbol.strip()]))

    @blueprint.get("/api/broker/funds")
    def broker_funds():
        return success(service.funds())

    @blueprint.get("/api/broker/positions")
    def broker_positions():
        return success(service.positions())

    @blueprint.get("/api/broker/holdings")
    def broker_holdings():
        return success(service.holdings())

    @blueprint.post("/api/connect_zerodha")
    def connect_zerodha():
        if not SETTINGS.live_trading_enabled:
            return failure("Live trading is disabled by Stage 1 safety policy.", 403)
        return failure("Live broker activation is intentionally unavailable in Stage 7 Batch 2.", 501)

    @blueprint.get("/api/logs")
    def logs(): return success(database.query("SELECT * FROM system_logs ORDER BY created_at DESC LIMIT 250"))
    @blueprint.get("/api/risk_events")
    def risk_events(): return success(database.query("SELECT * FROM risk_events ORDER BY created_at DESC LIMIT 250"))
    return blueprint
