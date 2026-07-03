from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.brokers.base import BaseBroker
from app.brokers.broker_modes import BrokerMode, DEFAULT_BROKER_MODE, normalize_mode
from app.brokers.mock_broker import MockBroker
from app.brokers.paper import PaperBroker
from app.db.database import Database
from app.risk.manager import RiskManager


class BrokerFactory:
    """Build only safe broker adapters for Stage 7 Batch 2."""

    def __init__(
        self,
        price_provider: Callable[[str], float] | None = None,
        database: Database | None = None,
        risk_manager: RiskManager | None = None,
        mock_quotes: dict[str, float] | None = None,
        mock_broker: MockBroker | None = None,
        readonly_broker: BaseBroker | None = None,
        paper_broker: PaperBroker | None = None,
        live_broker: BaseBroker | None = None,
    ) -> None:
        self.price_provider = price_provider or (lambda _symbol: 0.0)
        self.database = database
        self.risk_manager = risk_manager
        self.mock_quotes = dict(mock_quotes or {})
        self.mock_broker = mock_broker
        self.readonly_broker = readonly_broker
        self.paper_broker = paper_broker
        self.live_broker = live_broker

    def _paper(self) -> PaperBroker:
        return self.paper_broker or PaperBroker(self.price_provider, self.database, self.risk_manager)

    def paper(self) -> PaperBroker:
        return self._paper()

    def _readonly(self, mode: BrokerMode) -> BaseBroker:
        if self.mock_broker is not None:
            self.mock_broker.mode = mode.value
            return self.mock_broker
        if isinstance(self.readonly_broker, MockBroker):
            self.readonly_broker.mode = mode.value
            return self.readonly_broker
        # Batch 2 deliberately does not expose any raw live broker adapter.
        return MockBroker(mode, connected=True, quotes=self.mock_quotes)

    def create(self, mode: str | BrokerMode | None = None) -> BaseBroker:
        broker_mode = normalize_mode(mode or DEFAULT_BROKER_MODE)
        if broker_mode is BrokerMode.PAPER:
            return self._paper()
        if broker_mode is BrokerMode.LIVE_DISABLED:
            return MockBroker(broker_mode, connected=False, quotes=self.mock_quotes, raise_on_read=True)
        return self._readonly(broker_mode)

