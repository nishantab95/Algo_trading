from __future__ import annotations

import json
from typing import Any

from app.brokers.broker_errors import BrokerError
from app.brokers.broker_models import sanitize_broker_payload
from app.brokers.broker_modes import BrokerMode, normalize_mode
from app.db.database import Database, get_database
from app.db.models import OrderRequest
from app.live.live_audit import new_shadow_id, utc_now


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


class ShadowLiveService:
    def __init__(self, database: Database | None = None, broker_service=None, live_risk_manager=None, paper_broker=None) -> None:
        self.database = database or get_database()
        self.broker_service = broker_service
        self.live_risk_manager = live_risk_manager
        self.paper_broker = paper_broker

    def _paper(self):
        if self.paper_broker is not None:
            return self.paper_broker
        if self.broker_service is not None:
            return self.broker_service.get_paper_broker()
        return None

    def _quote(self, symbol: str) -> tuple[float | None, list[str]]:
        warnings: list[str] = []
        if self.broker_service is None:
            return None, ["broker_service_unavailable"]
        try:
            quote = self.broker_service.quote(symbol)
            price = _float(quote.get("last_price"), 0.0)
            if price <= 0:
                warnings.append("broker_quote_unavailable")
                return None, warnings
            return price, warnings
        except Exception as exc:
            warnings.append(f"broker_quote_unavailable: {exc}")
            return None, warnings

    def _simulate_paper(self, payload: dict[str, Any], shadow_id: str, price: float | None) -> tuple[str | None, float | None, list[str]]:
        warnings: list[str] = []
        paper = self._paper()
        if paper is None:
            return None, None, ["paper_broker_unavailable"]
        if price is None or price <= 0:
            return None, None, ["paper_simulation_skipped_without_quote"]
        try:
            if hasattr(paper, "create_order"):
                order = paper.create_order(
                    {
                        "client_order_id": shadow_id + "_paper",
                        "symbol": payload["symbol"],
                        "side": payload["side"],
                        "quantity": payload["quantity"],
                        "order_type": payload["order_type"],
                        "requested_price": price,
                        "strategy_id": payload.get("strategy_id"),
                        "combo_id": payload.get("combo_id"),
                        "source": "shadow_live",
                        "metadata": {"shadow_id": shadow_id},
                    },
                    approved_by_user=True,
                )
                return str(order.get("id") or order.get("client_order_id")), _float(order.get("fill_price"), None), warnings
            request = OrderRequest(
                symbol=payload["symbol"],
                side=payload["side"],
                quantity=int(payload["quantity"]),
                order_type=str(payload["order_type"]).upper(),
                requested_price=price,
                strategy_id=payload.get("strategy_id"),
                client_order_id=shadow_id + "_paper",
            )
            order = paper.place_order(request)
            return str(order.get("client_order_id") or order.get("id")), _float(order.get("fill_price"), None), warnings
        except Exception as exc:
            warnings.append(f"paper_simulation_failed: {exc}")
            return None, None, warnings

    def _live_gate(self, payload: dict[str, Any], price: float | None) -> tuple[bool, list[str], dict[str, Any]]:
        if self.live_risk_manager is None:
            return False, ["live_risk_manager_unavailable"], {}
        risk_payload = {
            **payload,
            "price": price if price is not None else payload.get("price"),
            "product_type": payload.get("product_type", "CNC"),
            "exchange": payload.get("exchange", "NSE"),
            "approved_by_user": True,
            "approved_by_actor": "user",
        }
        try:
            result = self.live_risk_manager.preflight_order(risk_payload, actor="user")
            return bool(result.get("approved")), list(result.get("rejection_reasons") or []), result
        except Exception as exc:
            return False, [f"live_gate_error: {exc}"], {}

    def _persist(self, event: dict[str, Any]) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO shadow_live_events(
                    shadow_id, strategy_id, combo_id, symbol, signal_time, intended_side, intended_quantity,
                    intended_order_type, paper_order_id, paper_fill_price, broker_quote_price, spread_estimate,
                    slippage_estimate, would_pass_live_gate, blocked_reason, warnings_json, live_gate_json, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event["shadow_id"],
                    event.get("strategy_id"),
                    event.get("combo_id"),
                    event["symbol"],
                    event["signal_time"],
                    event["intended_side"],
                    event["intended_quantity"],
                    event["intended_order_type"],
                    event.get("paper_order_id"),
                    event.get("paper_fill_price"),
                    event.get("broker_quote_price"),
                    event.get("spread_estimate"),
                    event.get("slippage_estimate"),
                    1 if event.get("would_pass_live_gate") else 0,
                    event.get("blocked_reason"),
                    json.dumps(event.get("warnings", []), default=str),
                    json.dumps(event.get("live_gate", {}), default=str),
                    event["created_at"],
                ),
            )

    def _row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "shadow_id": row["shadow_id"],
            "strategy_id": row["strategy_id"],
            "combo_id": row["combo_id"],
            "symbol": row["symbol"],
            "signal_time": row["signal_time"],
            "intended_side": row["intended_side"],
            "intended_quantity": row["intended_quantity"],
            "intended_order_type": row["intended_order_type"],
            "paper_order_id": row["paper_order_id"],
            "paper_fill_price": row["paper_fill_price"],
            "broker_quote_price": row["broker_quote_price"],
            "spread_estimate": row["spread_estimate"],
            "slippage_estimate": row["slippage_estimate"],
            "would_pass_live_gate": bool(row["would_pass_live_gate"]),
            "blocked_reason": row["blocked_reason"],
            "warnings": json.loads(row["warnings_json"] or "[]"),
            "live_gate": json.loads(row["live_gate_json"] or "{}"),
            "created_at": row["created_at"],
        }

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.database.query("SELECT * FROM shadow_live_events ORDER BY id DESC LIMIT ?", (int(limit),))
        return [self._row(row) for row in rows]

    def run(self, payload: dict[str, Any] | None, actor: str = "user") -> dict[str, Any]:
        raw = dict(payload or {})
        symbol = str(raw.get("symbol", "")).strip().upper()
        side = str(raw.get("side", "BUY")).strip().upper() or "BUY"
        quantity = _int(raw.get("quantity"))
        order_type = str(raw.get("order_type", "market")).strip().lower() or "market"
        if not symbol:
            raise ValueError("Symbol is required for shadow-live.")
        if quantity <= 0:
            raise ValueError("Positive quantity is required for shadow-live.")

        shadow_id = new_shadow_id()
        mode = "unknown"
        if self.broker_service is not None:
            try:
                mode = normalize_mode(self.broker_service.get_mode()).value
            except Exception:
                mode = "unknown"
        warnings: list[str] = []
        if mode != BrokerMode.SHADOW_LIVE.value:
            warnings.append("shadow_live_mode_required")

        event_payload = {
            **raw,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
        }
        quote_price, quote_warnings = self._quote(symbol)
        warnings.extend(quote_warnings)
        paper_order_id = None
        paper_fill_price = None
        if raw.get("simulate_paper", True) is not False:
            paper_order_id, paper_fill_price, paper_warnings = self._simulate_paper(event_payload, shadow_id, quote_price)
            warnings.extend(paper_warnings)
        would_pass, live_reasons, live_gate = self._live_gate(event_payload, quote_price)
        if quote_price is None:
            blocked_reason = "broker_quote_unavailable"
        elif live_reasons:
            blocked_reason = ",".join(live_reasons)
        elif warnings:
            blocked_reason = ",".join(warnings)
        else:
            blocked_reason = ""
        slippage = (paper_fill_price - quote_price) if paper_fill_price is not None and quote_price is not None else None
        event = sanitize_broker_payload(
            {
                "shadow_id": shadow_id,
                "strategy_id": raw.get("strategy_id"),
                "combo_id": raw.get("combo_id"),
                "symbol": symbol,
                "signal_time": str(raw.get("signal_time") or utc_now()),
                "intended_side": side,
                "intended_quantity": quantity,
                "intended_order_type": order_type,
                "paper_order_id": paper_order_id,
                "paper_fill_price": paper_fill_price,
                "broker_quote_price": quote_price,
                "spread_estimate": abs(slippage) if slippage is not None else None,
                "slippage_estimate": slippage,
                "would_pass_live_gate": would_pass,
                "blocked_reason": blocked_reason,
                "warnings": warnings,
                "live_gate": live_gate,
                "created_at": utc_now(),
                "actor": actor,
                "live_order_submitted": False,
            }
        )
        self._persist(event)
        return event

    def report(self) -> dict[str, Any]:
        events = self.events(500)
        by_reason: dict[str, int] = {}
        slippages = []
        for event in events:
            reason = event.get("blocked_reason") or "none"
            by_reason[reason] = by_reason.get(reason, 0) + 1
            if event.get("slippage_estimate") is not None:
                slippages.append(float(event["slippage_estimate"]))
        return {
            "total_events": len(events),
            "would_pass_live_gate_count": sum(1 for event in events if event.get("would_pass_live_gate")),
            "blocked_count": sum(1 for event in events if not event.get("would_pass_live_gate")),
            "paper_simulated_count": sum(1 for event in events if event.get("paper_order_id")),
            "average_slippage_estimate": round(sum(slippages) / len(slippages), 4) if slippages else None,
            "blocked_reasons": by_reason,
            "events": events,
            "live_order_submitted": False,
        }
