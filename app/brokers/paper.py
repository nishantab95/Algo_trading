from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable

import config_settings as cfg
from app.brokers.base import BaseBroker
from app.core.logging_config import log_event
from app.db.database import Database, get_database
from app.db.models import OrderRequest
from app.risk.manager import RiskManager


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PaperBroker(BaseBroker):
    mode = "PAPER"
    broker_name = "paper"
    read_only = False
    real_broker = False
    supports_live_orders = False
    supports_paper_orders = True
    supports_order_mutation = True

    def __init__(self, price_provider: Callable[[str], float], database: Database | None = None, risk_manager: RiskManager | None = None) -> None:
        self.database = database or get_database()
        self.price_provider = price_provider
        self.risk_manager = risk_manager or RiskManager(self.database)
        self.ensure_account()

    def ensure_account(self) -> None:
        now = _now()
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO paper_account(id,cash,starting_capital,realized_pnl,unrealized_pnl,total_equity,updated_at) VALUES(1,?,?,?,?,?,?)",
                (cfg.INITIAL_CAPITAL, cfg.INITIAL_CAPITAL, 0.0, 0.0, cfg.INITIAL_CAPITAL, now),
            )


    def connect(self) -> dict:
        return {"connected": True, "mode": self.mode, "source": "paper"}

    def disconnect(self) -> dict:
        return {"connected": True, "mode": self.mode, "source": "paper", "message": "Paper broker remains locally available."}

    def is_connected(self) -> bool:
        return True

    def get_profile(self) -> dict:
        account = self.get_funds()
        return {"mode": self.mode, "broker": "paper", "account_id": "default", "currency": "INR", "cash": account["cash"]}

    def get_quote(self, symbol: str) -> dict:
        clean_symbol = str(symbol).upper()
        return {"symbol": clean_symbol, "last_price": float(self.price_provider(clean_symbol)), "source": "paper", "stale": False}

    def get_orders(self) -> list[dict]:
        return self.database.query("SELECT * FROM paper_orders ORDER BY created_at DESC LIMIT 200")

    def get_order(self, order_id: str) -> dict:
        rows = self.database.query("SELECT * FROM paper_orders WHERE client_order_id=? OR CAST(id AS TEXT)=?", (str(order_id), str(order_id)))
        if not rows:
            raise ValueError("Unknown paper order.")
        return rows[0]

    def get_trades(self) -> list[dict]:
        return self.database.query("SELECT * FROM paper_trades ORDER BY exit_time DESC LIMIT 200")

    def get_instruments(self) -> list[dict]:
        return []

    def modify_order(self, order_id: str, modification: dict) -> dict:
        self.reject_mutation("paper order modification")

    def get_quotes(self, symbols: list[str]) -> dict[str, float]:
        return {symbol: float(self.price_provider(symbol)) for symbol in symbols}

    def get_funds(self) -> dict:
        return self.database.query("SELECT * FROM paper_account WHERE id=1")[0]

    def get_positions(self) -> list[dict]:
        return self.database.query("SELECT * FROM paper_positions WHERE status='OPEN' ORDER BY opened_at")

    def get_holdings(self) -> list[dict]:
        return self.get_positions()

    def place_order(self, order_request: OrderRequest) -> dict:
        symbol, side, quantity = order_request.symbol.upper(), order_request.side.upper(), int(order_request.quantity)
        client_id = order_request.client_order_id or str(uuid.uuid4())
        existing = self.database.query("SELECT * FROM paper_orders WHERE client_order_id=?", (client_id,))
        if existing:
            return existing[0]
        market_price = float(order_request.requested_price or self.price_provider(symbol))
        slippage = 0.0007 if side == "BUY" else -0.0007
        fill_price = round(market_price * (1 + slippage), 2)
        decision = self.risk_manager.assess_order(symbol, side, quantity, fill_price, self.mode, order_request.strategy_id)
        now = _now()
        if not decision.approved:
            self._record_order(client_id, order_request, market_price, None, "REJECTED", decision.reason, now)
            log_event("warning", "paper_broker", "order_rejected", decision.reason, decision.to_dict())
            raise ValueError(decision.reason)

        notional = fill_price * quantity
        with self.database.transaction() as connection:
            account = connection.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
            if side == "BUY":
                if notional > account["cash"]:
                    raise ValueError(f"Insufficient paper cash: need {notional:.2f}, have {account['cash']:.2f}.")
                connection.execute(
                    "INSERT INTO paper_positions(symbol,quantity,avg_price,last_price,highest_price,unrealized_pnl,opened_at,updated_at,status) VALUES(?,?,?,?,?,?,?,?,'OPEN')",
                    (symbol, quantity, fill_price, fill_price, fill_price, 0.0, now, now),
                )
                cash = account["cash"] - notional
            else:
                position = connection.execute("SELECT * FROM paper_positions WHERE symbol=? AND status='OPEN'", (symbol,)).fetchone()
                if position is None or position["quantity"] < quantity:
                    raise ValueError(f"No sufficient open paper position for {symbol}.")
                remaining = position["quantity"] - quantity
                gross = (fill_price - position["avg_price"]) * quantity
                cash = account["cash"] + notional
                realized = account["realized_pnl"] + gross
                if remaining:
                    connection.execute("UPDATE paper_positions SET quantity=?,last_price=?,updated_at=? WHERE id=?", (remaining, fill_price, now, position["id"]))
                else:
                    connection.execute("DELETE FROM paper_positions WHERE id=?", (position["id"],))
                connection.execute(
                    "INSERT INTO paper_trades(symbol,side,quantity,entry_price,exit_price,gross_pnl,costs,net_pnl,entry_time,exit_time,exit_reason,strategy_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (symbol, side, quantity, position["avg_price"], fill_price, gross, 0.0, gross, position["opened_at"], now, "MANUAL_OR_RISK_EXIT", order_request.strategy_id),
                )
                connection.execute("UPDATE paper_account SET realized_pnl=? WHERE id=1", (realized,))
            connection.execute(
                "UPDATE paper_account SET cash=?,total_equity=?,updated_at=? WHERE id=1",
                (cash, cash + sum(row["quantity"] * row["last_price"] for row in connection.execute("SELECT * FROM paper_positions WHERE status='OPEN'")), now),
            )
            connection.execute(
                "INSERT INTO paper_orders(client_order_id,broker_order_id,mode,symbol,side,quantity,order_type,requested_price,fill_price,status,rejection_reason,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'FILLED',NULL,?,?)",
                (client_id, None, self.mode, symbol, side, quantity, order_request.order_type, market_price, fill_price, now, now),
            )
        result = {"status": "PAPER_FILLED", "client_order_id": client_id, "symbol": symbol, "side": side, "quantity": quantity, "fill_price": fill_price, "notional": round(notional, 2)}
        log_event("info", "paper_broker", "paper_fill", "Paper order filled", result)
        return result

    def _record_order(self, client_id: str, request: OrderRequest, requested: float, fill: float | None, status: str, reason: str | None, now: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO paper_orders(client_order_id,mode,symbol,side,quantity,order_type,requested_price,fill_price,status,rejection_reason,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (client_id, self.mode, request.symbol.upper(), request.side.upper(), request.quantity, request.order_type, requested, fill, status, reason, now, now),
            )

    def mark_to_market(self) -> None:
        now = _now()
        with self.database.transaction() as connection:
            positions = connection.execute("SELECT * FROM paper_positions WHERE status='OPEN'").fetchall()
            unrealized = 0.0
            for position in positions:
                price = float(self.price_provider(position["symbol"]))
                pnl = (price - position["avg_price"]) * position["quantity"]
                unrealized += pnl
                connection.execute("UPDATE paper_positions SET last_price=?,highest_price=?,unrealized_pnl=?,updated_at=? WHERE id=?", (price, max(price, position["highest_price"]), pnl, now, position["id"]))
            account = connection.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
            value = sum(row["quantity"] * row["last_price"] for row in connection.execute("SELECT * FROM paper_positions WHERE status='OPEN'"))
            connection.execute("UPDATE paper_account SET unrealized_pnl=?,total_equity=?,updated_at=? WHERE id=1", (unrealized, account["cash"] + value, now))

    def reset(self) -> None:
        now = _now()
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM paper_positions")
            connection.execute("UPDATE paper_account SET cash=starting_capital,realized_pnl=0,unrealized_pnl=0,total_equity=starting_capital,updated_at=? WHERE id=1", (now,))
        log_event("warning", "paper_broker", "paper_reset", "Paper account explicitly reset")

    def cancel_order(self, order_id: str) -> dict:
        raise ValueError("Paper market orders fill immediately and cannot be cancelled.")

    def get_order_status(self, order_id: str) -> dict:
        rows = self.database.query("SELECT * FROM paper_orders WHERE client_order_id=?", (order_id,))
        if not rows:
            raise ValueError("Unknown paper order.")
        return rows[0]

    def reconcile(self) -> dict:
        self.mark_to_market()
        return {"mode": self.mode, "positions": len(self.get_positions()), "status": "reconciled"}

    def health_check(self) -> dict:
        return {"healthy": True, "mode": self.mode, "database": str(self.database.path)}
