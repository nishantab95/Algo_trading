from __future__ import annotations

from typing import Any

from app.brokers.broker_errors import BrokerNotConnectedError, BrokerPermissionError, BrokerUnavailableError
from app.db.models import OrderRequest


class BaseBroker:
    mode = "unknown"
    broker_name = "base"
    read_only = True
    real_broker = False
    supports_live_orders = False
    supports_paper_orders = False
    supports_order_mutation = False

    def capabilities(self) -> dict[str, Any]:
        return {
            "mode": str(getattr(self, "mode", "unknown")).lower(),
            "broker_name": str(getattr(self, "broker_name", self.__class__.__name__)),
            "read_only": bool(getattr(self, "read_only", True)),
            "real_broker": bool(getattr(self, "real_broker", False)),
            "supports_live_orders": bool(getattr(self, "supports_live_orders", False)),
            "supports_paper_orders": bool(getattr(self, "supports_paper_orders", False)),
            "supports_order_mutation": bool(getattr(self, "supports_order_mutation", False)),
        }

    def _unavailable(self, action: str) -> None:
        raise BrokerUnavailableError(f"Broker action '{action}' is unavailable for broker {self.broker_name} in mode {self.mode}.")

    def _not_connected(self, action: str) -> None:
        raise BrokerNotConnectedError(f"Broker is not connected; cannot read {action}.")

    def reject_mutation(self, action: str = "broker mutation") -> None:
        raise BrokerPermissionError(f"{action} is not allowed in broker mode {self.mode}.")

    def connect(self) -> dict[str, Any]:
        self._unavailable("connect")

    def disconnect(self) -> dict[str, Any]:
        self._unavailable("disconnect")

    def is_connected(self) -> bool:
        return False

    def get_profile(self) -> dict[str, Any]:
        self._not_connected("profile")

    def get_funds(self) -> dict[str, Any]:
        self._not_connected("funds")

    def get_holdings(self) -> list[dict]:
        self._not_connected("holdings")

    def get_positions(self) -> list[dict]:
        self._not_connected("positions")

    def get_orders(self) -> list[dict]:
        self._not_connected("orders")

    def get_order(self, order_id: str) -> dict:
        self._not_connected(f"order {order_id}")

    def get_order_status(self, order_id: str) -> dict:
        return self.get_order(order_id)

    def get_trades(self) -> list[dict]:
        self._not_connected("trades")

    def get_instruments(self) -> list[dict]:
        self._not_connected("instruments")

    def get_quote(self, symbol: str) -> dict[str, Any]:
        self._not_connected(f"quote for {symbol}")

    def get_quotes(self, symbols: list[str]) -> dict[str, float]:
        quotes = {}
        for symbol in symbols:
            quote = self.get_quote(symbol)
            quotes[str(symbol).upper()] = float(quote.get("last_price", 0.0))
        return quotes

    def place_order(self, order_request: OrderRequest) -> dict:
        self.reject_mutation("order submission")

    def cancel_order(self, order_id: str) -> dict:
        self.reject_mutation("order cancellation")

    def modify_order(self, order_id: str, modification: dict[str, Any]) -> dict:
        self.reject_mutation("order modification")

    def reconcile(self) -> dict:
        self._unavailable("reconcile")

    def health_check(self) -> dict:
        return {"healthy": False, "mode": self.mode, "broker_name": self.broker_name, "connected": False}

