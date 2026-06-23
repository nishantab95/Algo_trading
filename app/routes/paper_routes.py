from __future__ import annotations

from flask import Blueprint, request

from app.core.logging_config import log_event
from app.routes.common import failure, success


def create_paper_blueprint(paper_service, scan_callback):
    blueprint = Blueprint("paper_api", __name__)

    @blueprint.get("/api/paper/account")
    def account(): return success(paper_service.account())
    @blueprint.get("/api/paper/positions")
    def positions(): return success(paper_service.positions())
    @blueprint.get("/api/paper/orders")
    def orders(): return success(paper_service.orders())
    @blueprint.get("/api/paper/trades")
    def trades(): return success(paper_service.trades())

    @blueprint.post("/api/place_order")
    def place_order():
        payload = request.get_json(silent=True) or {}
        try:
            result = paper_service.place_order(str(payload.get("ticker", payload.get("symbol", ""))).strip(), str(payload.get("side", "BUY")), int(payload.get("quantity", 1)), payload.get("client_order_id"), payload.get("strategy_id"))
            return success(result, "Paper order filled.")
        except Exception as exc:
            log_event("error", "paper_routes", "order_failed", str(exc), payload); return failure(exc)

    @blueprint.post("/api/reset_session")
    def reset_session():
        payload = request.get_json(silent=True) or {}
        if payload.get("confirm") is not True: return failure("Explicit confirmation is required: {confirm: true}.")
        try: return success(paper_service.reset(), "Paper account reset.")
        except Exception as exc:
            log_event("error", "paper_routes", "reset_failed", str(exc)); return failure(exc)

    @blueprint.post("/api/run_exit_sweep")
    def exit_sweep():
        try: return success(paper_service.exit_sweep(), "Exit-only sweep complete.")
        except Exception as exc:
            log_event("error", "paper_routes", "exit_sweep_failed", str(exc)); return failure(exc)

    @blueprint.post("/api/run_scan")
    def run_scan():
        try: return success(scan_callback(), "Paper signal scan complete.")
        except Exception as exc:
            log_event("error", "paper_routes", "scan_failed", str(exc)); return failure(exc)
    return blueprint
