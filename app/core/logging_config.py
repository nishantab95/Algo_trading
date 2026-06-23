from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.paths import LOG_PATH, ensure_runtime_paths
from app.db.database import get_database


def configure_logging() -> logging.Logger:
    ensure_runtime_paths()
    logger = logging.getLogger("algo_terminal")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    return logger


LOGGER = configure_logging()


def log_event(level: str, source: str, event_type: str, message: str, context: dict[str, Any] | None = None) -> None:
    payload = context or {}
    getattr(LOGGER, level.lower(), LOGGER.info)("%s %s %s", source, event_type, json.dumps(payload, default=str))
    database = get_database()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO system_logs(level, source, event_type, message, context_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (level.upper(), source, event_type, message, json.dumps(payload, default=str), datetime.now(timezone.utc).isoformat()),
        )
