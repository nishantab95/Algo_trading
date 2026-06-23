from __future__ import annotations

import json,uuid
from datetime import datetime,timezone
from app.research_lab.schemas import ExperimentConfig


def now():return datetime.now(timezone.utc).isoformat()

class ResearchExperimentService:
    def __init__(self,database):self.database=database
    def create(self,payload):
        config=ExperimentConfig(**payload);identifier="exp_"+uuid.uuid4().hex;stamp=now();d=config.to_dict()
        if not (d["strategy_id"] or d["combo_id"]):raise ValueError("strategy_id or combo_id is required")
        if not d["symbols"]:raise ValueError("At least one symbol is required")
        with self.database.transaction() as c:c.execute("""INSERT INTO research_experiments(id,name,description,strategy_id,combo_id,universe,symbols_json,start_date,end_date,train_start,train_end,test_start,test_end,execution_model,cost_model,slippage_bps,spread_bps,fees_enabled,initial_capital,max_positions,sizing_model,risk_settings_json,parameter_grid_json,validation_config_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(identifier,d["name"],d["description"],d["strategy_id"],d["combo_id"],d["universe"],json.dumps(d["symbols"]),d["start_date"],d["end_date"],d["train_start"],d["train_end"],d["test_start"],d["test_end"],d["execution_model"],d["cost_model"],d["slippage_bps"],d["spread_bps"],int(d["fees_enabled"]),d["initial_capital"],d["max_positions"],d["sizing_model"],json.dumps(d["risk_settings"]),json.dumps(d["parameter_grid"]),json.dumps(d["validation_config"]),"draft",stamp,stamp))
        return self.get(identifier)
    def list(self):return [self._decode(r) for r in self.database.query("SELECT * FROM research_experiments ORDER BY created_at DESC")]
    def get(self,identifier):
        rows=self.database.query("SELECT * FROM research_experiments WHERE id=?",(identifier,))
        if not rows:raise ValueError("Unknown research experiment")
        item=self._decode(rows[0]);summary=self.database.query("SELECT * FROM research_validation_summaries WHERE experiment_id=?",(identifier,));item["summary"]=json.loads(summary[0]["summary_json"]) if summary else None;return item
    def set_status(self,identifier,status):
        with self.database.transaction() as c:c.execute("UPDATE research_experiments SET status=?,updated_at=? WHERE id=?",(status,now(),identifier))
        return self.get(identifier)
    def cancel(self,identifier):
        current=self.get(identifier)
        if current["status"] in {"completed","archived"}:raise ValueError("Completed experiments are immutable; archive instead")
        return self.set_status(identifier,"cancelled")
    def _decode(self,row):
        row=dict(row)
        for key in ("symbols_json","risk_settings_json","parameter_grid_json","validation_config_json"):row[key.removesuffix("_json")]=json.loads(row.pop(key) or ("[]" if key=="symbols_json" else "{}"))
        row["fees_enabled"]=bool(row["fees_enabled"]);return row

class ResearchDecisionService:
    def __init__(self,database):self.database=database
    def draft(self,experiment,recommendation,score):
        identifier="decision_"+uuid.uuid4().hex;stamp=now()
        with self.database.transaction() as c:c.execute("INSERT INTO research_decisions(id,experiment_id,strategy_id,combo_id,decision,evidence_score,decision_reason,warnings_json,approved_by_user,status,created_at) VALUES(?,?,?,?,?,?,?,?,0,'pending',?)",(identifier,experiment["id"],experiment.get("strategy_id"),experiment.get("combo_id"),recommendation["decision"],score,recommendation["reason"],json.dumps(recommendation.get("warnings",[])),stamp))
        return self.get(identifier)
    def get(self,identifier):
        rows=self.database.query("SELECT * FROM research_decisions WHERE id=?",(identifier,))
        if not rows:raise ValueError("Unknown research decision")
        row=rows[0];row["warnings"]=json.loads(row.pop("warnings_json"));row["approved_by_user"]=bool(row["approved_by_user"]);return row
    def approve(self,identifier,actor="user"):
        if actor!="user":raise PermissionError("Only the user can approve a research decision")
        d=self.get(identifier)
        if d["status"]!="pending":raise ValueError("Decision is not pending")
        with self.database.transaction() as c:c.execute("UPDATE research_decisions SET approved_by_user=1,status='approved',approved_at=? WHERE id=?",(now(),identifier))
        return self.get(identifier)
    def reject(self,identifier,actor="user"):
        if actor!="user":raise PermissionError("Only the user can reject a research decision")
        with self.database.transaction() as c:c.execute("UPDATE research_decisions SET status='rejected',rejected_at=? WHERE id=? AND status='pending'",(now(),identifier))
        return self.get(identifier)
