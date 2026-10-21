from __future__ import annotations

from flask import Blueprint

from app.routes.common import failure, success


def create_fundamental_blueprint(service):
    blueprint = Blueprint("fundamental_api", __name__)

    @blueprint.get("/api/discovery/fundamentals/<path:symbol>")
    def cached(symbol: str):
        try: return success(service.cached(symbol))
        except Exception as exc: return failure(exc)

    @blueprint.post("/api/discovery/fundamentals/<path:symbol>/refresh")
    def refresh(symbol: str):
        try: return success(service.get(symbol, refresh=True))
        except Exception as exc: return failure(exc)

    return blueprint
