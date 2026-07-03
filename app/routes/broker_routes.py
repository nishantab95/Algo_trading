from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flask import Blueprint, request

from app.brokers.broker_errors import (
    BrokerError,
    BrokerModeError,
    BrokerNotConnectedError,
    BrokerPermissionError,
    BrokerReadOnlyError,
    BrokerUnavailableError,
)
from app.brokers.broker_factory import BrokerFactory
from app.core.config import SETTINGS
from app.routes.common import failure, success
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.broker_service import BrokerService


def create_broker_blueprint(database, broker_service: BrokerService | None = None, reconciliation_service: BrokerReconciliationService | None = None):
    blueprint = Blueprint("broker_api", __name__)
    service = broker_service or BrokerService(BrokerFactory(database=database))
    reconciliation = reconciliation_service or BrokerReconciliationService(database, service)

    def body() -> dict:
        return request.get_json(silent=True) or {}

    def actor() -> str:
        return str(body().get("actor", "user")).strip().lower() or "user"

    def broker_failure(exc: Exception):
        if isinstance(exc, (BrokerPermissionError, BrokerReadOnlyError)):
            return failure(exc, 403)
        if isinstance(exc, BrokerModeError):
            return failure(exc, 400)
        if isinstance(exc, (BrokerNotConnectedError, BrokerUnavailableError)):
            return failure(exc, 503)
        return failure(exc, 400)

    def read_endpoint(callback: Callable[[], Any]):
        try:
            return success(callback())
        except BrokerError as exc:
            return broker_failure(exc)
        except Exception as exc:
            return failure(exc, 400)

    @blueprint.get("/api/broker/status")
    def broker_status():
        return success(service.get_status())

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
        except BrokerError as exc:
            return broker_failure(exc)
        except ValueError as exc:
            return failure(exc, 400)

    @blueprint.get("/api/broker/profile")
    def broker_profile():
        return read_endpoint(service.profile)

    @blueprint.get("/api/broker/funds")
    def broker_funds():
        return read_endpoint(service.funds)

    @blueprint.get("/api/broker/holdings")
    def broker_holdings():
        return read_endpoint(service.holdings)

    @blueprint.get("/api/broker/positions")
    def broker_positions():
        return read_endpoint(service.positions)

    @blueprint.get("/api/broker/orders")
    def broker_orders():
        return read_endpoint(service.orders)

    @blueprint.get("/api/broker/trades")
    def broker_trades():
        return read_endpoint(service.trades)

    @blueprint.get("/api/broker/quote/<symbol>")
    def broker_quote(symbol: str):
        return read_endpoint(lambda: service.quote(symbol))

    @blueprint.get("/api/broker/quotes")
    def broker_quotes():
        symbols = request.args.get("symbols", "")
        return read_endpoint(lambda: service.quotes([symbol for symbol in symbols.split(",") if symbol.strip()]))

    @blueprint.post("/api/broker/reconcile")
    def broker_reconcile():
        payload = body()
        try:
            return success(reconciliation.run_reconciliation(payload.get("mode"), payload.get("broker_name")))
        except BrokerError as exc:
            return broker_failure(exc)
        except Exception as exc:
            return failure(exc, 400)

    @blueprint.get("/api/broker/reconciliation/latest")
    def broker_reconciliation_latest():
        return success(reconciliation.get_latest_reconciliation())

    @blueprint.get("/api/broker/reconciliation/history")
    def broker_reconciliation_history():
        try:
            limit = int(request.args.get("limit", 50))
        except ValueError:
            limit = 50
        return success(reconciliation.get_reconciliation_history(limit))

    @blueprint.post("/api/connect_zerodha")
    def connect_zerodha():
        if not SETTINGS.live_trading_enabled:
            return failure("Live trading is disabled by Stage 1 safety policy.", 403)
        return failure("Live broker activation is intentionally unavailable in Stage 7 Batch 3.", 501)

    @blueprint.get("/api/logs")
    def logs(): return success(database.query("SELECT * FROM system_logs ORDER BY created_at DESC LIMIT 250"))
    @blueprint.get("/api/risk_events")
    def risk_events(): return success(database.query("SELECT * FROM risk_events ORDER BY created_at DESC LIMIT 250"))
    return blueprint
