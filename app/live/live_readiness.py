from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid

READINESS_STATUSES = {"pass", "warning", "fail", "not_checked", "not_applicable"}
READINESS_SEVERITIES = {"info", "low", "medium", "high", "critical"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    return "ready_" + uuid.uuid4().hex[:12]


@dataclass(frozen=True)
class ReadinessCheck:
    check_id: str
    check_name: str
    status: str
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def overall_readiness_status(checks: list[ReadinessCheck]) -> str:
    if any(check.status == "fail" and check.severity == "critical" for check in checks):
        return "failed"
    if any(check.status == "fail" for check in checks):
        return "failed"
    if any(check.status == "warning" for check in checks):
        return "warning"
    if any(check.status == "not_checked" for check in checks):
        return "warning"
    return "passed"

