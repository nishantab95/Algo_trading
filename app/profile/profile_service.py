from __future__ import annotations

import json
from datetime import datetime, timezone

from app.profile.preferences import SAFE_COST_MODELS,SAFE_EXECUTION_MODELS
from app.profile.risk_profile import validate_risk_profile
from app.profile.trading_profile import TradingProfile


FORBIDDEN_PROFILE_KEYS={"api_key","api_secret","access_token","broker_credentials","password"}


class TradingProfileService:
    def __init__(self,database) -> None: self.database=database; self._ensure_default()
    def _ensure_default(self):
        now=datetime.now(timezone.utc).isoformat(); profile=TradingProfile()
        with self.database.transaction() as c:
            c.execute("INSERT OR IGNORE INTO trading_profile(id,profile_name,config_json,created_at,updated_at) VALUES(1,?,?,?,?)",(profile.profile_name,json.dumps(profile.to_dict()),now,now))
    def get(self):
        row=self.database.query("SELECT * FROM trading_profile WHERE id=1")[0]; payload=json.loads(row["config_json"]); payload.update({"id":1,"updated_at":row["updated_at"]}); return payload
    def validate(self,changes:dict):
        errors=[]
        if FORBIDDEN_PROFILE_KEYS & {key.lower() for key in changes}: errors.append("Broker secrets are forbidden in the trading profile")
        merged={**self.get(),**changes}; errors.extend(validate_risk_profile(merged))
        if merged.get("default_execution_model") not in SAFE_EXECUTION_MODELS: errors.append("Unsupported default execution model")
        if merged.get("default_cost_model") not in SAFE_COST_MODELS: errors.append("Unsupported default cost model")
        return {"valid":not errors,"errors":errors,"warnings":[]}
    def apply(self,changes:dict):
        validation=self.validate(changes)
        if not validation["valid"]: raise ValueError("; ".join(validation["errors"]))
        merged={key:value for key,value in {**self.get(),**changes}.items() if key not in {"id","updated_at"}}
        now=datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as c: c.execute("UPDATE trading_profile SET profile_name=?,config_json=?,updated_at=? WHERE id=1",(merged["profile_name"],json.dumps(merged),now))
        return self.get()
