from __future__ import annotations

import json,uuid
from datetime import datetime,timezone

from app.dashboard_builder.schemas import validate_layout,validate_widget


class DashboardService:
    def __init__(self,database): self.database=database
    def list(self): return [self._decode(row) for row in self.database.query("SELECT * FROM dashboard_layouts ORDER BY updated_at DESC")]
    def get(self,layout_id):
        rows=self.database.query("SELECT * FROM dashboard_layouts WHERE layout_id=?",(layout_id,))
        if not rows: raise ValueError(f"Unknown dashboard: {layout_id}")
        item=self._decode(rows[0]); item["widgets"]=[self._widget(row) for row in self.database.query("SELECT * FROM dashboard_widgets WHERE layout_id=? ORDER BY id",(layout_id,))]; return item
    def save(self,payload):
        errors=validate_layout(payload)
        if errors: raise ValueError("; ".join(errors))
        layout_id=payload.get("layout_id") or "dashboard_"+uuid.uuid4().hex[:10]; now=datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as c: c.execute("""INSERT INTO dashboard_layouts(layout_id,name,description,layout_json,created_at,updated_at) VALUES(?,?,?,?,?,?)
            ON CONFLICT(layout_id) DO UPDATE SET name=excluded.name,description=excluded.description,layout_json=excluded.layout_json,updated_at=excluded.updated_at""",
            (layout_id,payload["name"],payload.get("description",""),json.dumps(payload.get("layout",{})),now,now))
        return self.get(layout_id)
    def delete(self,layout_id):
        self.get(layout_id)
        with self.database.transaction() as c: c.execute("DELETE FROM dashboard_layouts WHERE layout_id=?",(layout_id,))
        return {"layout_id":layout_id,"deleted":True}
    def add_widget(self,layout_id,payload):
        self.get(layout_id); errors=validate_widget(payload)
        if errors: raise ValueError("; ".join(errors))
        now=datetime.now(timezone.utc).isoformat(); kind=payload.get("type") or payload.get("widget_type")
        with self.database.transaction() as c: c.execute("""INSERT INTO dashboard_widgets(layout_id,widget_id,widget_type,title,config_json,position_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(layout_id,widget_id) DO UPDATE SET widget_type=excluded.widget_type,title=excluded.title,config_json=excluded.config_json,position_json=excluded.position_json,updated_at=excluded.updated_at""",
            (layout_id,payload["widget_id"],kind,payload.get("title",kind.replace("_"," ").title()),json.dumps(payload.get("config",{})),json.dumps(payload.get("position",{})),now,now))
        return self.get(layout_id)
    def remove_widget(self,layout_id,widget_id):
        with self.database.transaction() as c: c.execute("DELETE FROM dashboard_widgets WHERE layout_id=? AND widget_id=?",(layout_id,widget_id))
        return self.get(layout_id)
    def _decode(self,row): row=dict(row); row["layout"]=json.loads(row.pop("layout_json")); return row
    def _widget(self,row): row=dict(row); row["config"]=json.loads(row.pop("config_json")); row["position"]=json.loads(row.pop("position_json")); row["type"]=row.pop("widget_type"); return row
