from __future__ import annotations

from app.backtesting.models import BacktestConfig


def validate_config(config: BacktestConfig) -> list[str]:
    errors = []
    if not config.strategy_id: errors.append("strategy_id is required")
    if not config.symbols: errors.append("at least one symbol is required")
    if config.initial_capital <= 0: errors.append("initial_capital must be positive")
    if config.execution_price_model not in {"next_open", "next_close", "signal_close_for_research_only"}: errors.append("invalid execution_price_model")
    if config.direction_mode not in {"long_only", "short_only", "long_short"}: errors.append("invalid direction_mode")
    if config.position_sizing_method not in {"fixed_quantity", "fixed_value", "equal_weight", "risk_percent", "atr_risk"}: errors.append("invalid position_sizing_method")
    if config.max_positions < 1: errors.append("max_positions must be >= 1")
    if not 0 < config.max_position_value_pct <= 1: errors.append("max_position_value_pct must be in (0, 1]")
    if config.stop_loss_pct <= 0: errors.append("stop_loss_pct must be positive")
    if config.max_holding_bars < 1: errors.append("max_holding_bars must be >= 1")
    if config.start_date and config.end_date and config.start_date > config.end_date: errors.append("start_date must not be after end_date")
    return errors


def require_valid_config(config: BacktestConfig) -> None:
    errors = validate_config(config)
    if errors: raise ValueError("; ".join(errors))
