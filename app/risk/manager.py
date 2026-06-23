from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import config_settings as legacy_config
from app.core.config import SETTINGS, Stage1Config
from app.db.database import Database, get_database
from app.db.models import RiskDecision
from app.risk import rules


class RiskManager:
    def __init__(self, database: Database | None = None, settings: Stage1Config = SETTINGS) -> None:
        self.database = database or get_database()
        self.settings = settings

    def assess_order(self, symbol: str, side: str, quantity: int, price: float, mode: str = "PAPER", strategy_id: str | None = None) -> RiskDecision:
        symbol, side, mode = symbol.upper(), side.upper(), mode.upper()
        if self.settings.kill_switch:
            return self._reject(rules.KILL_SWITCH, "Kill switch is active.", "critical", symbol, strategy_id)
        if mode == "LIVE" and not self.settings.live_trading_enabled:
            return self._reject(rules.LIVE_DISABLED, "Live trading is disabled by Stage 1 policy.", "critical", symbol, strategy_id)
        if quantity <= 0 or price <= 0 or side not in {"BUY", "SELL"}:
            return self._reject(rules.INVALID_ORDER, "Order side, quantity, or price is invalid.", "error", symbol, strategy_id)
        order_value = quantity * price
        account_rows = self.database.query("SELECT realized_pnl, unrealized_pnl FROM paper_account WHERE id=1")
        if side == "BUY" and account_rows and (account_rows[0]["realized_pnl"] + account_rows[0]["unrealized_pnl"]) <= -self.settings.max_daily_loss:
            return self._reject(rules.DAILY_LOSS, "Maximum daily paper loss threshold reached.", "critical", symbol, strategy_id)
        if side == "BUY" and order_value > self.settings.max_order_value:
            return self._reject(rules.MAX_ORDER_VALUE, f"Order value {order_value:.2f} exceeds limit {self.settings.max_order_value:.2f}.", "error", symbol, strategy_id)
        open_positions = self.database.query("SELECT symbol FROM paper_positions WHERE status='OPEN'")
        symbols = {row["symbol"] for row in open_positions}
        if side == "BUY" and symbol in symbols and not self.settings.duplicate_positions_allowed:
            return self._reject(rules.DUPLICATE_POSITION, f"An open position already exists for {symbol}.", "warning", symbol, strategy_id)
        if side == "BUY" and len(open_positions) >= legacy_config.MAX_PORTFOLIO_POSITIONS:
            return self._reject(rules.MAX_POSITIONS, "Maximum open paper positions reached.", "error", symbol, strategy_id)
        return RiskDecision(True, "Approved", "APPROVED", "info", {
            "order_value": order_value, "mode": mode,
            "market_hours_guard": "observe_only_stage1",
            "data_freshness_guard": "observe_only_stage1",
        })

    def _reject(self, rule_id: str, reason: str, severity: str, symbol: str | None, strategy_id: str | None) -> RiskDecision:
        context: dict[str, Any] = {"rule_id": rule_id}
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO risk_events(severity,event_type,symbol,strategy_id,reason,context_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (severity, "ORDER_REJECTED", symbol, strategy_id, reason, json.dumps(context), datetime.now(timezone.utc).isoformat()),
            )
        return RiskDecision(False, reason, rule_id, severity, context)
