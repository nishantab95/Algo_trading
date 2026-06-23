from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

DirectionMode = Literal["long_only", "short_only", "long_short"]
ExecutionPriceModel = Literal["next_open", "next_close", "signal_close_for_research_only"]


@dataclass
class BacktestConfig:
    strategy_id: str
    symbols: list[str]
    start_date: str | None = None
    end_date: str | None = None
    initial_capital: float = 1_000_000.0
    timeframe: str = "1d"
    direction_mode: DirectionMode = "long_only"
    execution_price_model: ExecutionPriceModel = "next_open"
    max_positions: int = 10
    max_position_value_pct: float = 0.20
    risk_per_trade_pct: float = 0.01
    fixed_position_value: float = 100_000.0
    fixed_quantity: int = 1
    position_sizing_method: str = "risk_percent"
    stop_loss_pct: float = 0.05
    target_pct: float = 0.15
    trailing_stop_pct: float = 0.07
    max_holding_bars: int = 60
    allow_multiple_positions_per_symbol: bool = False
    allow_reentry_same_day: bool = False
    liquidity_filter_enabled: bool = True
    min_avg_volume: float = 100_000.0
    liquidity_order_value_pct: float = 0.02
    min_price: float = 5.0
    max_price: float = 100_000.0
    slippage_bps: float = 7.0
    spread_bps: float = 5.0
    cost_model_name: str = "india_equity_delivery_approx"
    custom_cost_settings: dict[str, float] = field(default_factory=dict)
    benchmark_symbol: str | None = "NIFTY50"
    include_short_borrow_cost_placeholder: bool = False
    missing_atr_policy: str = "reject"
    notes: str = ""
    entry_delay_bars: int = 0
    exit_delay_bars: int = 0
    position_size_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.cost_model_name == "zero_cost_research":
            self.slippage_bps = 0.0
            self.spread_bps = 0.0

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass
class SignalEvent:
    timestamp: Any
    symbol: str
    strategy_id: str
    direction: str
    signal_value: int
    signal_reason: str
    indicator_values: dict[str, float] = field(default_factory=dict)


@dataclass
class OrderEvent:
    timestamp: Any
    symbol: str
    side: str
    quantity: int
    requested_price: float | None = None
    fill_price: float | None = None
    status: str = "PENDING"
    rejection_reason: str | None = None
    slippage: float = 0.0
    costs: float = 0.0
    fill_time: Any | None = None
    signal_time: Any | None = None
    reason: str = ""
    direction: str = "long"


@dataclass
class CostBreakdown:
    brokerage: float = 0.0
    taxes_and_charges: float = 0.0
    slippage_cost: float = 0.0
    spread_cost: float = 0.0
    total_costs: float = 0.0


@dataclass
class Trade:
    symbol: str
    direction: str
    quantity: int
    entry_time: Any
    entry_price: float
    exit_time: Any
    exit_price: float
    stop_loss: float
    target: float
    trailing_stop: float
    exit_reason: str
    gross_pnl: float
    costs: float
    net_pnl: float
    holding_period_bars: int
    mae: float
    mfe: float
    entry_signal_time: Any | None = None
    exit_signal_time: Any | None = None
    entry_reason: str = ""
    return_pct: float = 0.0
    brokerage: float = 0.0
    taxes_and_charges: float = 0.0
    slippage_cost: float = 0.0
    spread_cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        for key in ("entry_time", "exit_time", "entry_signal_time", "exit_signal_time"):
            if row[key] is not None: row[key] = str(row[key])
        return row


@dataclass
class Position:
    symbol: str
    direction: str
    quantity: int
    entry_time: Any
    entry_signal_time: Any
    entry_price: float
    entry_reference_price: float
    entry_costs: CostBreakdown
    reserved_capital: float
    stop_loss: float
    target: float
    trailing_stop_pct: float
    highest_price: float
    lowest_price: float
    bars_held: int = 0
    mae: float = 0.0
    mfe: float = 0.0
    entry_reason: str = ""
    pending_exit_bars: int | None = None
    pending_exit_reason: str | None = None


@dataclass
class PortfolioState:
    timestamp: Any
    cash: float
    positions: dict[str, Position]
    total_equity: float
    realized_pnl: float
    unrealized_pnl: float
    drawdown: float
    exposure: float


@dataclass
class BacktestResult:
    run_id: str
    config: BacktestConfig
    trades: list[Trade]
    orders: list[OrderEvent]
    equity_curve: list[dict[str, Any]]
    daily_summary: list[dict[str, Any]]
    metrics: dict[str, Any]
    metric_breakdown: list[dict[str, Any]]
    warnings: list[str]
    benchmark_metrics: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "config": self.config.to_dict(), "metrics": self.metrics,
                "benchmark_metrics": self.benchmark_metrics, "warnings": self.warnings}
