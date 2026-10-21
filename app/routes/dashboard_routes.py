from __future__ import annotations

from flask import Blueprint, render_template

from app.routes.common import success


def create_dashboard_blueprint(state_provider, template_name: str = "index.html"):
    blueprint = Blueprint("dashboard", __name__)

    @blueprint.get("/")
    def index():
        import json
        return render_template(template_name, initial_state=json.dumps(state_provider()))

    @blueprint.get("/api/state")
    def state(): return success(state_provider())
    return blueprint
