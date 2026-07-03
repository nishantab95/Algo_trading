from __future__ import annotations

from typing import Any

from app.brokers.base import BaseBroker
from app.brokers.broker_errors import (
    BrokerError,
    BrokerModeError,
    BrokerPermissionError,
    BrokerReadOnlyError,
)
from app.brokers.broker_factory import BrokerFactory
from app.brokers.broker_modes import (
    DEFAULT_BROKER_MODE,
    BrokerMode,
    allows_live_order,
    allows_paper_order,
    allows_readonly_broker,
    broker_mode_spec,
    broker_mode_specs,
    normalize_mode,
    requires_reconciliation,
    safe_broker_mode,
)
from app.brokers.broker_models import BrokerReadonlyState, BrokerStatus, sanitize_broker_payload
from app.core.config import SETTINGS
from app.core.logging_config import log_event
from app.db.models import OrderRequest


class BrokerService:
    def __init__(self, factory: BrokerFactory | None = None, initial_mode: str | BrokerMode | None = None) -> None:
        self.factory = factory or BrokerFactory()
        requested_mode = SETTINGS.broker_mode if initial_mode is None else initial_mode
        self._mode, self._mode_warning = safe_broker_mode(requested_mode)

    @property
    def current_mode(self) -> BrokerMode:
        return self._mode

    def get_mode(self) -> str:
        return self._mode.value

    def mode(self) -> dict[str, Any]:
        payload = broker_mode_spec(self._mode)
        payload["is_default"] = self._mode is DEFAULT_BROKER_MODE
        payload["warning"] = self._mode_warning
        return payload

    def modes(self) -> list[dict[str, Any]]:
        return broker_mode_specs()

    def get_broker(self) -> BaseBroker:
        return self.factory.create(self._mode)

    def broker(self) -> BaseBroker:
        return self.get_broker()

    def get_paper_broker(self) -> BaseBroker:
        return self.factory.paper()

    def _mode_message(self) -> str:
        if self._mode is BrokerMode.LIVE_DISABLED:
            return "Live trading is disabled."
        if self._mode is BrokerMode.PAPER:
            return "Paper mode is active. Live orders are disabled."
        if self._mode is BrokerMode.BROKER_READONLY:
            return "Broker read-only mode is active. Mutations are disabled."
        if self._mode is BrokerMode.SHADOW_LIVE:
            return "Shadow-live is read-only in Batch 2. Live orders are disabled."
        return "Tiny-live is locked in Batch 2. Live orders are disabled."

    def get_status(self) -> dict[str, Any]:
        broker = self.get_broker()
        warnings = []
        if self._mode_warning:
            warnings.append(self._mode_warning)
        if SETTINGS.live_trading_enabled:
            warnings.append("ALGO_LIVE_TRADING_ENABLED is true, but Stage 7 Batch 2 still blocks live orders.")
        try:
            health = broker.health_check()
        except Exception as exc:  # pragma: no cover - defensive API status behavior
            health = {"healthy": False, "connected": False, "error": str(exc)}
        status = BrokerStatus(
            mode=self._mode.value,
            live_trading_enabled=bool(SETTINGS.live_trading_enabled),
            broker_connected=bool(health.get("connected", broker.is_connected() if hasattr(broker, "is_connected") else False)),
            readonly_available=allows_readonly_broker(self._mode),
            live_orders_allowed=allows_live_order(self._mode),
            paper_orders_allowed=allows_paper_order(self._mode),
            message=self._mode_message(),
            warnings=warnings,
        ).to_dict()
        status.update(
            {
                "default_mode": DEFAULT_BROKER_MODE.value,
                "tiny_live_locked": self._mode is BrokerMode.TINY_LIVE,
                "requires_reconciliation": requires_reconciliation(self._mode),
                "broker": sanitize_broker_payload(broker.capabilities()),
                "health": sanitize_broker_payload(health),
                "available_modes": self.modes(),
                "live_trading_enabled_env": bool(SETTINGS.live_trading_enabled),
            }
        )
        return status

    def status(self) -> dict[str, Any]:
        return self.get_status()

    def _log_mode_change(self, old_mode: BrokerMode, new_mode: BrokerMode, actor: str) -> None:
        try:
            log_event(
                "info",
                "broker_service",
                "broker_mode_changed",
                f"Broker mode changed from {old_mode.value} to {new_mode.value}",
                {"old_mode": old_mode.value, "new_mode": new_mode.value, "actor": actor},
            )
        except Exception:
            # Logging must never make a broker safety transition fail open.
            pass

    def set_mode(self, mode: str | BrokerMode, actor: str = "user") -> dict[str, Any]:
        actor_clean = str(actor or "user").strip().lower()
        new_mode = normalize_mode(mode)
        if actor_clean == "assistant" and (new_mode is BrokerMode.TINY_LIVE or allows_readonly_broker(new_mode)):
            raise BrokerPermissionError("Assistant cannot switch to tiny_live or live-like broker modes.")
        old_mode = self._mode
        self._mode = new_mode
        self._mode_warning = None
        self._log_mode_change(old_mode, new_mode, actor_clean)
        return self.mode()

    def assert_can_place_paper_order(self) -> bool:
        if not allows_paper_order(self._mode):
            raise BrokerModeError(f"Broker mode '{self._mode.value}' does not allow paper order placement.")
        return True

    def assert_can_place_live_order(self, actor: str = "user") -> bool:
        raise BrokerPermissionError("Live order placement is disabled in Stage 7 Batch 2.")

    def _assert_read_allowed(self) -> None:
        if self._mode is BrokerMode.LIVE_DISABLED:
            raise BrokerModeError("Broker read-only access is unavailable while mode is live_disabled.")

    def _read(self, method_name: str, *args: Any) -> Any:
        self._assert_read_allowed()
        broker = self.get_broker()
        method = getattr(broker, method_name)
        return sanitize_broker_payload(method(*args))

    def get_readonly_state(self) -> dict[str, Any]:
        if not allows_readonly_broker(self._mode):
            raise BrokerModeError(f"Broker mode '{self._mode.value}' does not allow read-only live broker state.")
        broker = self.get_broker()
        state = BrokerReadonlyState(
            mode=self._mode.value,
            connected=broker.is_connected(),
            profile=broker.get_profile(),
            funds=broker.get_funds(),
            holdings=broker.get_holdings(),
            positions=broker.get_positions(),
            orders=broker.get_orders(),
            trades=broker.get_trades(),
        )
        return state.to_dict()

    def profile(self) -> dict[str, Any]:
        return self._read("get_profile")

    def funds(self) -> dict[str, Any]:
        return self._read("get_funds")

    def holdings(self) -> list[dict]:
        return self._read("get_holdings")

    def positions(self) -> list[dict]:
        return self._read("get_positions")

    def orders(self) -> list[dict]:
        return self._read("get_orders")

    def trades(self) -> list[dict]:
        return self._read("get_trades")

    def quote(self, symbol: str) -> dict[str, Any]:
        return self._read("get_quote", str(symbol).upper())

    def quotes(self, symbols: list[str]) -> dict[str, float]:
        self._assert_read_allowed()
        clean_symbols = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
        return sanitize_broker_payload(self.get_broker().get_quotes(clean_symbols))

    def place_order(self, order_request: OrderRequest, actor: str = "user") -> dict[str, Any]:
        if str(actor or "user").strip().lower() != "user":
            raise BrokerPermissionError("Assistant cannot execute broker actions.")
        if self._mode is not BrokerMode.PAPER:
            raise BrokerReadOnlyError(f"Broker mode '{self._mode.value}' is read-only and fail-closed for order submission.")
        broker = self.get_broker()
        capabilities = broker.capabilities()
        if capabilities["real_broker"] or capabilities["supports_live_orders"]:
            raise BrokerPermissionError("Real broker order submission is disabled by Stage 7 Batch 2 safety policy.")
        return sanitize_broker_payload(broker.place_order(order_request))

    def cancel_order(self, order_id: str, actor: str = "user") -> dict[str, Any]:
        if str(actor or "user").strip().lower() != "user":
            raise BrokerPermissionError("Assistant cannot execute broker actions.")
        if self._mode is not BrokerMode.PAPER:
            return self.get_broker().cancel_order(order_id)
        return sanitize_broker_payload(self.get_broker().cancel_order(order_id))

    def modify_order(self, order_id: str, modification: dict[str, Any] | None = None, actor: str = "user") -> dict[str, Any]:
        if str(actor or "user").strip().lower() != "user":
            raise BrokerPermissionError("Assistant cannot execute broker actions.")
        if self._mode is not BrokerMode.PAPER:
            return self.get_broker().modify_order(order_id, modification or {})
        return sanitize_broker_payload(self.get_broker().modify_order(order_id, modification or {}))
