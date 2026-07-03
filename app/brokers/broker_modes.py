from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from app.brokers.broker_errors import BrokerModeError


class BrokerMode(str, Enum):
    LIVE_DISABLED = "live_disabled"
    PAPER = "paper"
    BROKER_READONLY = "broker_readonly"
    SHADOW_LIVE = "shadow_live"
    TINY_LIVE = "tiny_live"


DEFAULT_BROKER_MODE = BrokerMode.LIVE_DISABLED


@dataclass(frozen=True)
class BrokerModeSpec:
    value: str
    label: str
    description: str
    read_only: bool
    paper_trading: bool
    live_broker_state: bool
    live_order_allowed: bool
    order_mutation_allowed: bool
    requires_user_approval: bool


_MODE_SPECS: dict[BrokerMode, BrokerModeSpec] = {
    BrokerMode.LIVE_DISABLED: BrokerModeSpec(
        value=BrokerMode.LIVE_DISABLED.value,
        label="Live disabled",
        description="Fail-closed default. No broker credentials, live state, or order mutation is used.",
        read_only=True,
        paper_trading=False,
        live_broker_state=False,
        live_order_allowed=False,
        order_mutation_allowed=False,
        requires_user_approval=False,
    ),
    BrokerMode.PAPER: BrokerModeSpec(
        value=BrokerMode.PAPER.value,
        label="Paper",
        description="Local paper broker only. Orders are simulated and never routed to a live broker.",
        read_only=False,
        paper_trading=True,
        live_broker_state=False,
        live_order_allowed=False,
        order_mutation_allowed=True,
        requires_user_approval=True,
    ),
    BrokerMode.BROKER_READONLY: BrokerModeSpec(
        value=BrokerMode.BROKER_READONLY.value,
        label="Broker read-only",
        description="Read-only broker-observation mode. Batch 2 uses mock/read-only broker state and rejects mutation.",
        read_only=True,
        paper_trading=False,
        live_broker_state=True,
        live_order_allowed=False,
        order_mutation_allowed=False,
        requires_user_approval=False,
    ),
    BrokerMode.SHADOW_LIVE: BrokerModeSpec(
        value=BrokerMode.SHADOW_LIVE.value,
        label="Shadow live",
        description="Read-only broker observation plus paper compatibility. Live mutation is blocked in Batch 2.",
        read_only=True,
        paper_trading=True,
        live_broker_state=True,
        live_order_allowed=False,
        order_mutation_allowed=False,
        requires_user_approval=False,
    ),
    BrokerMode.TINY_LIVE: BrokerModeSpec(
        value=BrokerMode.TINY_LIVE.value,
        label="Tiny live",
        description="Future restricted live mode. Batch 2 keeps it locked and rejects all live orders.",
        read_only=True,
        paper_trading=False,
        live_broker_state=True,
        live_order_allowed=False,
        order_mutation_allowed=False,
        requires_user_approval=True,
    ),
}


def normalize_mode(value: str | BrokerMode | None) -> BrokerMode:
    if isinstance(value, BrokerMode):
        return value
    raw = str(value or DEFAULT_BROKER_MODE.value).strip().lower()
    for mode in BrokerMode:
        if raw == mode.value:
            return mode
    allowed = ", ".join(mode.value for mode in BrokerMode)
    raise BrokerModeError(f"Unsupported broker mode '{value}'. Allowed modes: {allowed}.")


def normalize_broker_mode(value: str | BrokerMode | None) -> BrokerMode:
    return normalize_mode(value)


def safe_broker_mode(value: str | BrokerMode | None) -> tuple[BrokerMode, str | None]:
    try:
        return normalize_mode(value), None
    except BrokerModeError as exc:
        return DEFAULT_BROKER_MODE, str(exc)


def default_mode() -> BrokerMode:
    return DEFAULT_BROKER_MODE


def broker_mode_spec(mode: str | BrokerMode) -> dict[str, Any]:
    return asdict(_MODE_SPECS[normalize_mode(mode)])


def broker_mode_specs() -> list[dict[str, Any]]:
    return [broker_mode_spec(mode) for mode in BrokerMode]


def is_live_like(mode: str | BrokerMode) -> bool:
    return normalize_mode(mode) in {
        BrokerMode.BROKER_READONLY,
        BrokerMode.SHADOW_LIVE,
        BrokerMode.TINY_LIVE,
    }


def is_live_like_mode(mode: str | BrokerMode) -> bool:
    return is_live_like(mode)


def allows_live_order(mode: str | BrokerMode) -> bool:
    return False


def allows_readonly_broker(mode: str | BrokerMode) -> bool:
    return normalize_mode(mode) in {
        BrokerMode.BROKER_READONLY,
        BrokerMode.SHADOW_LIVE,
        BrokerMode.TINY_LIVE,
    }


def allows_paper_order(mode: str | BrokerMode) -> bool:
    return normalize_mode(mode) in {BrokerMode.PAPER, BrokerMode.SHADOW_LIVE}


def requires_reconciliation(mode: str | BrokerMode) -> bool:
    return is_live_like(mode)

