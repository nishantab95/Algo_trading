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


@dataclass(frozen=True)
class AssistantConfig:
    enabled: bool = _env_bool("LLM_ENABLED", True)
    provider: str = os.getenv("LLM_PROVIDER", "lmstudio")
    base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:1234/v1").rstrip("/")
    model: str = os.getenv("LLM_MODEL", "qwen3.5-9b")
    timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    max_context_messages: int = int(os.getenv("LLM_MAX_CONTEXT_MESSAGES", "20"))
    approval_required: bool = _env_bool("LLM_ACTION_APPROVAL_REQUIRED", True)
    rag_enabled: bool = _env_bool("RAG_ENABLED", True)
    rag_mode: str = os.getenv("RAG_MODE", "sqlite_fts")


SETTINGS = Stage1Config()
ASSISTANT_SETTINGS = AssistantConfig()
