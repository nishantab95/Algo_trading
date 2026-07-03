from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.brokers.broker_errors import BrokerError
from app.brokers.broker_modes import BrokerMode, allows_readonly_broker, normalize_mode, requires_reconciliation
from app.brokers.broker_models import sanitize_broker_payload
from app.brokers.reconciliation import ReconciliationMismatch, ReconciliationResult, group_status, mismatch, new_reconciliation_id, overall_status, utc_now
from app.db.database import Database, get_database
from app.services.broker_service import BrokerService

LocalStateProvider = Callable[[str], dict[str, Any]]


def _clean_symbol(row: dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("tradingsymbol") or row.get("instrument") or row.get("ticker") or "").upper()


def _quantity(row: dict[str, Any]) -> float:
    for key in ("quantity", "qty", "net_quantity", "net_qty"):
        if key in row and row[key] is not None:
            return float(row[key])
    return 0.0


def _price(row: dict[str, Any]) -> float | None:
    for key in ("avg_price", "average_price", "price", "last_price", "current_price"):
        if key in row and row[key] is not None:
            return float(row[key])
    return None


def _status(row: dict[str, Any]) -> str:
    return str(row.get("status") or row.get("order_status") or "").lower()


def _order_key(row: dict[str, Any]) -> str:
    return str(row.get("order_id") or row.get("broker_order_id") or row.get("client_order_id") or row.get("id") or "")


def _cash_value(funds: dict[str, Any]) -> float | None:
    for key in ("available_cash", "cash", "net", "equity", "opening_balance"):
        if key in funds and funds[key] is not None:
            return float(funds[key])
    return None


def _contains_stale(value: Any) -> bool:
    if isinstance(value, dict):
        if bool(value.get("stale")) or str(value.get("status", "")).lower() == "stale":
            return True
        return any(_contains_stale(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_stale(item) for item in value)
    return False


class BrokerReconciliationService:
    def __init__(self, database: Database | None = None, broker_service: BrokerService | None = None, local_state_provider: LocalStateProvider | None = None) -> None:
        self.database = database or get_database()
        self.broker_service = broker_service or BrokerService()
        self.local_state_provider = local_state_provider or self._default_local_state

    def _default_local_state(self, mode: str) -> dict[str, Any]:
        state: dict[str, Any] = {
            "expected_cash": None,
            "local_live_orders": [],
            "local_live_positions": [],
            "local_live_trades": [],
        }
        if mode == BrokerMode.SHADOW_LIVE.value:
            try:
                paper = self.broker_service.get_paper_broker()
                state["paper_account_if_shadow"] = paper.get_funds()
                state["paper_positions_if_shadow"] = paper.get_positions()
            except Exception as exc:
                state["paper_account_if_shadow"] = None
                state["paper_positions_if_shadow"] = []
                state.setdefault("warnings", []).append(f"Paper shadow state unavailable: {exc}")
        return state

    def _persist(self, result: dict[str, Any]) -> None:
        now = utc_now()
        safe = sanitize_broker_payload(result)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO broker_reconciliations(
                    reconciliation_id, mode, broker, started_at, completed_at, status,
                    funds_status, positions_status, orders_status, trades_status,
                    mismatches_json, warnings_json, errors_json, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    safe["reconciliation_id"],
                    safe["mode"],
                    safe["broker"],
                    safe["started_at"],
                    safe["completed_at"],
                    safe["status"],
                    safe["funds_status"],
                    safe["positions_status"],
                    safe["orders_status"],
                    safe["trades_status"],
                    json.dumps(safe["mismatches"], default=str),
                    json.dumps(safe["warnings"], default=str),
                    json.dumps(safe["errors"], default=str),
                    now,
                ),
            )

    def _row_to_result(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "reconciliation_id": row["reconciliation_id"],
            "mode": row["mode"],
            "broker": row["broker"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "status": row["status"],
            "funds_status": row["funds_status"],
            "positions_status": row["positions_status"],
            "orders_status": row["orders_status"],
            "trades_status": row["trades_status"],
            "mismatches": json.loads(row["mismatches_json"] or "[]"),
            "warnings": json.loads(row["warnings_json"] or "[]"),
            "errors": json.loads(row["errors_json"] or "[]"),
            "created_at": row["created_at"],
        }

    def _compare_funds(self, broker_funds: dict[str, Any], local_state: dict[str, Any], mismatches: list[ReconciliationMismatch]) -> str:
        expected_cash = local_state.get("expected_cash")
        if expected_cash is None:
            return "matched"
        broker_cash = _cash_value(broker_funds)
        if broker_cash is None:
            mismatches.append(mismatch("unknown", "funds", "critical", "Broker cash value is unavailable.", {"broker_funds": broker_funds}))
            return "unknown"
        if abs(float(expected_cash) - broker_cash) > 0.01:
            mismatches.append(
                mismatch(
                    "cash_mismatch",
                    "funds",
                    "critical",
                    "Local and broker cash do not match.",
                    {"local_cash": float(expected_cash), "broker_cash": broker_cash},
                )
            )
            return "cash_mismatch"
        return "matched"

    def _compare_positions(self, broker_positions: list[dict[str, Any]], local_positions: list[dict[str, Any]], mismatches: list[ReconciliationMismatch]) -> str:
        status = "matched"
        broker_by_symbol = {_clean_symbol(row): row for row in broker_positions if _clean_symbol(row)}
        local_by_symbol = {_clean_symbol(row): row for row in local_positions if _clean_symbol(row)}
        for symbol, local in local_by_symbol.items():
            broker = broker_by_symbol.get(symbol)
            if broker is None:
                mismatches.append(mismatch("missing_broker", "positions", "critical", "Expected local live position is missing at broker.", {"symbol": symbol}, symbol=symbol, local_quantity=_quantity(local), broker_quantity=0))
                status = "missing_broker"
                continue
            local_qty, broker_qty = _quantity(local), _quantity(broker)
            if abs(local_qty - broker_qty) > 0.000001:
                mismatches.append(mismatch("quantity_mismatch", "positions", "critical", "Local and broker quantities do not match.", {"symbol": symbol}, symbol=symbol, local_quantity=local_qty, broker_quantity=broker_qty))
                status = "quantity_mismatch"
                continue
            local_price, broker_price = _price(local), _price(broker)
            if local_price is not None and broker_price is not None and abs(local_price - broker_price) > 0.01:
                mismatches.append(mismatch("price_mismatch", "positions", "high", "Local and broker prices do not match.", {"symbol": symbol, "local_price": local_price, "broker_price": broker_price}, symbol=symbol))
                if status == "matched":
                    status = "price_mismatch"
        for symbol, broker in broker_by_symbol.items():
            if symbol not in local_by_symbol:
                mismatches.append(mismatch("missing_local", "positions", "high", "Broker has a position that is missing locally.", {"symbol": symbol}, symbol=symbol, local_quantity=0, broker_quantity=_quantity(broker)))
                if status == "matched":
                    status = "missing_local"
        return status

    def _compare_orders(self, broker_orders: list[dict[str, Any]], local_orders: list[dict[str, Any]], mismatches: list[ReconciliationMismatch]) -> str:
        status = "matched"
        broker_by_key = {_order_key(row): row for row in broker_orders if _order_key(row)}
        local_by_key = {_order_key(row): row for row in local_orders if _order_key(row)}
        for key, local in local_by_key.items():
            broker = broker_by_key.get(key)
            if broker is None:
                mismatches.append(mismatch("missing_broker", "orders", "critical", "Expected local live order is missing at broker.", {"order_id": key}))
                status = "missing_broker"
                continue
            if _status(local) and _status(broker) and _status(local) != _status(broker):
                mismatches.append(mismatch("status_mismatch", "orders", "critical", "Local and broker order statuses do not match.", {"order_id": key, "local_status": _status(local), "broker_status": _status(broker)}))
                status = "status_mismatch"
        for key, broker in broker_by_key.items():
            if key not in local_by_key:
                mismatches.append(mismatch("missing_local", "orders", "medium", "Broker has an order that is missing locally.", {"order_id": key, "broker_status": _status(broker)}))
                if status == "matched":
                    status = "missing_local"
        return status

    def _compare_trades(self, broker_trades: list[dict[str, Any]], local_trades: list[dict[str, Any]], mismatches: list[ReconciliationMismatch]) -> str:
        if not broker_trades and not local_trades:
            return "matched"
        if local_trades and not broker_trades:
            mismatches.append(mismatch("missing_broker", "trades", "critical", "Expected local live trades are missing at broker.", {"local_count": len(local_trades)}))
            return "missing_broker"
        if broker_trades and not local_trades:
            mismatches.append(mismatch("missing_local", "trades", "medium", "Broker has trades that are missing locally.", {"broker_count": len(broker_trades)}))
            return "missing_local"
        return "matched"

    def run_reconciliation(self, mode: str | BrokerMode | None = None, broker_name: str | None = None) -> dict[str, Any]:
        started_at = utc_now()
        reconciliation_id = new_reconciliation_id()
        if mode is not None:
            self.broker_service.set_mode(mode, actor="user")
        broker_mode = normalize_mode(self.broker_service.get_mode())
        broker_label = broker_name or "mock"
        warnings: list[str] = []
        errors: list[str] = []
        mismatches: list[ReconciliationMismatch] = []
        funds_status = positions_status = orders_status = trades_status = "not_applicable"

        if broker_mode is BrokerMode.LIVE_DISABLED:
            warnings.append("Broker reconciliation is not applicable while live trading is disabled.")
            result = ReconciliationResult(reconciliation_id, broker_mode.value, broker_label, started_at, utc_now(), "not_checked", funds_status, positions_status, orders_status, trades_status, [], warnings, errors).to_dict()
            self._persist(result)
            return result
        if broker_mode is BrokerMode.PAPER:
            result = ReconciliationResult(reconciliation_id, broker_mode.value, "paper", started_at, utc_now(), "passed", funds_status, positions_status, orders_status, trades_status, [], warnings, errors).to_dict()
            self._persist(result)
            return result

        if not allows_readonly_broker(broker_mode):
            errors.append(f"Broker read-only access is not allowed for mode {broker_mode.value}.")
        else:
            try:
                state = self.broker_service.get_readonly_state()
                broker_label = str(state.get("profile", {}).get("broker") or state.get("profile", {}).get("source") or broker_label)
                local_state = self.local_state_provider(broker_mode.value)
                warnings.extend(str(item) for item in local_state.get("warnings", []))
                if _contains_stale(state):
                    mismatches.append(mismatch("stale_broker_state", "broker_state", "critical", "Broker state is stale.", {"mode": broker_mode.value}))
                funds_status = self._compare_funds(state.get("funds", {}), local_state, mismatches)
                positions_status = self._compare_positions(state.get("positions", []), local_state.get("local_live_positions", []), mismatches)
                orders_status = self._compare_orders(state.get("orders", []), local_state.get("local_live_orders", []), mismatches)
                trades_status = self._compare_trades(state.get("trades", []), local_state.get("local_live_trades", []), mismatches)
                if broker_mode is BrokerMode.SHADOW_LIVE:
                    if local_state.get("paper_account_if_shadow") is None:
                        warnings.append("Shadow-live paper account comparison is unavailable.")
            except BrokerError as exc:
                errors.append(str(exc))
                mismatches.append(mismatch("broker_unavailable", "broker", "critical", "Broker read-only state is unavailable.", {"error": str(exc), "mode": broker_mode.value}))
                funds_status = positions_status = orders_status = trades_status = "broker_unavailable"
            except Exception as exc:  # pragma: no cover - defensive fail-closed path
                errors.append(str(exc))
                mismatches.append(mismatch("unknown", "broker", "critical", "Unknown reconciliation failure.", {"error": str(exc), "mode": broker_mode.value}))
                funds_status = positions_status = orders_status = trades_status = "unknown"

        statuses = [funds_status, positions_status, orders_status, trades_status]
        result = ReconciliationResult(
            reconciliation_id=reconciliation_id,
            mode=broker_mode.value,
            broker=broker_label,
            started_at=started_at,
            completed_at=utc_now(),
            status=overall_status(statuses, mismatches, errors),
            funds_status=group_status(mismatches, "funds", funds_status),
            positions_status=group_status(mismatches, "positions", positions_status),
            orders_status=group_status(mismatches, "orders", orders_status),
            trades_status=group_status(mismatches, "trades", trades_status),
            mismatches=[item.to_dict() for item in mismatches],
            warnings=warnings,
            errors=errors,
        ).to_dict()
        self._persist(result)
        return sanitize_broker_payload(result)

    def get_latest_reconciliation(self) -> dict[str, Any] | None:
        rows = self.database.query("SELECT * FROM broker_reconciliations ORDER BY id DESC LIMIT 1")
        return self._row_to_result(rows[0]) if rows else None

    def get_reconciliation_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return [self._row_to_result(row) for row in self.database.query("SELECT * FROM broker_reconciliations ORDER BY id DESC LIMIT ?", (int(limit),))]

    def is_reconciliation_passing(self, mode: str | BrokerMode | None = None) -> bool:
        broker_mode = normalize_mode(mode or self.broker_service.get_mode())
        if not requires_reconciliation(broker_mode):
            return True
        latest = self.get_latest_reconciliation()
        return bool(latest and latest["mode"] == broker_mode.value and latest["status"] == "passed")
