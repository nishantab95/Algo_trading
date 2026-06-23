from __future__ import annotations

from flask import Blueprint,request
from app.dashboard_builder.schemas import validate_layout,validate_widget
from app.routes.common import failure,success


def create_dashboard_builder_blueprint(dashboards,drafts):
    bp=Blueprint("dashboard_builder_api",__name__)
    @bp.get("/api/dashboards")
    def list_dashboards(): return success(dashboards.list())
    @bp.post("/api/dashboards")
    def create():
        payload=request.get_json(silent=True) or {}; errors=validate_layout(payload)
        return success(drafts.create("save_dashboard_layout",payload,validation={"valid":not errors,"errors":errors,"warnings":[]}),status=201)
    @bp.get("/api/dashboards/<layout_id>")
    def detail(layout_id):
        try:return success(dashboards.get(layout_id))
        except Exception as exc:return failure(exc,404)
    @bp.put("/api/dashboards/<layout_id>")
    def update(layout_id):
        payload={**(request.get_json(silent=True) or {}),"layout_id":layout_id}; errors=validate_layout(payload)
        return success(drafts.create("save_dashboard_layout",payload,validation={"valid":not errors,"errors":errors,"warnings":[]}))
    @bp.delete("/api/dashboards/<layout_id>")
    def delete(layout_id): return success(drafts.create("delete_dashboard_layout",{"layout_id":layout_id}))
    @bp.post("/api/dashboards/<layout_id>/widgets")
    def add_widget(layout_id):
        payload={**(request.get_json(silent=True) or {}),"layout_id":layout_id}; errors=validate_widget(payload)
        return success(drafts.create("add_dashboard_widget",payload,validation={"valid":not errors,"errors":errors,"warnings":[]}),status=201)
    @bp.delete("/api/dashboards/<layout_id>/widgets/<widget_id>")
    def remove_widget(layout_id,widget_id): return success(drafts.create("remove_dashboard_widget",{"layout_id":layout_id,"widget_id":widget_id}))
    return bp
