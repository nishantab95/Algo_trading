from __future__ import annotations
import json,uuid
from app.strategies.combos.combo_registry import ComboRegistry
from app.strategies.combos.combo_validator import validate_combo

class ComboStrategyService:
    def __init__(self,database,library,backtest_service): self.database=database; self.registry=ComboRegistry(database); self.library=library; self.backtest_service=backtest_service
    def initialize(self): self.registry.load_catalog()
    def _decode(self,row):
        row=dict(row); row["enabled"]=bool(row["enabled"])
        for field in ("logic","components","entry","exit","risk","tags"): row[field]=json.loads(row.pop(field+"_json"))
        return row
    def list(self): return [self._decode(row) for row in self.registry.list()]
    def get(self,combo_id): return self._decode(self.registry.get(combo_id))
    def save(self,payload,allow_existing=False):
        supplied_id=payload.get("combo_id")
        if not supplied_id: payload["combo_id"]="CUSTOM_COMBO_"+uuid.uuid4().hex[:10].upper()
        elif not allow_existing:
            try: self.registry.get(supplied_id)
            except ValueError: pass
            else: raise ValueError(f"Duplicate combo ID: {supplied_id}")
        validation=self.validate_payload(payload)
        if validation["errors"]: raise ValueError("; ".join(validation["errors"]))
        payload["status"]=validation["status"]; return self._decode(self.registry.save(payload))
    def update(self,combo_id,payload): payload={**self.get(combo_id),**payload,"combo_id":combo_id}; return self.save(payload,allow_existing=True)
    def validate_payload(self,payload): return validate_combo(payload,{item["strategy_id"] for item in self.library.list()})
    def validate(self,combo_id): return self.validate_payload(self.get(combo_id))
    def duplicate(self,combo_id):
        item=self.get(combo_id); item["combo_id"]="CUSTOM_COMBO_"+uuid.uuid4().hex[:10].upper(); item["name"]+=" Copy"; item["enabled"]=False; return self.save(item)
    def toggle(self,combo_id,enabled):
        item=self.get(combo_id)
        if enabled and item["status"]!="active": raise ValueError(f"Cannot enable combo with status {item['status']}")
        return self._decode(self.registry.toggle(combo_id,enabled))
