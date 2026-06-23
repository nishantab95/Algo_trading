from __future__ import annotations

import math

from app.backtesting.models import BacktestConfig, Position


class Portfolio:
    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.cash = float(config.initial_capital)
        self.positions: dict[str, Position] = {}
        self.realized_pnl = 0.0
        self.peak_equity = float(config.initial_capital)
        self.turnover = 0.0
        self.exposure_observations: list[float] = []

    def position_value(self, prices: dict[str, float]) -> float:
        value = 0.0
        for symbol, position in self.positions.items():
            price = prices.get(symbol, position.entry_price)
            pnl = (price - position.entry_price) * position.quantity * (1 if position.direction == "long" else -1)
            value += position.reserved_capital + pnl
        return value

    def equity(self, prices: dict[str, float]) -> float: return self.cash + self.position_value(prices)

    def size_position(self, price: float, stop_price: float, atr: float | None = None, equity: float | None = None) -> tuple[int, str | None]:
        cfg = self.config; equity = equity if equity is not None else self.cash + sum(p.reserved_capital for p in self.positions.values())
        max_value = min(self.cash, equity * cfg.max_position_value_pct)
        method = cfg.position_sizing_method
        if method == "fixed_quantity": qty = cfg.fixed_quantity
        elif method == "fixed_value": qty = int(cfg.fixed_position_value / price)
        elif method == "equal_weight": qty = int((equity / cfg.max_positions) / price)
        elif method == "risk_percent":
            distance = abs(price - stop_price)
            if distance <= 0: return 0, "invalid stop distance"
            qty = int((equity * cfg.risk_per_trade_pct) / distance)
        elif method == "atr_risk":
            if atr is None or not math.isfinite(atr) or atr <= 0:
                if cfg.missing_atr_policy == "fallback_equal_weight": qty = int((equity / cfg.max_positions) / price)
                else: return 0, "ATR_14 missing or invalid"
            else: qty = int((equity * cfg.risk_per_trade_pct) / (2.0 * atr))
        else: return 0, "unknown sizing method"
        qty = int(qty * cfg.position_size_multiplier)
        qty = min(qty, int(max_value / price), int(self.cash / price))
        return (qty, None) if qty > 0 else (0, "calculated quantity is zero")

    def can_open(self, symbol: str) -> tuple[bool, str | None]:
        if len(self.positions) >= self.config.max_positions: return False, "maximum positions reached"
        if symbol in self.positions and not self.config.allow_multiple_positions_per_symbol: return False, "duplicate symbol position"
        return True, None
