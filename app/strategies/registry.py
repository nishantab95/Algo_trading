from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db.database import Database, get_database
from app.strategies.legacy_builtin import BUILTIN_STRATEGIES


class StrategyRegistry:
    def __init__(self, database: Database | None = None) -> None:
        self.database = database or get_database()

    def load_builtins(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as connection:
            for strategy in BUILTIN_STRATEGIES:
                config = strategy.to_dict()
                connection.execute(
                    """INSERT INTO strategy_registry(strategy_id,name,category,direction,timeframe,enabled,status,description,config_json,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(strategy_id) DO UPDATE SET category=excluded.category,direction=excluded.direction,
                       timeframe=excluded.timeframe,description=excluded.description,config_json=excluded.config_json,updated_at=excluded.updated_at""",
                    (strategy.strategy_id, strategy.name, strategy.category, strategy.direction, strategy.timeframe,
                     int(strategy.enabled), strategy.status, strategy.description, json.dumps(config), now, now),
                )

    def list(self) -> list[dict]:
        rows = self.database.query("SELECT * FROM strategy_registry ORDER BY category, name")
        for row in rows:
            row["enabled"] = bool(row["enabled"])
            row["config"] = json.loads(row.pop("config_json") or "{}")
        return rows

    def set_enabled(self, strategy_id: str, enabled: bool) -> None:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE strategy_registry SET enabled=?, updated_at=? WHERE strategy_id=?",
                (int(enabled), datetime.now(timezone.utc).isoformat(), strategy_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Unknown strategy: {strategy_id}")
