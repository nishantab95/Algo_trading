from __future__ import annotations

from app.brokers.broker_errors import BrokerModeError, BrokerPermissionError
from app.brokers.broker_modes import allows_readonly_broker, normalize_mode, requires_reconciliation


class LiveGuard:
    def __init__(self, reconciliation_service=None) -> None:
        self.reconciliation_service = reconciliation_service

    def assert_live_order_blocked(self) -> bool:
        raise BrokerPermissionError("Live orders are blocked in Stage 7 Batch 3.")

    def assert_broker_readonly_allowed(self, mode) -> bool:
        broker_mode = normalize_mode(mode)
        if not allows_readonly_broker(broker_mode):
            raise BrokerModeError(f"Broker read-only access is not allowed for mode '{broker_mode.value}'.")
        return True

    def assert_reconciliation_required(self, mode) -> bool:
        return requires_reconciliation(mode)

    def assert_reconciliation_passing(self, mode) -> bool:
        if not requires_reconciliation(mode):
            return True
        if self.reconciliation_service is None or not self.reconciliation_service.is_reconciliation_passing(mode):
            raise BrokerPermissionError("A passing broker reconciliation is required before live-like readiness can proceed.")
        return True

    def assert_assistant_cannot_live_trade(self, actor) -> bool:
        if str(actor or "").strip().lower() == "assistant":
            raise BrokerPermissionError("Assistant actors cannot place, approve, or route live orders.")
        return True

    def assert_tiny_live_not_ready_yet(self) -> bool:
        raise BrokerPermissionError("tiny_live is not ready in Stage 7 Batch 3; unlock, risk limits, and kill switch are not implemented yet.")

