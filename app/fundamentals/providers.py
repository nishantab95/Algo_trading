from __future__ import annotations

import math
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from time import sleep

import pandas as pd

from app.discovery.providers import Instrument


class FundamentalProviderError(RuntimeError):
    pass


CAPABILITIES = {
    "annual_statements": True, "quarterly_statements": True,
    "snapshot_valuation": True, "filing_dates": False,
}

FIELD_ALIASES = {
    "revenue": ("Total Revenue", "Operating Revenue"),
    "gross_profit": ("Gross Profit",),
    "operating_income": ("Operating Income", "EBIT", "Normalized EBIT"),
    "net_income": ("Net Income", "Net Income Common Stockholders", "Net Income Including Noncontrolling Interests"),
    "total_assets": ("Total Assets",),
    "equity": ("Stockholders Equity", "Stockholders' Equity", "Total Stockholder Equity", "Common Stock Equity"),
    "total_debt": ("Total Debt", "Net Debt", "Long Term Debt And Capital Lease Obligation"),
    "cash": ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash Financial"),
    "current_assets": ("Current Assets", "Total Current Assets"),
    "current_liabilities": ("Current Liabilities", "Total Current Liabilities"),
    "interest_expense": ("Interest Expense", "Interest Expense Non Operating"),
    "operating_cash_flow": ("Operating Cash Flow", "Total Cash From Operating Activities", "Cash Flow From Continuing Operating Activities"),
    "capital_expenditure": ("Capital Expenditure", "Capital Expenditures"),
}

INFO_FIELDS = {
    "pe": ("trailingPE", "forwardPE"), "pb": ("priceToBook",),
    "ps": ("priceToSalesTrailing12Months",), "ev_ebitda": ("enterpriseToEbitda",),
    "market_cap": ("marketCap",),
}


def _number(value) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _period(value) -> str | None:
    timestamp = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(timestamp) else timestamp.date().isoformat()


def _statement_records(frame: pd.DataFrame | None, frequency: str) -> dict[str, dict]:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return {}
    output: dict[str, dict] = {}
    labels = {str(index).strip(): index for index in frame.index}
    for column in frame.columns:
        period = _period(column)
        if not period:
            continue
        record = output.setdefault(period, {"period_end": period, "frequency": frequency, "metrics": {}, "source_fields": {}})
        for metric, aliases in FIELD_ALIASES.items():
            source = next((alias for alias in aliases if alias in labels), None)
            if source is None:
                continue
            value = _number(frame.at[labels[source], column])
            if value is not None:
                record["metrics"][metric] = value
                record["source_fields"][metric] = source
    return output


def _valuation_from_info(info: dict) -> dict:
    """Extract provider-supplied snapshot multiples without deriving a valuation score."""
    valuation = {}
    for metric, aliases in INFO_FIELDS.items():
        value = next((_number(info.get(alias)) for alias in aliases if _number(info.get(alias)) is not None), None)
        if value is not None:
            valuation[metric] = value
    return valuation


def normalize_yahoo_payload(instrument: Instrument, info: dict | None, income, balance, cashflow, quarterly_income=None, quarterly_balance=None, quarterly_cashflow=None) -> dict:
    """Normalise Yahoo frames without inventing units, filing dates, or currencies."""
    info = info if isinstance(info, dict) else {}
    currency = info.get("financialCurrency") or info.get("currency")
    annual: dict[str, dict] = {}
    quarterly: dict[str, dict] = {}
    for statement in (_statement_records(income, "annual"), _statement_records(balance, "annual"), _statement_records(cashflow, "annual")):
        for period, record in statement.items():
            target = annual.setdefault(period, {"period_end": period, "frequency": "annual", "metrics": {}, "source_fields": {}})
            target["metrics"].update(record["metrics"]); target["source_fields"].update(record["source_fields"])
    for statement in (_statement_records(quarterly_income, "quarterly"), _statement_records(quarterly_balance, "quarterly"), _statement_records(quarterly_cashflow, "quarterly")):
        for period, record in statement.items():
            target = quarterly.setdefault(period, {"period_end": period, "frequency": "quarterly", "metrics": {}, "source_fields": {}})
            target["metrics"].update(record["metrics"]); target["source_fields"].update(record["source_fields"])
    valuation = _valuation_from_info(info)
    return {
        "symbol": instrument.canonical_symbol, "provider": "yahoo", "provider_symbol": instrument.provider_symbol,
        "identity": {"name": info.get("longName") or info.get("shortName") or info.get("displayName"), "sector": info.get("sector"), "industry": info.get("industry"), "quote_currency": info.get("currency"), "statement_currency": currency, "quote_type": info.get("quoteType")},
        "annual": sorted(annual.values(), key=lambda row: row["period_end"], reverse=True),
        "quarterly": sorted(quarterly.values(), key=lambda row: row["period_end"], reverse=True),
        "valuation": valuation, "capabilities": dict(CAPABILITIES),
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "data_quality_warnings": [] if annual else ["Yahoo returned no annual financial statements."],
        "units": "provider-reported statement currency units; no scaling or currency conversion applied",
    }


class FundamentalDataProvider(ABC):
    name: str
    capabilities: dict

    @abstractmethod
    def fetch(self, instrument: Instrument) -> dict:
        """Return a normalised current fundamental snapshot for one canonical symbol."""

    def fetch_valuation(self, instrument: Instrument) -> dict | None:
        """Optionally refresh only price-sensitive provider snapshot multiples."""
        return None


class YahooFundamentalProvider(FundamentalDataProvider):
    name = "yahoo"
    capabilities = CAPABILITIES
    retry_attempts = 2
    retry_delay_seconds = 0.25

    def _retry(self, operation, request_name: str):
        error = None
        for attempt in range(self.retry_attempts):
            try:
                return operation()
            except Exception as exc:
                error = exc
                if attempt + 1 < self.retry_attempts:
                    sleep(self.retry_delay_seconds)
        raise FundamentalProviderError(f"Yahoo Finance {request_name} request failed: {error}") from error

    def fetch(self, instrument: Instrument) -> dict:
        def request():
            import yfinance as yf
            ticker = yf.Ticker(instrument.provider_symbol)
            return normalize_yahoo_payload(
                instrument, ticker.info, ticker.income_stmt, ticker.balance_sheet, ticker.cashflow,
                ticker.quarterly_income_stmt, ticker.quarterly_balance_sheet, ticker.quarterly_cashflow,
            )
        return self._retry(request, f"fundamental data for {instrument.provider_symbol}")

    def fetch_valuation(self, instrument: Instrument) -> dict:
        def request():
            import yfinance as yf
            info = yf.Ticker(instrument.provider_symbol).info
            if not isinstance(info, dict):
                raise FundamentalProviderError("Yahoo returned an invalid valuation snapshot.")
            return {"valuation": _valuation_from_info(info), "retrieved_at": datetime.now(timezone.utc).isoformat()}
        return self._retry(request, f"valuation for {instrument.provider_symbol}")
