from __future__ import annotations

from typing import Any

from app.brokers.broker_models import sanitize_broker_payload


class BrokerSafetyTools:
    def __init__(self, broker_service=None, reconciliation_service=None, readiness_service=None, tiny_live_service=None, shadow_live_service=None, kill_switch_service=None) -> None:
        self.broker_service = broker_service
        self.reconciliation_service = reconciliation_service
        self.readiness_service = readiness_service
        self.tiny_live_service = tiny_live_service
        self.shadow_live_service = shadow_live_service
        self.kill_switch_service = kill_switch_service

    def broker_status(self) -> dict[str, Any]:
        if self.broker_service is None:
            return {"available": False, "message": "Broker service is unavailable."}
        return sanitize_broker_payload(self.broker_service.get_status())

    def latest_reconciliation(self) -> dict[str, Any] | None:
        if self.reconciliation_service is None:
            return None
        return sanitize_broker_payload(self.reconciliation_service.get_latest_reconciliation())

    def live_readiness(self) -> dict[str, Any]:
        if self.readiness_service is None:
            return {"overall_status": "not_checked", "critical_failures": ["readiness_service_unavailable"]}
        latest = self.readiness_service.latest_run()
        return sanitize_broker_payload(latest or {"overall_status": "not_checked", "critical_failures": [], "warnings": ["No readiness run has been recorded yet."]})

    def tiny_live_status(self) -> dict[str, Any]:
        if self.tiny_live_service is None:
            return {"available": False, "locked": True, "message": "Tiny-live service is unavailable."}
        return sanitize_broker_payload(self.tiny_live_service.status())

    def shadow_live_report(self) -> dict[str, Any]:
        if self.shadow_live_service is None:
            return {"total_events": 0, "blocked_count": 0, "events": [], "message": "Shadow-live service is unavailable."}
        return sanitize_broker_payload(self.shadow_live_service.report())

    def explain_tiny_live_blockers(self) -> dict[str, Any]:
        status = self.tiny_live_status()
        readiness = self.live_readiness()
        reconciliation = self.latest_reconciliation()
        blockers: list[str] = []
        unlock = status.get("unlock", {}) if isinstance(status, dict) else {}
        kill = status.get("kill_switch", {}) if isinstance(status, dict) else {}
        broker = status.get("broker", {}) if isinstance(status, dict) else {}
        if unlock.get("locked", True):
            blockers.append("tiny_live_locked")
        if not unlock.get("phrase_configured", False):
            blockers.append("unlock_phrase_not_configured")
        if kill.get("blocks_live_actions"):
            blockers.append("kill_switch_blocks_live_actions")
        if broker.get("mode") != "tiny_live":
            blockers.append("broker_mode_not_tiny_live")
        if not broker.get("broker_connected", False):
            blockers.append("broker_not_connected")
        if not reconciliation or reconciliation.get("mode") != "tiny_live" or reconciliation.get("status") != "passed":
            blockers.append("tiny_live_reconciliation_not_passing")
        if readiness.get("overall_status") in {"failed", "not_checked"} or readiness.get("critical_failures"):
            blockers.append("live_readiness_not_passing")
        blockers.append("live_order_submission_disabled_by_policy")
        return sanitize_broker_payload(
            {
                "blocked": True,
                "blockers": sorted(set(blockers)),
                "live_orders_allowed": False,
                "preflight_only": True,
                "status": status,
                "readiness": readiness,
                "reconciliation": reconciliation,
            }
        )

    def execute(self, name: str, args: dict[str, Any] | None = None) -> Any:
        mapping = {
            "get_broker_status": self.broker_status,
            "get_broker_reconciliation_latest": self.latest_reconciliation,
            "get_live_readiness": self.live_readiness,
            "get_tiny_live_status": self.tiny_live_status,
            "get_shadow_live_report": self.shadow_live_report,
            "explain_tiny_live_blockers": self.explain_tiny_live_blockers,
        }
        if name not in mapping:
            raise ValueError(f"Unknown broker safety tool: {name}")
        return mapping[name]()
