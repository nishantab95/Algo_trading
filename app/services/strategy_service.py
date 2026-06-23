from __future__ import annotations

import json
from datetime import datetime, timezone

import config_settings as cfg
import preprocessing
from app.core.logging_config import log_event
from app.db.database import Database, get_database
from app.strategies.registry import StrategyRegistry


INDICATOR_NAMES = {
    "Open", "High", "Low", "Close", "Volume", "SMA_20", "SMA_50", "EMA_9", "EMA_21",
    "EMA_50", "EMA_200", "RSI_14", "MACD", "MACD_Signal", "MACD_Hist", "Stochastic_%K",
    "Stochastic_%D", "ATR_14", "Bollinger_Upper", "Bollinger_Middle", "Bollinger_Lower",
    "Bollinger_Width", "Volume_SMA_20", "Volume_Z_Score", "np", "abs", "round", "df",
}


class CustomStrategyService:
    def __init__(self, database: Database | None = None) -> None:
        self.database = database or get_database()

    def validate(self, expression: str) -> tuple[bool, str | None]:
        try:
            preprocessing._validate_strategy_ast(expression, INDICATOR_NAMES)
            return True, None
        except Exception as exc:
            return False, str(exc)

    def save(self, name: str, expression: str, description: str = "") -> dict:
        clean = preprocessing._sanitize_strategy_name(name)
        valid, error = self.validate(expression)
        now = datetime.now(timezone.utc).isoformat()
        status = "valid" if valid else "invalid"
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO custom_strategies(strategy_id,name,expression,description,enabled,validation_status,validation_error,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(strategy_id) DO UPDATE SET expression=excluded.expression,
                   description=excluded.description,enabled=excluded.enabled,validation_status=excluded.validation_status,
                   validation_error=excluded.validation_error,updated_at=excluded.updated_at""",
                (clean, clean, expression, description, int(valid), status, error, now, now),
            )
        if valid:
            cfg.add_custom_strategy(clean, expression)
        log_event("info" if valid else "warning", "strategy_service", "custom_strategy_validation", f"Custom strategy {clean} is {status}", {"error": error})
        return self.get(clean)

    def get(self, strategy_id: str) -> dict:
        rows = self.database.query("SELECT * FROM custom_strategies WHERE strategy_id=?", (strategy_id,))
        if not rows:
            raise ValueError(f"Unknown custom strategy: {strategy_id}")
        row = rows[0]; row["enabled"] = bool(row["enabled"]); return row

    def list(self) -> list[dict]:
        rows = self.database.query("SELECT * FROM custom_strategies ORDER BY updated_at DESC")
        for row in rows: row["enabled"] = bool(row["enabled"])
        return rows

    def set_enabled(self, strategy_id: str, enabled: bool) -> dict:
        item = self.get(strategy_id)
        if enabled and item["validation_status"] != "valid":
            raise ValueError("Invalid custom strategy cannot be enabled.")
        with self.database.transaction() as connection:
            connection.execute("UPDATE custom_strategies SET enabled=?,updated_at=? WHERE strategy_id=?", (int(enabled), datetime.now(timezone.utc).isoformat(), strategy_id))
        if enabled: cfg.add_custom_strategy(item["name"], item["expression"])
        else:
            cfg.CUSTOM_STRATEGIES.pop(item["name"], None)
            cfg.ACTIVE_STRATEGIES.discard(item["name"])
        return self.get(strategy_id)

    def reload(self) -> int:
        cfg.CUSTOM_STRATEGIES.clear()
        count = 0
        for item in self.list():
            if item["enabled"] and item["validation_status"] == "valid":
                cfg.add_custom_strategy(item["name"], item["expression"]); count += 1
        return count


class StrategyService:
    def __init__(self, database: Database | None = None) -> None:
        self.database = database or get_database()
        self.registry = StrategyRegistry(self.database)
        self.custom = CustomStrategyService(self.database)

    def initialize(self) -> None:
        self.registry.load_builtins()
        loaded = self.custom.reload()
        log_event("info", "strategy_service", "registry_loaded", "Strategy registry loaded", {"builtins": 15, "custom": loaded})

    def list_all(self) -> list[dict]:
        return self.registry.list()
