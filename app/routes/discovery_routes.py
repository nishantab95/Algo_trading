from __future__ import annotations

from flask import Blueprint, request

from app.routes.common import failure, success


def create_discovery_blueprint(service):
    blueprint = Blueprint("discovery_api", __name__)

    @blueprint.get("/api/discovery/symbols")
    def symbols():
        try:
            return success({"symbols": service.list_symbols(request.args.get("universe", "nse"))})
        except Exception as exc:
            return failure(exc)

    @blueprint.post("/api/discovery/symbols")
    def add_symbol():
        payload = request.get_json(silent=True) or {}
        try:
            return success(service.add_custom_symbol(payload.get("symbol", ""), payload.get("exchange")), status=201)
        except Exception as exc:
            return failure(exc)

    @blueprint.delete("/api/discovery/symbols/<path:symbol>")
    def remove_symbol(symbol: str):
        try:
            service.remove_custom_symbol(symbol)
            return success({"removed": symbol.upper()})
        except Exception as exc:
            return failure(exc)

    @blueprint.post("/api/discovery/update")
    def update():
        payload = request.get_json(silent=True) or {}
        if str(payload.get("provider", "yahoo")).lower() != "yahoo":
            return failure("Yahoo Finance is the only enabled provider in Stage 2.")
        try:
            return success(service.update(str(payload.get("universe", "nse")).lower(), str(payload.get("lookback", "1y")).lower()))
        except Exception as exc:
            return failure(exc)

    return blueprint
