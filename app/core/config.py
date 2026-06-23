from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Stage1Config:
    live_trading_enabled: bool = _env_bool("ALGO_LIVE_TRADING_ENABLED", False)
    kill_switch: bool = _env_bool("ALGO_KILL_SWITCH", False)
    max_order_value: float = float(os.getenv("ALGO_MAX_ORDER_VALUE", "250000"))
    max_daily_loss: float = float(os.getenv("ALGO_MAX_DAILY_LOSS", "25000"))
    duplicate_positions_allowed: bool = False


SETTINGS = Stage1Config()
