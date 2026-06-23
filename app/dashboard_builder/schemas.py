from __future__ import annotations

import re

from app.dashboard_builder.widgets import ALLOWED_WIDGETS


def validate_layout(payload:dict)->list[str]:
    errors=[]
    if not payload.get("name"): errors.append("Dashboard name is required")
    if payload.get("layout_id") and not re.fullmatch(r"[A-Za-z0-9_-]+",str(payload["layout_id"])): errors.append("Invalid layout_id")
    return errors

def validate_widget(payload:dict)->list[str]:
    errors=[]; kind=payload.get("type") or payload.get("widget_type")
    if kind not in ALLOWED_WIDGETS: errors.append(f"Unsupported widget type: {kind}")
    if not payload.get("widget_id"): errors.append("widget_id is required")
    return errors
