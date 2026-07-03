from __future__ import annotations

from typing import Any

from app.brokers.broker_factory import BrokerFactory
from app.brokers.broker_modes import (
    DEFAULT_BROKER_MODE,
    BrokerMode,
    broker_mode_spec,
    broker_mode_specs,
    normalize_broker_mode,
    safe_broker_mode,
)
from app.core.config import SETTINGS
from app.core.errors import BrokerError
from app.db.models import OrderRequest

_SECRET_KEY_FRAGMENTS = ("secret", "token", "api_key", "api-secret", "password", "access")


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(fragment in key_text for fragment in _SECRET_KEY_FRAGMENTS):
                cleaned[key] = "******"
            else:
                cleaned[key] = _sanitize(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


class BrokerService:
    def __init__(self, factory: BrokerFactory | None = None, initial_mode: str | BrokerMode | None = None) -> None:
        self.factory = factory or BrokerFactory()
        requested_mode = SETTINGS.broker_mode if initial_mode is None else initial_mode
        self._mode, self._mode_warning = safe_broker_mode(requested_mode)

    @property
    def current_mode(self) -> BrokerMode:
        return self._mode

    def broker(self):
        return self.factory.create(self._mode)

    def modes(self) -> list[dict[str, Any]]:
        return broker_mode_specs()

    def mode(self) -> dict[str, Any]:
        payload = broker_mode_spec(self._mode)
        payload["is_default"] = self._mode is DEFAULT_BROKER_MODE
        payload["warning"] = self._mode_warning
        return payload

    def status(self) -> dict[str, Any]:
        broker = self.broker()
        warnings = []
        if self._mode_warning:
            warnings.append(self._mode_warning)
        if SETTINGS.live_trading_enabled:
            warnings.append("ALGO_LIVE_TRADING_ENABLED is true, but Stage 7 Batch 2 broker service still blocks live orders.")
        try:
            health = broker.health_check()
        except Exception as exc:  # pragma: no cover - defensive status endpoint behavior
            health = {"healthy": False, "error": str(exc)}
        return {
            "stage": "stage7_batch2",
            "mode": self._mode.value,
            "default_mode": DEFAULT_BROKER_MODE.value,
            "live_trading_enabled_env": bool(SETTINGS.live_trading_enabled),
            "live_orders_allowed": False,
            "tiny_live_locked": self._mode is BrokerMode.TINY_LIVE,
            "broker": _sanitize(broker.capabilities()),
            "health": _sanitize(health),
            "available_modes": self.modes(),
            "warnings": warnings,
        }

    def set_mode(self, mode: str | BrokerMode, actor: str = "user") -> dict[str, Any]:
        if str(actor).strip().lower() != "user":
            raise PermissionError("Only the user can change broker mode; assistants cannot switch broker modes.")
        self._mode = normalize_broker_mode(mode)
        self._mode_warning = None
        return self.mode()

    def quotes(self, symbols: list[str]) -> dict[str, float]:
        clean_symbols = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
        return _sanitize(self.broker().get_quotes(clean_symbols))

    def funds(self) -> dict[str, Any]:
        return _sanitize(self.broker().get_funds())

    def positions(self) -> list[dict]:
        return _sanitize(self.broker().get_positions())

    def holdings(self) -> list[dict]:
        return _sanitize(self.broker().get_holdings())

    def place_order(self, order_request: OrderRequest, actor: str = "user") -> dict[str, Any]:
        if str(actor).strip().lower() != "user":
            raise PermissionError("Assistant cannot execute broker actions.")
        broker = self.broker()
        capabilities = broker.capabilities()
        if capabilities["real_broker"] or capabilities["supports_live_orders"]:
            raise BrokerError("Real broker order submission is disabled by Stage 7 Batch 2 safety policy.")
        if self._mode is not BrokerMode.PAPER:
            raise BrokerError(f"Broker mode '{self._mode.value}' is fail-closed for order submission.")
        return _sanitize(broker.place_order(order_request))

    def cancel_order(self, order_id: str, actor: str = "user") -> dict[str, Any]:
        if str(actor).strip().lower() != "user":
            raise PermissionError("Assistant cannot execute broker actions.")
        if self._mode is not BrokerMode.PAPER:
            raise BrokerError(f"Broker mode '{self._mode.value}' is fail-closed for order cancellation.")
        return _sanitize(self.broker().cancel_order(order_id))

