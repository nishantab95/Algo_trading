from __future__ import annotations

from typing import Any

from app.brokers.base import BaseBroker
from app.brokers.broker_errors import BrokerNotConnectedError, BrokerReadOnlyError, BrokerUnavailableError
from app.brokers.broker_modes import BrokerMode, broker_mode_spec, normalize_mode
from app.brokers.broker_models import BrokerQuote, sanitize_broker_payload
from app.db.models import OrderRequest


class MockBroker(BaseBroker):
    broker_name = "mock_broker"
    read_only = True
    real_broker = False
    supports_live_orders = False
    supports_paper_orders = False
    supports_order_mutation = False

    def __init__(
        self,
        mode: str | BrokerMode = BrokerMode.LIVE_DISABLED,
        connected: bool = True,
        profile: dict[str, Any] | None = None,
        funds: dict[str, Any] | None = None,
        holdings: list[dict[str, Any]] | None = None,
        positions: list[dict[str, Any]] | None = None,
        orders: list[dict[str, Any]] | None = None,
        trades: list[dict[str, Any]] | None = None,
        quotes: dict[str, float] | None = None,
        raise_on_place: bool = False,
        raise_on_read: bool = False,
    ) -> None:
        self._mode = normalize_mode(mode)
        self.mode = self._mode.value
        self.connected = bool(connected)
        self.profile = dict(profile or {"broker": "mock", "account_id": "mock-account", "user_name": "Mock User"})
        self.funds = dict(funds or {"currency": "INR", "available_cash": 0.0, "status": "mock"})
        self.holdings = list(holdings or [])
        self.positions = list(positions or [])
        self.orders = list(orders or [])
        self.trades = list(trades or [])
        self.quotes = {str(symbol).upper(): float(price) for symbol, price in (quotes or {}).items()}
        self.raise_on_place = bool(raise_on_place)
        self.raise_on_read = bool(raise_on_read)
        self.place_order_called = False
        self.cancel_order_called = False
        self.modify_order_called = False

    def _ensure_readable(self, action: str) -> None:
        if self.raise_on_read:
            raise BrokerUnavailableError(f"Mock broker read failed for {action}.")
        if not self.connected:
            raise BrokerNotConnectedError(f"Mock broker is disconnected; cannot read {action}.")

    def connect(self) -> dict[str, Any]:
        self.connected = True
        return {"connected": True, "mode": self.mode, "source": "mock_broker"}

    def disconnect(self) -> dict[str, Any]:
        self.connected = False
        return {"connected": False, "mode": self.mode, "source": "mock_broker"}

    def is_connected(self) -> bool:
        return self.connected

    def get_profile(self) -> dict[str, Any]:
        self._ensure_readable("profile")
        return sanitize_broker_payload({**self.profile, "mode": self.mode, "source": "mock_broker"})

    def get_funds(self) -> dict[str, Any]:
        self._ensure_readable("funds")
        return sanitize_broker_payload({**self.funds, "mode": self.mode, "source": "mock_broker"})

    def get_holdings(self) -> list[dict]:
        self._ensure_readable("holdings")
        return sanitize_broker_payload(self.holdings)

    def get_positions(self) -> list[dict]:
        self._ensure_readable("positions")
        return sanitize_broker_payload(self.positions)

    def get_orders(self) -> list[dict]:
        self._ensure_readable("orders")
        return sanitize_broker_payload(self.orders)

    def get_order(self, order_id: str) -> dict:
        self._ensure_readable(f"order {order_id}")
        for order in self.orders:
            if str(order.get("order_id") or order.get("id")) == str(order_id):
                return sanitize_broker_payload(order)
        raise BrokerUnavailableError(f"Mock broker order '{order_id}' was not found.")

    def get_order_status(self, order_id: str) -> dict:
        return self.get_order(order_id)

    def get_trades(self) -> list[dict]:
        self._ensure_readable("trades")
        return sanitize_broker_payload(self.trades)

    def get_instruments(self) -> list[dict]:
        self._ensure_readable("instruments")
        return []

    def get_quote(self, symbol: str) -> dict[str, Any]:
        self._ensure_readable(f"quote for {symbol}")
        clean_symbol = str(symbol).upper()
        return BrokerQuote(clean_symbol, float(self.quotes.get(clean_symbol, 0.0)), source="mock_broker").to_dict()

    def get_quotes(self, symbols: list[str]) -> dict[str, float]:
        return {str(symbol).upper(): float(self.get_quote(symbol)["last_price"]) for symbol in symbols}

    def place_order(self, order_request: OrderRequest) -> dict:
        self.place_order_called = True
        if self.raise_on_place:
            raise BrokerUnavailableError("Mock broker rejected order submission.")
        raise BrokerReadOnlyError(f"Broker mode '{self.mode}' is read-only: order submission is blocked in Stage 7 Batch 2.")

    def cancel_order(self, order_id: str) -> dict:
        self.cancel_order_called = True
        raise BrokerReadOnlyError(f"Broker mode '{self.mode}' is read-only: order cancellation is blocked in Stage 7 Batch 2.")

    def modify_order(self, order_id: str, modification: dict[str, Any]) -> dict:
        self.modify_order_called = True
        raise BrokerReadOnlyError(f"Broker mode '{self.mode}' is read-only: order modification is blocked in Stage 7 Batch 2.")

    def reconcile(self) -> dict:
        return {"mode": self.mode, "status": "not_applicable", "source": "mock_broker"}

    def health_check(self) -> dict:
        return {
            "healthy": not self.raise_on_read,
            "mode": self.mode,
            "source": "mock_broker",
            "connected": self.connected,
            "read_only": True,
            "real_broker": False,
            "live_orders_allowed": False,
            "mode_spec": broker_mode_spec(self._mode),
        }

