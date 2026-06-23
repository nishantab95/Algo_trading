from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    rule_id: str
    severity: str = "info"
    context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str
    quantity: int
    order_type: str = "MARKET"
    requested_price: float | None = None
    strategy_id: str | None = None
    client_order_id: str | None = None
