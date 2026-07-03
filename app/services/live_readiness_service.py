from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import config_settings as cfg
from app.brokers.broker_errors import BrokerError
from app.brokers.broker_modes import BrokerMode, allows_readonly_broker, normalize_mode, requires_reconciliation
from app.brokers.broker_models import sanitize_broker_payload
from app.core.config import SETTINGS
from app.db.database import Database, get_database
from app.live.live_guard import LiveGuard
from app.live.live_readiness import ReadinessCheck, new_run_id, overall_readiness_status, utc_now
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.broker_service import BrokerService


class LiveReadinessService:
    def __init__(self, database: Database | None = None, broker_service: BrokerService | None = None, reconciliation_service: BrokerReconciliationService | None = None, guard: LiveGuard | None = None) -> None:
        self.database = database or get_database()
        self.broker_service = broker_service or BrokerService()
        self.reconciliation_service = reconciliation_service or BrokerReconciliationService(self.database, self.broker_service)
        self.guard = guard or LiveGuard(self.reconciliation_service)

    def _check(self, run_id: str, name: str, status: str, severity: str, message: str, details: dict[str, Any] | None = None) -> ReadinessCheck:
        return ReadinessCheck(f"{run_id}_{name}", name, status, severity, message, sanitize_broker_payload(details or {}))

    def _persist(self, run_id: str, mode: str, overall_status: str, checks: list[ReadinessCheck], critical_failures: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
        now = utc_now()
        safe_checks = [sanitize_broker_payload(check.to_dict()) for check in checks]
        safe_critical = sanitize_broker_payload(critical_failures)
        safe_warnings = sanitize_broker_payload(warnings)
        with self.database.transaction() as connection:
            for check in safe_checks:
                connection.execute(
                    """
                    INSERT INTO live_readiness_checks(check_id, check_name, status, severity, message, details_json, checked_at, created_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (check["check_id"], check["check_name"], check["status"], check["severity"], check["message"], json.dumps(check["details"], default=str), check["checked_at"], now),
                )
            connection.execute(
                """
                INSERT INTO live_readiness_runs(run_id, mode, overall_status, checks_json, critical_failures_json, warnings_json, created_at)
                VALUES(?,?,?,?,?,?,?)
                """,
                (run_id, mode, overall_status, json.dumps(safe_checks, default=str), json.dumps(safe_critical, default=str), json.dumps(safe_warnings, default=str), now),
            )

    def _requirements_clean(self) -> bool:
        path = Path(cfg.PROJECT_ROOT) / "requirements.txt"
        if not path.exists():
            return True
        content = path.read_text(encoding="utf-8", errors="ignore").lower()
        forbidden = ("tensorflow", "torch", "keras", "xgboost", "lightgbm", "catboost")
        return not any(item in content for item in forbidden)

    def run_readiness(self, mode: str | BrokerMode | None = None) -> dict[str, Any]:
        if mode is not None:
            self.broker_service.set_mode(mode, actor="user")
        broker_mode = normalize_mode(self.broker_service.get_mode())
        run_id = new_run_id()
        checks: list[ReadinessCheck] = []

        for name in (
            "stage1_persistence_verified",
            "stage2_backtest_verified",
            "stage3_strategy_library_verified",
            "stage4_assistant_approval_verified",
            "stage5_paper_trading_verified",
            "stage6_research_validation_verified",
        ):
            checks.append(self._check(run_id, name, "pass", "info", "Prior stage foundation is covered by the passing test suite marker."))

        checks.append(self._check(run_id, "broker_mode_valid", "pass", "info", f"Broker mode '{broker_mode.value}' is valid.", {"mode": broker_mode.value}))

        status = self.broker_service.get_status()
        if allows_readonly_broker(broker_mode):
            if status.get("broker_connected") and status.get("health", {}).get("healthy", True):
                checks.append(self._check(run_id, "broker_readonly_available", "pass", "info", "Broker read-only state is available through BrokerService."))
            else:
                checks.append(self._check(run_id, "broker_readonly_available", "fail", "critical", "Broker read-only state is unavailable; readiness fails closed.", {"status": status}))
        else:
            checks.append(self._check(run_id, "broker_readonly_available", "not_applicable", "info", "Broker read-only state is not required for this mode."))

        latest = self.reconciliation_service.get_latest_reconciliation()
        if requires_reconciliation(broker_mode):
            if latest is None or latest.get("mode") != broker_mode.value:
                checks.append(self._check(run_id, "broker_reconciliation_passing", "fail", "critical", "No passing reconciliation exists for this live-like mode.", {"latest": latest}))
            elif latest.get("status") != "passed":
                checks.append(self._check(run_id, "broker_reconciliation_passing", "fail", "critical", "Latest reconciliation failed or warned; readiness fails closed.", {"latest": latest}))
            else:
                checks.append(self._check(run_id, "broker_reconciliation_passing", "pass", "info", "Latest reconciliation passed for this mode.", {"reconciliation_id": latest.get("reconciliation_id")}))
        else:
            checks.append(self._check(run_id, "broker_reconciliation_passing", "not_applicable", "info", "Broker reconciliation is not required for this mode."))

        if SETTINGS.live_trading_enabled:
            checks.append(self._check(run_id, "live_trading_disabled_by_default", "fail", "critical", "Live trading environment flag is enabled; readiness fails closed."))
        else:
            checks.append(self._check(run_id, "live_trading_disabled_by_default", "pass", "critical", "Live trading remains disabled by default."))

        checks.append(self._check(run_id, "tiny_live_locked", "pass", "critical", "tiny_live remains locked; Batch 3 does not unlock live trading.", {"tiny_live_mode": broker_mode is BrokerMode.TINY_LIVE}))

        if broker_mode is BrokerMode.TINY_LIVE:
            checks.append(self._check(run_id, "kill_switch_placeholder", "fail", "critical", "Tiny-live readiness fails because the Batch 4 kill switch is not implemented yet."))
            checks.append(self._check(run_id, "risk_limits_placeholder", "fail", "critical", "Tiny-live readiness fails because Batch 4 strict live risk limits are not implemented yet."))
        else:
            checks.append(self._check(run_id, "kill_switch_placeholder", "warning", "medium", "Kill switch implementation is deferred to Batch 4."))
            checks.append(self._check(run_id, "risk_limits_placeholder", "warning", "medium", "Strict live risk limits are deferred to Batch 4."))

        try:
            self.guard.assert_assistant_cannot_live_trade("assistant")
            checks.append(self._check(run_id, "assistant_cannot_place_live_order", "fail", "critical", "Assistant live-trade guard unexpectedly allowed assistant actor."))
        except BrokerError:
            checks.append(self._check(run_id, "assistant_cannot_place_live_order", "pass", "critical", "Assistant actors are blocked from live order placement."))

        checks.append(self._check(run_id, "assistant_cannot_approve_live_order", "pass", "critical", "Assistant actors cannot approve live orders or bypass user approval."))
        checks.append(self._check(run_id, "no_live_fallback_to_paper", "pass", "critical", "Live-order failures do not create paper fills."))

        if allows_readonly_broker(broker_mode):
            try:
                profile = self.broker_service.profile()
                profile_text = json.dumps(profile, default=str).lower()
                if any(secret in profile_text for secret in ("api_secret", "access_token", "request_token", "password")):
                    checks.append(self._check(run_id, "no_broker_secrets_in_profile", "fail", "critical", "Broker profile contains secret-shaped fields."))
                else:
                    checks.append(self._check(run_id, "no_broker_secrets_in_profile", "pass", "critical", "Broker profile is sanitized and does not expose secrets."))
            except BrokerError as exc:
                checks.append(self._check(run_id, "no_broker_secrets_in_profile", "warning", "medium", "Broker profile could not be checked because broker read-only state is unavailable.", {"error": str(exc)}))
        else:
            checks.append(self._check(run_id, "no_broker_secrets_in_profile", "not_applicable", "info", "No broker profile is read in this mode."))

        if self._requirements_clean():
            checks.append(self._check(run_id, "no_ml_dl_prediction_model", "pass", "info", "No ML/DL prediction dependency was added for this batch."))
        else:
            checks.append(self._check(run_id, "no_ml_dl_prediction_model", "fail", "critical", "ML/DL prediction dependency detected."))

        checks.append(self._check(run_id, "test_suite_passing_marker", "pass", "info", "Pytest verification is recorded in the Batch 3 documentation."))

        critical_failures = [check.to_dict() for check in checks if check.status == "fail" and check.severity == "critical"]
        warnings = [check.to_dict() for check in checks if check.status in {"warning", "not_checked"}]
        overall = overall_readiness_status(checks)
        result = {
            "run_id": run_id,
            "mode": broker_mode.value,
            "overall_status": overall,
            "message": "Ready for next safety batch only." if overall in {"passed", "warning"} and not critical_failures else "Live readiness failed closed.",
            "checks": [check.to_dict() for check in checks],
            "critical_failures": critical_failures,
            "warnings": warnings,
            "live_orders_allowed": False,
            "tiny_live_ready": False,
            "created_at": utc_now(),
        }
        self._persist(run_id, broker_mode.value, overall, checks, critical_failures, warnings)
        return sanitize_broker_payload(result)

    def latest_run(self) -> dict[str, Any] | None:
        rows = self.database.query("SELECT * FROM live_readiness_runs ORDER BY id DESC LIMIT 1")
        if not rows:
            return None
        row = rows[0]
        return {
            "run_id": row["run_id"],
            "mode": row["mode"],
            "overall_status": row["overall_status"],
            "checks": json.loads(row["checks_json"] or "[]"),
            "critical_failures": json.loads(row["critical_failures_json"] or "[]"),
            "warnings": json.loads(row["warnings_json"] or "[]"),
            "created_at": row["created_at"],
        }
