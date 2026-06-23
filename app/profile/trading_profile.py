from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class TradingProfile:
    profile_name: str = "My NSE Research Profile"
    preferred_market: str = "NSE"
    preferred_timeframe: str = "daily"
    capital_base: float = 1_000_000
    paper_capital: float = 1_000_000
    risk_per_trade_pct: float = 1.0
    max_daily_loss: float = 25_000
    max_open_positions: int = 10
    preferred_strategy_categories: list[str] = field(default_factory=list)
    disabled_strategy_categories: list[str] = field(default_factory=list)
    watchlists: list[str] = field(default_factory=list)
    favorite_symbols: list[str] = field(default_factory=list)
    favorite_strategies: list[str] = field(default_factory=list)
    default_backtest_start: str | None = None
    default_backtest_end: str | None = None
    default_execution_model: str = "next_open"
    default_cost_model: str = "india_equity_delivery_approx"
    learning_level: str = "intermediate"
    notes: str = ""

    def to_dict(self): return asdict(self)
