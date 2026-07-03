from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.brokers.broker_errors import BrokerPermissionError
from app.db.database import Database, get_database

DEFAULT_UNLOCK_TIMEOUT_SECONDS = 600


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def _hash_phrase(phrase: str) -> str:
    return hashlib.sha256(phrase.encode("utf-8")).hexdigest()


class TinyLiveUnlockService:
    def __init__(self, database: Database | None = None, expected_phrase: str | None = None, timeout_seconds: int = DEFAULT_UNLOCK_TIMEOUT_SECONDS) -> None:
        self.database = database or get_database()
        self.expected_phrase = expected_phrase if expected_phrase is not None else os.getenv("ALGO_TINY_LIVE_UNLOCK_PHRASE")
        self.timeout_seconds = int(timeout_seconds)
        self._active_unlock_id: str | None = None
        self._active_expires_at: datetime | None = None

    def _record(self, unlock_id: str, actor: str, status: str, phrase_hash: str | None = None, failure_reason: str | None = None, expires_at: str | None = None, locked_at: str | None = None) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO tiny_live_unlocks(unlock_id, actor, status, phrase_hash, failure_reason, expires_at, locked_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (unlock_id, actor, status, phrase_hash, failure_reason, expires_at, locked_at, iso_now()),
            )

    def is_unlocked(self) -> bool:
        if self._active_unlock_id is None or self._active_expires_at is None:
            return False
        if utc_now() >= self._active_expires_at:
            self._active_unlock_id = None
            self._active_expires_at = None
            return False
        return True

    def status(self) -> dict[str, Any]:
        active = self.is_unlocked()
        return {
            "locked": not active,
            "unlocked": active,
            "unlock_id": self._active_unlock_id if active else None,
            "expires_at": self._active_expires_at.isoformat() if active and self._active_expires_at else None,
            "timeout_seconds": self.timeout_seconds,
            "phrase_configured": bool(self.expected_phrase),
            "raw_phrase_stored": False,
        }

    def unlock(self, phrase: str, actor: str = "user") -> dict[str, Any]:
        actor_clean = str(actor or "user").strip().lower()
        unlock_id = "unlock_" + uuid.uuid4().hex[:12]
        phrase_text = str(phrase or "")
        if actor_clean == "assistant":
            self._record(unlock_id, actor_clean, "failed", failure_reason="assistant_actor_forbidden")
            raise BrokerPermissionError("Assistant cannot unlock tiny_live.")
        if not self.expected_phrase:
            self._record(unlock_id, actor_clean, "failed", phrase_hash=_hash_phrase(phrase_text), failure_reason="unlock_phrase_not_configured")
            raise BrokerPermissionError("Tiny-live unlock phrase is not configured for this process.")
        if not hmac.compare_digest(phrase_text, self.expected_phrase):
            self._record(unlock_id, actor_clean, "failed", phrase_hash=_hash_phrase(phrase_text), failure_reason="phrase_mismatch")
            raise BrokerPermissionError("Tiny-live unlock phrase did not match exactly.")
        expires_at = utc_now() + timedelta(seconds=self.timeout_seconds)
        self._active_unlock_id = unlock_id
        self._active_expires_at = expires_at
        self._record(unlock_id, actor_clean, "unlocked", phrase_hash=_hash_phrase(phrase_text), expires_at=expires_at.isoformat())
        return self.status()

    def lock(self, actor: str = "user") -> dict[str, Any]:
        actor_clean = str(actor or "user").strip().lower()
        lock_id = "lock_" + uuid.uuid4().hex[:12]
        self._active_unlock_id = None
        self._active_expires_at = None
        self._record(lock_id, actor_clean, "locked", locked_at=iso_now())
        return self.status()

