from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.getenv("ALGO_DATA_ROOT", PROJECT_ROOT / "data"))
RAW_DATA_ROOT = Path(os.getenv("ALGO_RAW_DATA_ROOT", DATA_ROOT / "raw"))
REPORTS_ROOT = Path(os.getenv("ALGO_REPORTS_ROOT", PROJECT_ROOT / "reports"))
DATABASE_PATH = Path(os.getenv("ALGO_DATABASE_PATH", DATA_ROOT / "app_state.sqlite3"))
LOG_PATH = Path(os.getenv("ALGO_LOG_PATH", PROJECT_ROOT / "logs" / "app.log"))


def ensure_runtime_paths() -> None:
    for path in (DATA_ROOT, RAW_DATA_ROOT, REPORTS_ROOT, DATABASE_PATH.parent, LOG_PATH.parent):
        path.mkdir(parents=True, exist_ok=True)
