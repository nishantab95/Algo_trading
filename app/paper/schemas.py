from __future__ import annotations

from dataclasses import asdict, dataclass


ORDER_STATUSES={"draft","pending_approval","approved","submitted","partially_filled","filled","rejected","cancelled","expired","failed"}
ORDER_TYPES={"market","limit","stop","stop_limit"}
PAPER_REVIEW_STATUSES={"not_started","paper_testing","needs_more_data","paused","rejected","candidate_for_tiny_live","archived"}


@dataclass
class PaperRiskSettings:
    max_open_positions: int = 10
    max_position_value_pct: float = 25.0
    max_per_symbol_exposure_pct: float = 25.0
    max_per_strategy_exposure_pct: float = 50.0
    max_daily_loss: float = 25_000.0
    max_weekly_loss: float = 75_000.0
    max_order_value: float = 250_000.0
    allow_duplicate_position: bool = False
    allow_averaging_down: bool = False
    stale_after_seconds: int = 86_400
    minimum_price: float = 0.05
    maximum_price: float = 10_000_000.0
    minimum_liquidity: float = 0.0
    require_stop_for_strategy: bool = False
    kill_switch: bool = False
    slippage_bps: float = 7.0
    spread_bps: float = 2.0
    fee_bps: float = 3.0

    def to_dict(self): return asdict(self)
