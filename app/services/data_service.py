from __future__ import annotations

import os
from datetime import date

import pandas as pd

import config_settings as cfg


class DataService:
    def freshness(self) -> dict:
        latest = None
        files = []
        if os.path.isdir(cfg.DATA_DIR):
            files = [os.path.join(cfg.DATA_DIR, name) for name in os.listdir(cfg.DATA_DIR) if name.lower().endswith(".csv")]
        for path in files:
            try:
                frame = pd.read_csv(path, index_col=0, parse_dates=True, usecols=[0])
                candidate = pd.Timestamp(frame.index.max()).date()
                latest = candidate if latest is None or candidate > latest else latest
            except Exception:
                continue
        if latest is None:
            return {"status": "unknown", "latest_date": None, "age_days": None, "ticker_files": len(files)}
        age = (date.today() - latest).days
        return {"status": "fresh" if age <= 4 else "stale", "latest_date": latest.isoformat(), "age_days": age, "ticker_files": len(files)}

    def reports_stale(self) -> bool:
        if not os.path.exists(cfg.STRATEGY_REPORT_FILE): return True
        report_mtime = os.path.getmtime(cfg.STRATEGY_REPORT_FILE)
        raw_mtimes = [os.path.getmtime(os.path.join(cfg.DATA_DIR, n)) for n in os.listdir(cfg.DATA_DIR)] if os.path.isdir(cfg.DATA_DIR) else []
        return bool(raw_mtimes and max(raw_mtimes) > report_mtime)
