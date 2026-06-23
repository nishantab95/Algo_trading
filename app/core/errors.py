class AppError(Exception):
    """Base error safe to expose through the local JSON API."""


class RiskRejected(AppError):
    pass


class BrokerError(AppError):
    pass


class ValidationError(AppError):
    pass
