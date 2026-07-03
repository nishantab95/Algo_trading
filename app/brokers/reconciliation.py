from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid

ITEM_STATUSES = {
    "matched",
    "missing_local",
    "missing_broker",
    "quantity_mismatch",
    "price_mismatch",
    "status_mismatch",
    "cash_mismatch",
    "stale_broker_state",
    "broker_unavailable",
    "not_applicable",
    "unknown",
}

OVERALL_STATUSES = {"passed", "warning", "failed", "not_checked"}
FAIL_STATUSES = {"broker_unavailable", "unknown", "cash_mismatch", "quantity_mismatch", "missing_broker", "status_mismatch", "stale_broker_state"}
WARNING_STATUSES = {"missing_local", "price_mismatch"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_reconciliation_id() -> str:
    return "rec_" + uuid.uuid4().hex[:12]


@dataclass(frozen=True)
class ReconciliationMismatch:
    type: str
    source: str
    severity: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    symbol: str | None = None
    local_quantity: float | None = None
    broker_quantity: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {key: value for key, value in data.items() if value is not None}


@dataclass(frozen=True)
class ReconciliationResult:
    reconciliation_id: str
    mode: str
    broker: str
    started_at: str
    completed_at: str
    status: str
    funds_status: str = "not_applicable"
    positions_status: str = "not_applicable"
    orders_status: str = "not_applicable"
    trades_status: str = "not_applicable"
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def mismatch(type_: str, source: str, severity: str, message: str, context: dict[str, Any] | None = None, **kwargs: Any) -> ReconciliationMismatch:
    if type_ not in ITEM_STATUSES:
        type_ = "unknown"
    return ReconciliationMismatch(type_, source, severity, message, context or {}, **kwargs)


def group_status(mismatches: list[ReconciliationMismatch], source: str, default: str = "matched") -> str:
    relevant = [item.type for item in mismatches if item.source == source]
    for status in ("broker_unavailable", "unknown", "cash_mismatch", "quantity_mismatch", "missing_broker", "status_mismatch", "stale_broker_state", "missing_local", "price_mismatch"):
        if status in relevant:
            return status
    return default


def overall_status(statuses: list[str], mismatches: list[ReconciliationMismatch], errors: list[str]) -> str:
    if errors:
        return "failed"
    if any(status in FAIL_STATUSES for status in statuses):
        return "failed"
    if any(item.severity == "critical" for item in mismatches):
        return "failed"
    if any(status in WARNING_STATUSES for status in statuses) or any(item.severity in {"high", "medium"} for item in mismatches):
        return "warning"
    if all(status == "not_applicable" for status in statuses):
        return "not_checked"
    return "passed"

