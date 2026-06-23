from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    def status(self) -> dict: ...
    def chat(self, messages: list[dict[str, str]]) -> str: ...
