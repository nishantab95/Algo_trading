from __future__ import annotations

from flask import Blueprint, request

import data
from app.core.logging_config import log_event
from app.routes.common import failure, success


def create_data_blueprint(report_service):
    blueprint = Blueprint("data_api", __name__)

    @blueprint.post("/api/download_ticker")
    def download_ticker():
        try:
            ticker = str((request.get_json(silent=True) or {}).get("ticker", "")).strip()
            downloaded = data.download_custom_ticker(ticker)
            recalibration = report_service.recalibrate()
            return success({"download": downloaded, "recalibration": recalibration}, f"{ticker.upper()} imported and reports refreshed.")
        except Exception as exc:
            log_event("error", "data_routes", "download_failed", str(exc)); return failure(exc)

    @blueprint.post("/api/recalibrate")
    def recalibrate():
        try: return success(report_service.recalibrate(), "Recalibration complete.")
        except Exception as exc:
            log_event("error", "data_routes", "recalibration_failed", str(exc)); return failure(exc)
    return blueprint
