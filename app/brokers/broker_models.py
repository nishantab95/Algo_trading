from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.db.models import OrderRequest


_SECRET_KEY_FRAGMENTS = ("secret", "token", "api_key", "api-secret", "password", "access", "password")


def sanitize_broker_payload(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            key_text = str(key).lower()
            cleaned[key] = "******" if any(fragment in key_text for fragment in _SECRET_KEY_FRAGMENTS) else sanitize_broker_payload(item)
        return cleaned
    if isinstance(value, list):
        return [sanitize_broker_payload(item) for item in value]
    return value


@dataclass(frozen=True)
class BrokerStatus:
    mode: str
    live_trading_enabled: bool = False
    broker_connected: bool = False
    readonly_available: bool = False
    live_orders_allowed: bool = False
    paper_orders_allowed: bool = False
    message: str = "Live trading is disabled."
    stage: str = "stage7_batch2"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return sanitize_broker_payload(asdict(self))


@dataclass(frozen=True)
class BrokerOrderRequest:
    symbol: str
    side: str
    quantity: int
    order_type: str = "MARKET"
    requested_price: float | None = None
    product_type: str = "CNC"
    exchange: str = "NSE"
    strategy_id: str | None = None
    client_order_id: str | None = None

    def to_order_request(self) -> OrderRequest:
        return OrderRequest(
            symbol=self.symbol,
            side=self.side,
            quantity=self.quantity,
            order_type=self.order_type,
            requested_price=self.requested_price,
            strategy_id=self.strategy_id,
            client_order_id=self.client_order_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return sanitize_broker_payload(asdict(self))


@dataclass(frozen=True)
class BrokerQuote:
    symbol: str
    last_price: float
    source: str = "mock_broker"
    stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BrokerReadonlyState:
    mode: str
    connected: bool
    profile: dict[str, Any] = field(default_factory=dict)
    funds: dict[str, Any] = field(default_factory=dict)
    holdings: list[dict[str, Any]] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    quotes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return sanitize_broker_payload(asdict(self))


@dataclass(frozen=True)
class BrokerReconciliationState:
    broker_funds: dict[str, Any] = field(default_factory=dict)
    broker_holdings: list[dict[str, Any]] = field(default_factory=list)
    broker_positions: list[dict[str, Any]] = field(default_factory=list)
    broker_orders: list[dict[str, Any]] = field(default_factory=list)
    broker_trades: list[dict[str, Any]] = field(default_factory=list)
    local_live_orders: list[dict[str, Any]] = field(default_factory=list)
    local_live_positions: list[dict[str, Any]] = field(default_factory=list)
    paper_account_if_shadow: dict[str, Any] | None = None
    paper_positions_if_shadow: list[dict[str, Any]] | None = None
    status: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return sanitize_broker_payload(asdict(self))

