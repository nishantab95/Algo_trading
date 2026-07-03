from __future__ import annotations

from app.core.errors import BrokerError as CoreBrokerError


class BrokerError(CoreBrokerError):
    """Base broker error safe to expose through the local API."""


class BrokerModeError(BrokerError, ValueError):
    """Raised when a broker mode is invalid or disallows the requested action."""


class BrokerPermissionError(BrokerError, PermissionError):
    """Raised when an actor or mode is not allowed to mutate broker state."""


class BrokerNotConnectedError(BrokerError):
    """Raised when broker state is requested while the broker is disconnected."""


class BrokerUnavailableError(BrokerError):
    """Raised when a broker read cannot be completed safely."""


class BrokerReadOnlyError(BrokerPermissionError):
    """Raised when mutation is attempted through a read-only broker boundary."""

