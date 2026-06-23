from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    name: str
    category: str
    direction: str
    timeframe: str
    description: str
    entry_rule_description: str
    exit_rule_description: str = "Managed by paper risk exits; research signal has no lifecycle exit."
    risk_rule_description: str = "Subject to the Stage 1 RiskManager."
    parameters: dict[str, Any] = field(default_factory=dict)
    explanation_template: str = "{name} emitted {direction} conditions on {timeframe} data."
    enabled: bool = True
    status: str = "live_disabled"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
