from __future__ import annotations

from typing import Any

from app.brokers.base import BaseBroker
from app.core.config import SETTINGS
from app.core.errors import BrokerError
from app.core.logging_config import log_event
from app.db.models import OrderRequest


class ZerodhaBroker(BaseBroker):
    mode = "LIVE"
    broker_name = "zerodha"
    read_only = False
    real_broker = True
    supports_live_orders = True
    supports_paper_orders = False
    supports_order_mutation = True

    def __init__(self, kite: Any = None) -> None:
        self.kite = kite

    def _require_enabled(self) -> None:
        if not SETTINGS.live_trading_enabled:
            raise BrokerError("Live trading is disabled. Set ALGO_LIVE_TRADING_ENABLED only after completing live-safety work.")
        if self.kite is None:
            raise BrokerError("Zerodha session is not authenticated.")

    def get_quotes(self, symbols: list[str]) -> dict[str, float]:
        self._require_enabled(); raw = self.kite.ltp([f"NSE:{s}" for s in symbols]); return {s: float(raw[f"NSE:{s}"]["last_price"]) for s in symbols}
    def get_funds(self) -> dict: self._require_enabled(); return self.kite.margins()
    def get_positions(self) -> list[dict]: self._require_enabled(); return self.kite.positions().get("net", [])
    def get_holdings(self) -> list[dict]: self._require_enabled(); return self.kite.holdings()

    def place_order(self, order_request: OrderRequest) -> dict:
        self._require_enabled()
        try:
            order_id = self.kite.place_order(variety="regular", exchange="NSE", tradingsymbol=order_request.symbol.upper(), transaction_type=order_request.side.upper(), quantity=order_request.quantity, order_type=order_request.order_type, product="CNC")
            return {"status": "LIVE_ORDER_SUBMITTED", "order_id": order_id}
        except Exception as exc:
            log_event("error", "zerodha_broker", "live_order_failed", "Live order failed; no paper fallback was created", {"error": str(exc), "symbol": order_request.symbol})
            raise BrokerError(f"Live order failed: {exc}") from exc

    def cancel_order(self, order_id: str) -> dict: self._require_enabled(); return {"order_id": self.kite.cancel_order("regular", order_id)}
    def get_order_status(self, order_id: str) -> dict: self._require_enabled(); return {"history": self.kite.order_history(order_id)}
    def reconcile(self) -> dict: self._require_enabled(); return {"positions": self.get_positions(), "holdings": self.get_holdings()}
    def health_check(self) -> dict:
        return {"healthy": bool(SETTINGS.live_trading_enabled and self.kite is not None), "mode": self.mode, "live_enabled": SETTINGS.live_trading_enabled}
