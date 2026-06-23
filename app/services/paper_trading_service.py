from __future__ import annotations

from app.brokers.paper import PaperBroker
from app.db.database import Database, get_database
from app.db.models import OrderRequest


class PaperTradingService:
    def __init__(self, price_provider, database: Database | None = None) -> None:
        self.database = database or get_database()
        self.broker = PaperBroker(price_provider, self.database)

    def place_order(self, symbol: str, side: str, quantity: int, client_order_id: str | None = None, strategy_id: str | None = None) -> dict:
        return self.broker.place_order(OrderRequest(symbol, side, quantity, strategy_id=strategy_id, client_order_id=client_order_id))

    def account(self) -> dict: return self.broker.get_funds()
    def positions(self) -> list[dict]: return self.broker.get_positions()
    def orders(self, limit: int = 200) -> list[dict]: return self.database.query("SELECT * FROM paper_orders ORDER BY created_at DESC LIMIT ?", (limit,))
    def trades(self, limit: int = 200) -> list[dict]: return self.database.query("SELECT * FROM paper_trades ORDER BY exit_time DESC LIMIT ?", (limit,))
    def reset(self) -> dict: self.broker.reset(); return self.snapshot()

    def exit_sweep(self) -> dict:
        self.broker.mark_to_market(); exits = []
        for position in list(self.positions()):
            price, avg, peak = position["last_price"], position["avg_price"], position["highest_price"]
            reason = None
            if price <= avg * (1 - 0.05): reason = "STOP_LOSS"
            elif price >= avg * (1 + 0.15): reason = "TAKE_PROFIT"
            elif price <= peak * (1 - 0.07): reason = "TRAILING_STOP"
            if reason:
                result = self.place_order(position["symbol"], "SELL", position["quantity"])
                result["exit_reason"] = reason; exits.append(result)
        return {"exits_triggered": len(exits), "exit_details": exits}

    def snapshot(self) -> dict:
        return {"mode": "PAPER", "account": self.account(), "positions": self.positions(), "orders": self.orders(50), "trades": self.trades(50)}
