from __future__ import annotations

from flask import jsonify


def success(data=None, message: str | None = None, status: int = 200, warnings=None):
    # `ok` and named aliases preserve compatibility while the UI migrates to
    # the mandatory Stage 1 success/data/error envelope.
    payload = {"success": True, "ok": True, "data": data, "warnings": list(warnings or []), "summary": data, "order": data, "session": data, "reports": data, "strategy": data}
    if message: payload["message"] = message
    return jsonify(payload), status


def failure(error: Exception | str, status: int = 400, details=None):
    return jsonify({"success": False, "ok": False, "error": str(error), "details": details or {}}), status
