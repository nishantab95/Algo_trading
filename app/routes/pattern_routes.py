from __future__ import annotations

from flask import Blueprint, request

from app.patterns.registry import REGISTRY_VERSION
from app.routes.common import failure, success


def create_pattern_blueprint(scanner):
    blueprint = Blueprint("pattern_api", __name__)

    @blueprint.get("/api/discovery/patterns")
    def patterns():
        return success({"registry_version": REGISTRY_VERSION, "patterns": scanner.registry()})

    @blueprint.post("/api/discovery/scan")
    def scan():
        payload = request.get_json(silent=True) or {}
        try:
            return success(scanner.scan(str(payload.get("universe", "nse")).lower(), payload.get("patterns"), payload.get("config")))
        except Exception as exc:
            return failure(exc)

    @blueprint.get("/api/discovery/scans/<scan_id>")
    def scan_detail(scan_id: str):
        scan = scanner.get_scan(scan_id)
        return success(scan) if scan else failure("Unknown scan execution.", 404)

    @blueprint.post("/api/discovery/historical-pattern-review")
    def historical_pattern_review():
        payload = request.get_json(silent=True) or {}
        try:
            symbols = payload.get("symbols")
            if symbols is not None and (not isinstance(symbols, list) or not all(isinstance(item, str) for item in symbols)):
                raise ValueError("symbols must be a list of canonical exchange-qualified symbols.")
            return success(scanner.historical_review(
                str(payload.get("universe", "nse")).lower(), payload.get("patterns"), payload.get("config"), symbols,
            ))
        except Exception as exc:
            return failure(exc)

    @blueprint.get("/api/discovery/historical-pattern-reviews/<review_id>")
    def historical_pattern_review_detail(review_id: str):
        review = scanner.get_historical_review(review_id)
        return success(review) if review else failure("Unknown historical pattern review.", 404)

    return blueprint
