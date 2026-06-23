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


@dataclass(frozen=True)
class CatalogStrategy:
    strategy_id: str
    name: str
    category: str
    subcategory: str
    direction: str
    timeframe: str = "daily"
    asset_class: str = "equity"
    status: str = "active"
    description: str = ""
    learning_note: str = "Research candidate; validate across regimes and costs."
    data_requirements: dict[str, list[str]] = field(default_factory=lambda: {"required_columns": ["Open","High","Low","Close","Volume"], "optional_columns": []})
    parameters: dict[str, Any] = field(default_factory=dict)
    entry: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)
    exit: dict[str, Any] = field(default_factory=lambda: {"any": [{"stop_loss_pct": 5}, {"trailing_stop_pct": 7}]})
    risk: dict[str, Any] = field(default_factory=lambda: {"max_holding_bars": 60, "max_position_value_pct": 10})
    explanation_template: str = "{name}: {passed_rules}."
    tags: tuple[str, ...] = ()
    unsupported_reason: str | None = None
    enabled: bool = False

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    status: str
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]: return asdict(self)
