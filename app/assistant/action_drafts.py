from __future__ import annotations

import json,uuid
from datetime import datetime,timezone


class ActionDraftService:
    def __init__(self,database,handlers:dict|None=None): self.database=database; self.handlers=handlers or {}
    def create(self,action_type:str,payload:dict,conversation_id:str|None=None,validation:dict|None=None,risk_check:dict|None=None):
        draft_id="draft_"+uuid.uuid4().hex; now=datetime.now(timezone.utc).isoformat(); validation=validation or {"valid":True,"errors":[],"warnings":[]}; risk_check=risk_check or {"approved":True,"reason":"Not applicable or checked at execution"}
        with self.database.transaction() as c: c.execute("INSERT INTO assistant_action_drafts(id,conversation_id,action_type,status,draft_json,validation_json,risk_check_json,approval_required,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(draft_id,conversation_id,action_type,"pending",json.dumps(payload),json.dumps(validation),json.dumps(risk_check),1,now))
        return self.get(draft_id)
    def get(self,draft_id):
        rows=self.database.query("SELECT * FROM assistant_action_drafts WHERE id=?",(draft_id,))
        if not rows: raise ValueError(f"Unknown action draft: {draft_id}")
        row=dict(rows[0]); row["draft"]=json.loads(row.pop("draft_json")); row["validation"]=json.loads(row.pop("validation_json")); row["risk_check"]=json.loads(row.pop("risk_check_json")); row["approval_required"]=bool(row["approval_required"]); return row
    def approve(self,draft_id,actor="user"):
        if actor!="user": raise PermissionError("Only the user can approve assistant actions")
        draft=self.get(draft_id)
        if draft["status"]!="pending": raise ValueError(f"Draft is already {draft['status']}")
        if not draft["validation"].get("valid",False): raise ValueError("Draft validation failed")
        if not draft["risk_check"].get("approved",False): raise PermissionError("Draft risk check failed")
        handler=self.handlers.get(draft["action_type"])
        if handler is None: raise ValueError(f"No approved executor for {draft['action_type']}")
        result=handler(draft["draft"]); now=datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as c: c.execute("UPDATE assistant_action_drafts SET status='executed',approved_at=?,executed_at=? WHERE id=?",(now,now,draft_id))
        return {"draft":self.get(draft_id),"result":result}
    def reject(self,draft_id,actor="user"):
        if actor!="user": raise PermissionError("Only the user can reject assistant actions")
        draft=self.get(draft_id)
        if draft["status"]!="pending": raise ValueError(f"Draft is already {draft['status']}")
        now=datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as c: c.execute("UPDATE assistant_action_drafts SET status='rejected',rejected_at=? WHERE id=?",(now,draft_id))
        return self.get(draft_id)
