from __future__ import annotations

from app.core.logging_config import log_event
from app.db.database import get_database
from app.services.strategy_service import StrategyService


def bootstrap_application() -> dict:
    database = get_database()
    strategies = StrategyService(database)
    strategies.initialize()
    log_event("info", "bootstrap", "app_startup", "Stage 1 application foundation initialized")
    return {"database": database, "strategies": strategies}
