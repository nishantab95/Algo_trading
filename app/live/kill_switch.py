from __future__ import annotations

from typing import Any
import uuid

from app.brokers.broker_errors import BrokerPermissionError
from app.db.database import Database, get_database
from app.live.unlock import iso_now

KILL_SWITCH_ARMED = "armed"
KILL_SWITCH_TRIGGERED = "triggered"
KILL_SWITCH_DISABLED_FOR_LIVE_USE = "disabled_for_live_use"


class KillSwitchService:
    def __init__(self, database: Database | None = None) -> None:
        self.database = database or get_database()

    def _record(self, state: str, reason: str = "", actor: str = "system") -> dict[str, Any]:
        switch_id = "ks_" + uuid.uuid4().hex[:12]
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO live_kill_switch(switch_id, state, reason, actor, created_at) VALUES(?,?,?,?,?)",
                (switch_id, state, reason, actor, iso_now()),
            )
        return {"switch_id": switch_id, "state": state, "reason": reason, "actor": actor}

    def latest(self) -> dict[str, Any]:
        rows = self.database.query("SELECT * FROM live_kill_switch ORDER BY id DESC LIMIT 1")
        if not rows:
            return self._record(KILL_SWITCH_ARMED, "default_armed", "system")
        row = rows[0]
        return {"switch_id": row["switch_id"], "state": row["state"], "reason": row["reason"], "actor": row["actor"], "created_at": row["created_at"]}

    def status(self) -> dict[str, Any]:
        latest = self.latest()
        return {**latest, "armed": latest["state"] == KILL_SWITCH_ARMED, "triggered": latest["state"] == KILL_SWITCH_TRIGGERED, "blocks_live_actions": latest["state"] != KILL_SWITCH_ARMED}

    def trigger(self, reason: str = "manual_trigger", actor: str = "user") -> dict[str, Any]:
        if str(actor or "user").strip().lower() == "assistant":
            raise BrokerPermissionError("Assistant cannot trigger or manage the live kill switch.")
        self._record(KILL_SWITCH_TRIGGERED, str(reason or "manual_trigger"), str(actor or "user"))
        return self.status()

    def deactivate(self, confirm: bool = False, actor: str = "user") -> dict[str, Any]:
        actor_clean = str(actor or "user").strip().lower()
        if actor_clean == "assistant":
            raise BrokerPermissionError("Assistant cannot deactivate the live kill switch.")
        if confirm is not True:
            raise BrokerPermissionError("Kill switch deactivation requires explicit confirmation.")
        self._record(KILL_SWITCH_DISABLED_FOR_LIVE_USE, "deactivation_requested_but_live_use_disabled", actor_clean)
        return self.status()

    def arm(self, actor: str = "user") -> dict[str, Any]:
        self._record(KILL_SWITCH_ARMED, "armed", str(actor or "user"))
        return self.status()

