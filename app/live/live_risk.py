from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.brokers.broker_errors import BrokerError, BrokerPermissionError
from app.brokers.broker_modes import BrokerMode, normalize_mode
from app.brokers.broker_models import sanitize_broker_payload
from app.db.database import Database, get_database
from app.live.kill_switch import KILL_SWITCH_ARMED
from app.live.unlock import iso_now

DEFAULT_TINY_LIVE_LIMITS: dict[str, Any] = {
    "max_order_value": 1000.0,
    "max_daily_order_value": 2000.0,
    "max_orders_per_day": 2,
    "max_open_live_positions": 1,
    "max_live_position_value": 1000.0,
    "allowed_product_type": "CNC",
    "allowed_order_types": ["market", "limit"],
    "allowed_exchange": "NSE",
    "intraday_disallowed_by_default": True,
    "short_selling_disallowed": True,
    "derivatives_disallowed": True,
    "options_disallowed": True,
    "leverage_disallowed": True,
}

REQUIRED_RISK_CHECKS = [
    "tiny_live_mode_required",
    "unlock_required",
    "unlock_not_expired",
    "broker_connected",
    "reconciliation_passing",
    "readiness_not_critical_fail",
    "kill_switch_armed_not_triggered",
    "user_approval_required",
    "assistant_cannot_approve",
    "max_order_value",
    "max_daily_order_value",
    "max_orders_per_day",
    "max_open_live_positions",
    "allowed_exchange",
    "allowed_product_type",
    "allowed_order_type",
    "no_intraday",
    "no_short_selling",
    "no_derivatives",
    "no_options",
    "no_leverage",
    "cash_available",
    "symbol_required",
    "quantity_required",
    "price_sanity",
]


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


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text


def _cash_value(funds: dict[str, Any]) -> float | None:
    for key in ("available_cash", "cash", "net", "equity", "opening_balance"):
        if key in funds and funds[key] is not None:
            return _float(funds[key])
    return None


def _today_prefix() -> str:
    return datetime.now(timezone.utc).date().isoformat() + "%"


class LiveRiskManager:
    def __init__(
        self,
        database: Database | None = None,
        broker_service=None,
        reconciliation_service=None,
        readiness_service=None,
        unlock_service=None,
        kill_switch_service=None,
    ) -> None:
        self.database = database or get_database()
        self.broker_service = broker_service
        self.reconciliation_service = reconciliation_service
        self.readiness_service = readiness_service
        self.unlock_service = unlock_service
        self.kill_switch_service = kill_switch_service
        self._ensure_limits()

    def _ensure_limits(self) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO tiny_live_limits(id, limits_json, updated_at) VALUES(1, ?, ?)",
                (json.dumps(DEFAULT_TINY_LIVE_LIMITS, sort_keys=True), iso_now()),
            )

    def limits(self) -> dict[str, Any]:
        self._ensure_limits()
        rows = self.database.query("SELECT limits_json, updated_at FROM tiny_live_limits WHERE id=1")
        if not rows:
            return {**DEFAULT_TINY_LIVE_LIMITS, "updated_at": None}
        loaded = json.loads(rows[0]["limits_json"] or "{}")
        merged = {**DEFAULT_TINY_LIVE_LIMITS, **loaded}
        if "allowed_order_types" in merged:
            merged["allowed_order_types"] = [str(item).lower() for item in merged["allowed_order_types"]]
        return {**merged, "updated_at": rows[0]["updated_at"]}

    def update_limits(self, changes: dict[str, Any], actor: str = "user") -> dict[str, Any]:
        actor_clean = str(actor or "user").strip().lower()
        if actor_clean == "assistant":
            raise BrokerPermissionError("Assistant cannot update tiny-live limits.")
        allowed_keys = set(DEFAULT_TINY_LIVE_LIMITS)
        unknown = sorted(set(changes or {}) - allowed_keys)
        if unknown:
            raise ValueError(f"Unsupported tiny-live limit keys: {', '.join(unknown)}")
        current = {key: value for key, value in self.limits().items() if key != "updated_at"}
        current.update(changes or {})
        current["allowed_product_type"] = str(current["allowed_product_type"]).upper()
        current["allowed_exchange"] = str(current["allowed_exchange"]).upper()
        current["allowed_order_types"] = [str(item).lower() for item in current.get("allowed_order_types", [])]
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE tiny_live_limits SET limits_json=?, updated_at=? WHERE id=1",
                (json.dumps(current, sort_keys=True), iso_now()),
            )
        return self.limits()

    def _add_check(
        self,
        checks: list[dict[str, Any]],
        name: str,
        passed: bool,
        message: str,
        severity: str = "critical",
        details: dict[str, Any] | None = None,
    ) -> None:
        checks.append(
            sanitize_broker_payload(
                {
                    "check": name,
                    "status": "pass" if passed else "fail",
                    "severity": severity,
                    "message": message,
                    "details": details or {},
                }
            )
        )

    def _daily_usage(self) -> dict[str, float]:
        rows = self.database.query(
            "SELECT COUNT(*) AS orders_count, COALESCE(SUM(order_value), 0) AS total_value FROM live_risk_events WHERE status='approved' AND created_at LIKE ?",
            (_today_prefix(),),
        )
        row = rows[0] if rows else {"orders_count": 0, "total_value": 0.0}
        return {"orders_count": _int(row.get("orders_count")), "total_value": _float(row.get("total_value"))}

    def _read_open_positions(self, payload: dict[str, Any]) -> tuple[int, float, str | None]:
        if "open_live_positions" in payload or "open_live_position_value" in payload:
            return _int(payload.get("open_live_positions")), _float(payload.get("open_live_position_value")), None
        if self.broker_service is None:
            return 0, 0.0, "broker_service_missing"
        try:
            positions = self.broker_service.positions()
            count = 0
            value = 0.0
            for row in positions:
                quantity = _float(row.get("quantity") or row.get("qty") or row.get("net_quantity"))
                if quantity <= 0:
                    continue
                count += 1
                price = _float(row.get("last_price") or row.get("current_price") or row.get("avg_price"))
                value += abs(quantity * price)
            return count, value, None
        except Exception as exc:
            return 0, 0.0, str(exc)

    def _persist_event(
        self,
        event_id: str,
        mode: str,
        payload: dict[str, Any],
        order_value: float,
        status: str,
        checks: list[dict[str, Any]],
        rejection_reasons: list[str],
        actor: str,
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO live_risk_events(event_id, mode, symbol, side, quantity, order_value, status, checks_json, rejection_reasons_json, actor, created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event_id,
                    mode,
                    _clean_text(payload.get("symbol")).upper() or None,
                    _clean_text(payload.get("side", "BUY")).upper() or None,
                    _int(payload.get("quantity")) or None,
                    float(order_value),
                    status,
                    json.dumps(sanitize_broker_payload(checks), default=str),
                    json.dumps(sanitize_broker_payload(rejection_reasons), default=str),
                    actor,
                    iso_now(),
                ),
            )

    def preflight_order(self, payload: dict[str, Any] | None, actor: str = "user") -> dict[str, Any]:
        payload = dict(payload or {})
        actor_clean = str(actor or payload.get("actor") or "user").strip().lower()
        checks: list[dict[str, Any]] = []
        limits = self.limits()
        event_id = "risk_" + uuid.uuid4().hex[:12]

        mode_text = "unknown"
        if self.broker_service is not None:
            try:
                mode_text = normalize_mode(self.broker_service.get_mode()).value
            except Exception as exc:
                mode_text = "unknown"
                self._add_check(checks, "tiny_live_mode_required", False, "Broker mode could not be read.", details={"error": str(exc)})
        if not any(check["check"] == "tiny_live_mode_required" for check in checks):
            self._add_check(checks, "tiny_live_mode_required", mode_text == BrokerMode.TINY_LIVE.value, "Broker mode must be tiny_live for tiny-live preflight.", details={"mode": mode_text})

        unlock_status = self.unlock_service.status() if self.unlock_service is not None else {"unlocked": False, "locked": True, "expires_at": None}
        unlocked = bool(unlock_status.get("unlocked"))
        self._add_check(checks, "unlock_required", unlocked, "Tiny-live must be explicitly unlocked by the user.", details=unlock_status)
        self._add_check(checks, "unlock_not_expired", unlocked, "Tiny-live unlock must be active and unexpired.", details={"expires_at": unlock_status.get("expires_at")})

        broker_status: dict[str, Any] = {}
        if self.broker_service is None:
            self._add_check(checks, "broker_connected", False, "Broker service is unavailable.")
        else:
            try:
                broker_status = self.broker_service.get_status()
                self._add_check(checks, "broker_connected", bool(broker_status.get("broker_connected")), "Broker read-only state must be connected.", details=broker_status)
            except Exception as exc:
                self._add_check(checks, "broker_connected", False, "Broker status read failed.", details={"error": str(exc)})

        try:
            reconciliation_ok = bool(self.reconciliation_service and self.reconciliation_service.is_reconciliation_passing(BrokerMode.TINY_LIVE))
            self._add_check(checks, "reconciliation_passing", reconciliation_ok, "Latest tiny-live reconciliation must be passing.")
        except Exception as exc:
            self._add_check(checks, "reconciliation_passing", False, "Reconciliation status read failed.", details={"error": str(exc)})

        try:
            latest = self.readiness_service.latest_run() if self.readiness_service is not None else None
            critical_failures = list((latest or {}).get("critical_failures") or [])
            readiness_ok = bool(latest and latest.get("mode") == BrokerMode.TINY_LIVE.value and not critical_failures and latest.get("overall_status") != "failed")
            self._add_check(checks, "readiness_not_critical_fail", readiness_ok, "Latest tiny-live readiness run must have no critical failures.", details={"latest": latest})
        except Exception as exc:
            self._add_check(checks, "readiness_not_critical_fail", False, "Readiness status read failed.", details={"error": str(exc)})

        try:
            kill_status = self.kill_switch_service.status() if self.kill_switch_service is not None else {"state": "missing", "armed": False, "triggered": False}
            kill_ok = kill_status.get("state") == KILL_SWITCH_ARMED and bool(kill_status.get("armed")) and not bool(kill_status.get("triggered"))
            self._add_check(checks, "kill_switch_armed_not_triggered", kill_ok, "Kill switch must be armed and not triggered.", details=kill_status)
        except Exception as exc:
            self._add_check(checks, "kill_switch_armed_not_triggered", False, "Kill switch status read failed.", details={"error": str(exc)})

        approved_by_user = payload.get("approved_by_user") is True
        approved_by_actor = str(payload.get("approved_by_actor") or actor_clean or "").strip().lower()
        self._add_check(checks, "user_approval_required", approved_by_user, "Explicit user approval is required for preflight.")
        self._add_check(checks, "assistant_cannot_approve", actor_clean != "assistant" and approved_by_actor != "assistant", "Assistant cannot approve, unlock, or route tiny-live requests.", details={"actor": actor_clean, "approved_by_actor": approved_by_actor})

        symbol = _clean_text(payload.get("symbol")).upper()
        side = _clean_text(payload.get("side", "BUY")).upper() or "BUY"
        quantity = _int(payload.get("quantity"))
        price_value = payload.get("price", payload.get("limit_price", payload.get("requested_price")))
        price = _float(price_value, -1.0)
        order_value = float(quantity * price) if quantity > 0 and price > 0 else 0.0
        order_type = _clean_text(payload.get("order_type", "market")).lower() or "market"
        product_type = _clean_text(payload.get("product_type", "CNC")).upper() or "CNC"
        exchange = _clean_text(payload.get("exchange", "NSE")).upper() or "NSE"

        self._add_check(checks, "symbol_required", bool(symbol), "Symbol is required.", details={"symbol": symbol})
        self._add_check(checks, "quantity_required", quantity > 0, "Quantity must be a positive integer.", details={"quantity": quantity})
        self._add_check(checks, "price_sanity", price > 0 and price < 1_000_000, "A positive, sane reference price is required.", details={"price": price})

        self._add_check(checks, "max_order_value", order_value > 0 and order_value <= _float(limits["max_order_value"]), "Order value must stay within the tiny-live cap.", details={"order_value": order_value, "limit": limits["max_order_value"]})
        daily = self._daily_usage()
        self._add_check(checks, "max_daily_order_value", daily["total_value"] + order_value <= _float(limits["max_daily_order_value"]), "Daily approved tiny-live value cap would be exceeded.", details={"daily_value": daily["total_value"], "order_value": order_value, "limit": limits["max_daily_order_value"]})
        self._add_check(checks, "max_orders_per_day", daily["orders_count"] + 1 <= _int(limits["max_orders_per_day"]), "Daily approved tiny-live order count cap would be exceeded.", details={"daily_orders": daily["orders_count"], "limit": limits["max_orders_per_day"]})

        open_positions, open_value, open_error = self._read_open_positions(payload)
        self._add_check(checks, "max_open_live_positions", open_error is None and open_positions < _int(limits["max_open_live_positions"]), "Open live position count must remain below the tiny-live cap.", details={"open_positions": open_positions, "limit": limits["max_open_live_positions"], "error": open_error})
        self._add_check(checks, "max_live_position_value", open_error is None and open_value + order_value <= _float(limits["max_live_position_value"]), "Open live position value must stay within the tiny-live cap.", details={"open_position_value": open_value, "order_value": order_value, "limit": limits["max_live_position_value"], "error": open_error})

        self._add_check(checks, "allowed_exchange", exchange == str(limits["allowed_exchange"]).upper(), "Only the configured exchange is allowed.", details={"exchange": exchange, "allowed": limits["allowed_exchange"]})
        self._add_check(checks, "allowed_product_type", product_type == str(limits["allowed_product_type"]).upper(), "Only CNC delivery product type is allowed.", details={"product_type": product_type, "allowed": limits["allowed_product_type"]})
        self._add_check(checks, "allowed_order_type", order_type in set(limits["allowed_order_types"]), "Only market or limit orders are allowed.", details={"order_type": order_type, "allowed": limits["allowed_order_types"]})

        intraday = bool(payload.get("intraday")) or product_type in {"MIS", "INTRADAY"}
        derivative_text = " ".join(str(payload.get(key, "")) for key in ("asset_class", "instrument_type", "segment", "symbol")).upper()
        is_option = "OPT" in derivative_text or "OPTION" in derivative_text
        is_derivative = is_option or "FUT" in derivative_text or "DERIV" in derivative_text or "NFO" in derivative_text
        leverage = bool(payload.get("leverage")) or _float(payload.get("margin_multiplier"), 1.0) > 1.0 or product_type in {"MIS", "NRML"}
        self._add_check(checks, "no_intraday", not (limits["intraday_disallowed_by_default"] and intraday), "Intraday tiny-live orders are disallowed.")
        self._add_check(checks, "no_short_selling", not (limits["short_selling_disallowed"] and side == "SELL"), "Short selling is disallowed for tiny-live.", details={"side": side})
        self._add_check(checks, "no_derivatives", not (limits["derivatives_disallowed"] and is_derivative), "Derivatives are disallowed for tiny-live.", details={"descriptor": derivative_text})
        self._add_check(checks, "no_options", not (limits["options_disallowed"] and is_option), "Options are disallowed for tiny-live.", details={"descriptor": derivative_text})
        self._add_check(checks, "no_leverage", not (limits["leverage_disallowed"] and leverage), "Leverage is disallowed for tiny-live.")

        cash_available = None
        if self.broker_service is not None:
            try:
                cash_available = _cash_value(self.broker_service.funds())
            except Exception as exc:
                self._add_check(checks, "cash_available", False, "Broker funds could not be read.", details={"error": str(exc), "required": order_value})
        if not any(check["check"] == "cash_available" for check in checks):
            self._add_check(checks, "cash_available", cash_available is not None and cash_available >= order_value > 0, "Available cash must cover the tiny-live order value.", details={"cash_available": cash_available, "required": order_value})

        failed = [check for check in checks if check["status"] == "fail"]
        rejection_reasons = [check["check"] for check in failed]
        status = "approved" if not failed else "rejected"
        self._persist_event(event_id, mode_text, payload, order_value, status, checks, rejection_reasons, actor_clean)
        return sanitize_broker_payload(
            {
                "event_id": event_id,
                "status": status,
                "approved": status == "approved",
                "checks": checks,
                "rejection_reasons": rejection_reasons,
                "order_value": order_value,
                "limits": limits,
                "live_order_submitted": False,
                "broker_place_order_called": False,
            }
        )
