from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

import pandas as pd


class ProviderError(RuntimeError):
    """A provider request could not supply usable market data."""


@dataclass(frozen=True)
class Instrument:
    exchange: str
    symbol: str
    provider_symbol: str
    currency: str
    timezone: str

    @property
    def canonical_symbol(self) -> str:
        return f"{self.exchange}:{self.symbol}"


EXCHANGE_DETAILS = {
    "NSE": {"suffix": ".NS", "currency": "INR", "timezone": "Asia/Kolkata"},
    "NASDAQ": {"suffix": "", "currency": "USD", "timezone": "America/New_York"},
    "NYSE": {"suffix": "", "currency": "USD", "timezone": "America/New_York"},
    "TSE": {"suffix": ".T", "currency": "JPY", "timezone": "Asia/Tokyo"},
}


def parse_instrument(value: str, exchange: str | None = None) -> Instrument:
    raw = str(value or "").strip().upper()
    if ":" in raw:
        supplied_exchange, symbol = raw.split(":", 1)
        exchange = supplied_exchange
    else:
        symbol = raw
    exchange = str(exchange or "").strip().upper()
    symbol = symbol.strip().upper()
    if exchange not in EXCHANGE_DETAILS:
        raise ValueError("Supported exchanges are NSE, NASDAQ, NYSE, and TSE.")
    if not symbol or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for char in symbol):
        raise ValueError("A stock symbol may contain only letters, numbers, dots, and hyphens.")
    detail = EXCHANGE_DETAILS[exchange]
    provider_symbol = f"{symbol}{detail['suffix']}"
    return Instrument(exchange, symbol, provider_symbol, detail["currency"], detail["timezone"])


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def fetch_daily(self, instrument: Instrument, start: date, end: date) -> pd.DataFrame:
        """Return daily OHLCV data for the inclusive requested date range."""


class YahooFinanceProvider(MarketDataProvider):
    name = "yahoo"

    def fetch_daily(self, instrument: Instrument, start: date, end: date) -> pd.DataFrame:
        try:
            import yfinance as yf

            return yf.download(
                instrument.provider_symbol,
                start=start.isoformat(),
                end=end.isoformat(),
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
            )
        except Exception as exc:  # yfinance exposes provider/network failures as varied exceptions.
            raise ProviderError(f"Yahoo Finance request failed for {instrument.provider_symbol}: {exc}") from exc
