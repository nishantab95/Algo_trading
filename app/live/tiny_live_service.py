from __future__ import annotations

from typing import Any

from app.brokers.broker_errors import BrokerError
from app.brokers.broker_models import sanitize_broker_payload


class TinyLiveService:
    def __init__(self, broker_service, unlock_service, risk_manager, kill_switch_service) -> None:
        self.broker_service = broker_service
        self.unlock_service = unlock_service
        self.risk_manager = risk_manager
        self.kill_switch_service = kill_switch_service

    def status(self) -> dict[str, Any]:
        try:
            broker_status = self.broker_service.get_status()
        except BrokerError as exc:
            broker_status = {"mode": "unknown", "broker_connected": False, "error": str(exc)}
        return sanitize_broker_payload(
            {
                "mode": broker_status.get("mode"),
                "broker": broker_status,
                "unlock": self.unlock_service.status(),
                "kill_switch": self.kill_switch_service.status(),
                "limits": self.risk_manager.limits(),
                "live_orders_allowed": False,
                "can_submit_live_order": False,
                "preflight_only": True,
                "raw_phrase_stored": False,
            }
        )

    def unlock(self, phrase: str, actor: str = "user") -> dict[str, Any]:
        result = self.unlock_service.unlock(phrase, actor=actor)
        return {"unlock": result, "status": self.status()}

    def lock(self, actor: str = "user") -> dict[str, Any]:
        result = self.unlock_service.lock(actor=actor)
        return {"unlock": result, "status": self.status()}

    def limits(self) -> dict[str, Any]:
        return self.risk_manager.limits()

    def update_limits(self, changes: dict[str, Any], actor: str = "user") -> dict[str, Any]:
        return self.risk_manager.update_limits(changes, actor=actor)

    def preflight_order(self, payload: dict[str, Any], actor: str = "user") -> dict[str, Any]:
        return self.risk_manager.preflight_order(payload, actor=actor)
