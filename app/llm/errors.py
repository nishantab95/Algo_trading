class LLMError(RuntimeError):
    """Base error for local LLM communication."""


class LLMOfflineError(LLMError):
    """Raised when LM Studio is disabled or unreachable."""
