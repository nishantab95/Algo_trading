from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

import config_settings as cfg
import preprocessing
import report
from app.core.logging_config import log_event
from app.db.database import Database, get_database


class ReportService:
    def __init__(self, database: Database | None = None) -> None: self.database = database or get_database()

    def recalibrate(self) -> dict:
        started = datetime.now(timezone.utc).isoformat()
        master = preprocessing.consolidate_universe()
        if master.empty: raise RuntimeError("No local ticker data was available for recalibration.")
        summary = report.generate_performance_report()
        if summary.empty: raise RuntimeError("Performance report generation returned no rows.")
        tickers = sorted(master["Ticker"].dropna().unique())
        dates = master["Date"]
        try: code_version = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=cfg.PROJECT_ROOT, text=True).strip()
        except Exception: code_version = "unknown"
        with self.database.transaction() as connection:
            connection.execute("INSERT INTO pipeline_manifests(run_type,source_data_path,ticker_count,earliest_date,latest_date,skipped_tickers_json,report_generated_at,code_version,status,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", ("recalibration",cfg.DATA_DIR,len(tickers),str(dates.min()),str(dates.max()),json.dumps([]),datetime.now(timezone.utc).isoformat(),code_version,"success","Stage 1 full rebuild",started))
        log_event("info", "report_service", "recalibration_complete", "Reports recalibrated", {"tickers": len(tickers), "strategies": len(summary)})
        return {"tickers": len(tickers), "strategies": len(summary), "report_path": cfg.STRATEGY_REPORT_FILE}
