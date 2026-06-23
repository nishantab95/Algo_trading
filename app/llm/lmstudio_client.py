from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.llm.errors import LLMError, LLMOfflineError
from app.llm.model_config import LLMConfig
from app.llm.prompts import SYSTEM_PROMPT


class LMStudioClient:
    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig()

    def status(self) -> dict:
        base = {"enabled": self.config.enabled, "provider": self.config.provider,
                "base_url": self.config.base_url, "model": self.config.model}
        if not self.config.enabled:
            return {**base, "online": False, "message": "Local assistant is disabled"}
        try:
            self._request("GET", "/models", timeout=min(self.config.timeout_seconds, 2.0))
            return {**base, "online": True, "message": "LM Studio available"}
        except LLMError:
            return {**base, "online": False, "message": "LM Studio unavailable"}

    def chat(self, messages: list[dict[str, str]]) -> str:
        if not self.config.enabled:
            raise LLMOfflineError("Local assistant is disabled")
        payload = {"model": self.config.model, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages[-self.config.max_context_messages:]], "temperature": 0.1}
        result = self._request("POST", "/chat/completions", payload)
        try:
            return str(result["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LM Studio returned an invalid response") from exc

    def _request(self, method: str, path: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.config.base_url + path, data=body, method=method,
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=timeout or self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise LLMOfflineError("LM Studio unavailable") from exc
