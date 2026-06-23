from __future__ import annotations

from dataclasses import dataclass, replace

from app.backtesting.models import CostBreakdown


@dataclass(frozen=True)
class FeeSchedule:
    name: str
    brokerage_bps: float = 0.0
    flat_brokerage: float = 0.0
    brokerage_cap: float = 20.0
    stt_bps_buy: float = 0.0
    stt_bps_sell: float = 10.0
    exchange_txn_bps: float = 0.0297
    sebi_bps: float = 0.001
    stamp_duty_bps_buy: float = 1.5
    gst_pct_on_brokerage_and_txn: float = 18.0


PRESETS = {
    "zero_cost_research": FeeSchedule("zero_cost_research", stt_bps_sell=0, exchange_txn_bps=0, sebi_bps=0, stamp_duty_bps_buy=0, gst_pct_on_brokerage_and_txn=0),
    "india_equity_intraday_approx": FeeSchedule("india_equity_intraday_approx", brokerage_bps=3.0, stt_bps_sell=2.5, stamp_duty_bps_buy=0.3),
    "india_equity_delivery_approx": FeeSchedule("india_equity_delivery_approx", brokerage_bps=0.0, stt_bps_buy=10.0, stt_bps_sell=10.0, stamp_duty_bps_buy=1.5),
}


class CostModel:
    """Configurable approximation. Verify actual broker/exchange charges before use."""

    def __init__(self, schedule: FeeSchedule) -> None: self.schedule = schedule

    @classmethod
    def named(cls, name: str, custom: FeeSchedule | None = None) -> "CostModel":
        if name == "custom" and custom: return cls(custom)
        if name not in PRESETS: raise ValueError(f"Unknown cost model: {name}")
        return cls(PRESETS[name])

    def calculate(self, side: str, quantity: int, reference_price: float, fill_price: float, spread_bps: float = 0.0) -> CostBreakdown:
        side = side.upper(); turnover = abs(fill_price * quantity)
        brokerage = min(turnover * self.schedule.brokerage_bps / 10_000 + self.schedule.flat_brokerage, self.schedule.brokerage_cap) if (self.schedule.brokerage_bps or self.schedule.flat_brokerage) else 0.0
        stt_bps = self.schedule.stt_bps_buy if side == "BUY" else self.schedule.stt_bps_sell
        stt = turnover * stt_bps / 10_000
        exchange = turnover * self.schedule.exchange_txn_bps / 10_000
        sebi = turnover * self.schedule.sebi_bps / 10_000
        stamp = turnover * self.schedule.stamp_duty_bps_buy / 10_000 if side == "BUY" else 0.0
        gst = (brokerage + exchange) * self.schedule.gst_pct_on_brokerage_and_txn / 100
        taxes = stt + exchange + sebi + stamp + gst
        adverse = (fill_price - reference_price) * quantity if side == "BUY" else (reference_price - fill_price) * quantity
        spread = turnover * spread_bps / 10_000 / 2.0
        return CostBreakdown(round(brokerage, 4), round(taxes, 4), round(max(adverse - spread, 0.0), 4), round(spread, 4), round(brokerage + taxes + max(adverse, 0.0), 4))
