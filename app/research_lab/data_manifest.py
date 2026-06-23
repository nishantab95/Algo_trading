from __future__ import annotations

import json,uuid
from datetime import datetime,timezone
from app.research_lab.validation import content_hash,validate_market_data


def build_manifest(experiment_id,data,config,data_source="local_processed_csv",code_version="stage6"):
    result=validate_market_data(data,config.get("symbols",[]),config.get("validation_config",{}).get("min_rows",50),config.get("validation_config",{}).get("stale_days",30));now=datetime.now(timezone.utc).isoformat();dates=data["Date"] if "Date" in data else []
    return {"id":"manifest_"+uuid.uuid4().hex,"experiment_id":experiment_id,"data_source":data_source,"symbols":config.get("symbols",[]),"symbol_count":len(config.get("symbols",[])),"date_start":str(dates.min().date()) if len(dates) else None,"date_end":str(dates.max().date()) if len(dates) else None,"rows_per_symbol":result["rows_per_symbol"],"missing_dates":result["missing_dates"],"skipped_symbols":result["skipped_symbols"],"stale_symbols":result["stale_symbols"],"data_hash":content_hash(data),"code_version":code_version,"config_hash":content_hash(config),"warnings":result["warnings"],"created_at":now}
