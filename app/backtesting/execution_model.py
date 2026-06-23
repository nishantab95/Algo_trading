from __future__ import annotations

from app.backtesting.models import CostBreakdown


class ExecutionModel:
    def __init__(self, price_model: str, slippage_bps: float, spread_bps: float) -> None:
        self.price_model = price_model; self.slippage_bps = float(slippage_bps); self.spread_bps = float(spread_bps)

    def reference_price(self, bar, same_bar: bool = False) -> float:
        if self.price_model == "next_open" and not same_bar: return float(bar["Open"])
        return float(bar["Close"])

    def fill_price(self, reference_price: float, side: str) -> float:
        adverse_bps = self.slippage_bps + self.spread_bps / 2.0
        direction = 1.0 if side.upper() == "BUY" else -1.0
        return round(reference_price * (1.0 + direction * adverse_bps / 10_000), 4)
