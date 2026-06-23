from __future__ import annotations

from dataclasses import dataclass

from app.core.config import ASSISTANT_SETTINGS


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool = ASSISTANT_SETTINGS.enabled
    provider: str = ASSISTANT_SETTINGS.provider
    base_url: str = ASSISTANT_SETTINGS.base_url
    model: str = ASSISTANT_SETTINGS.model
    timeout_seconds: float = ASSISTANT_SETTINGS.timeout_seconds
    max_context_messages: int = ASSISTANT_SETTINGS.max_context_messages
    approval_required: bool = ASSISTANT_SETTINGS.approval_required

