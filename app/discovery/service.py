from __future__ import annotations

import json
import math
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from app.discovery.providers import Instrument, MarketDataProvider, ProviderError, YahooFinanceProvider, parse_instrument


SEED_UNIVERSES = {
    "nse": ("NSE:RELIANCE", "NSE:TCS", "NSE:INFY"),
    "us": ("NASDAQ:AAPL", "NASDAQ:MSFT", "NYSE:BRK-B"),
}
LOOKBACK_YEARS = {"1y": 1, "3y": 3, "5y": 5}
OVERLAP_DAYS = 5
STALE_AFTER_DAYS = 7


class DiscoveryDataService:
    """Provider-neutral local daily-candle cache for the Discovery workflow.

    Yahoo data is stored unadjusted (``auto_adjust=False``).  Its optional
    ``Adj Close`` column is retained separately, so later research can choose a
    documented adjustment policy without changing the raw cache.
    """

    def __init__(self, storage_dir: str | Path, provider: MarketDataProvider | None = None, *, sleep=time.sleep) -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.provider = provider or YahooFinanceProvider()
        self._sleep = sleep
        self.catalog_path = self.storage_dir / "catalog.json"

    def _catalog(self) -> dict:
        if not self.catalog_path.exists():
            return {"custom_symbols": [], "symbols": {}}
        try:
            return json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"custom_symbols": [], "symbols": {}}

    def _save_catalog(self, catalog: dict) -> None:
        temporary = self.catalog_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(catalog, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.catalog_path)

    @staticmethod
    def _file_name(instrument: Instrument) -> str:
        return re.sub(r"[^A-Z0-9_.-]", "_", instrument.canonical_symbol.replace(":", "__")) + ".csv"

    def _cache_path(self, instrument: Instrument) -> Path:
        return self.storage_dir / self._file_name(instrument)

    @staticmethod
    def _normalize(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
        if frame is None or frame.empty:
            return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"]), 0
        data = frame.copy()
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        data.columns = [str(column).strip().title() for column in data.columns]
        if "Date" not in data.columns:
            data = data.reset_index().rename(columns={data.index.name or "index": "Date"})
        required = ["Date", "Open", "High", "Low", "Close", "Volume"]
        if any(column not in data.columns for column in required):
            raise ProviderError("Provider response is missing required daily OHLCV columns.")
        columns = required + (["Adj Close"] if "Adj Close" in data.columns else [])
        data = data[columns].copy()
        data["Date"] = pd.to_datetime(data["Date"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
        for column in ("Open", "High", "Low", "Close", "Volume"):
            data[column] = pd.to_numeric(data[column], errors="coerce")
        valid = (
            data["Date"].notna()
            & data[["Open", "High", "Low", "Close", "Volume"]].notna().all(axis=1)
            & (data[["Open", "High", "Low", "Close"]] > 0).all(axis=1)
            & (data["Volume"] >= 0)
            & (data["High"] >= data[["Open", "Close", "Low"]].max(axis=1))
            & (data["Low"] <= data[["Open", "Close", "High"]].min(axis=1))
        )
        invalid = int((~valid).sum())
        data = data.loc[valid].drop_duplicates("Date", keep="last").sort_values("Date")
        data["Date"] = data["Date"].dt.strftime("%Y-%m-%d")
        return data, invalid

    def _read_cache(self, instrument: Instrument) -> pd.DataFrame:
        path = self._cache_path(instrument)
        if not path.exists():
            return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])
        try:
            return self._normalize(pd.read_csv(path))[0]
        except (OSError, ValueError, ProviderError):
            return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])

    def _universe(self, name: str) -> list[Instrument]:
        catalog = self._catalog()
        if name == "custom":
            items = catalog["custom_symbols"]
        elif name in SEED_UNIVERSES:
            items = SEED_UNIVERSES[name]
        else:
            raise ValueError("Universe must be nse, us, or custom.")
        return [parse_instrument(item) for item in items]

    def list_symbols(self, universe: str) -> list[dict]:
        catalog = self._catalog()
        rows = []
        for instrument in self._universe(universe):
            record = catalog["symbols"].get(instrument.canonical_symbol, {})
            rows.append({
                "symbol": instrument.canonical_symbol,
                "provider_symbol": instrument.provider_symbol,
                "exchange": instrument.exchange,
                "currency": instrument.currency,
                "timezone": instrument.timezone,
                "source": record.get("source", self.provider.name),
                "latest_date": record.get("latest_date"),
                "last_updated": record.get("last_updated"),
                "status": record.get("status", "missing"),
            })
        return rows

    def cache_metadata(self, value: str) -> dict:
        """Describe one managed cache without exposing machine-specific paths."""
        instrument = parse_instrument(value)
        catalog = self._catalog()
        record = catalog["symbols"].get(instrument.canonical_symbol, {})
        cached = self._read_cache(instrument)
        warnings = []
        if record.get("status") in {"failed", "stale", "incomplete", "missing"}:
            warnings.append(f"Cache status: {record['status']}.")
        if record.get("error"):
            warnings.append(str(record["error"]))
        return {
            "symbol": instrument.canonical_symbol,
            "exchange": instrument.exchange,
            "provider_symbol": instrument.provider_symbol,
            "source": record.get("source", self.provider.name),
            "adjustment": record.get("adjustment", "unadjusted OHLCV; Yahoo Adj Close retained when supplied"),
            "cache_format": "csv",
            "status": record.get("status", "missing"),
            "candles": int(len(cached)),
            "earliest_date": str(cached["Date"].iloc[0]) if not cached.empty else None,
            "latest_date": str(cached["Date"].iloc[-1]) if not cached.empty else None,
            "data_quality_warnings": warnings,
        }

    def add_custom_symbol(self, value: str, exchange: str | None = None) -> dict:
        instrument = parse_instrument(value, exchange)
        catalog = self._catalog()
        symbols = set(catalog["custom_symbols"])
        symbols.add(instrument.canonical_symbol)
        catalog["custom_symbols"] = sorted(symbols)
        self._save_catalog(catalog)
        return self.list_symbols("custom")[-1] if len(catalog["custom_symbols"]) == 1 else next(
            row for row in self.list_symbols("custom") if row["symbol"] == instrument.canonical_symbol
        )

    def remove_custom_symbol(self, value: str) -> None:
        instrument = parse_instrument(value)
        catalog = self._catalog()
        catalog["custom_symbols"] = [item for item in catalog["custom_symbols"] if item != instrument.canonical_symbol]
        self._save_catalog(catalog)

    @staticmethod
    def _start_for_lookback(lookback: str, today: date) -> date:
        if lookback not in LOOKBACK_YEARS:
            raise ValueError("Lookback must be 1y, 3y, or 5y.")
        return today - timedelta(days=365 * LOOKBACK_YEARS[lookback])

    @staticmethod
    def _is_stale(latest: str | None, today: date) -> bool:
        if not latest:
            return True
        return (today - date.fromisoformat(latest)).days > STALE_AFTER_DAYS

    def update(self, universe: str, lookback: str) -> dict:
        today = date.today()
        instruments = self._universe(universe)
        if len(instruments) > 50:
            raise ValueError("Discovery updates are limited to 50 symbols per request.")
        report = {"provider": self.provider.name, "universe": universe, "lookback": lookback, "succeeded": [], "failed": [], "skipped": [], "stale": []}
        for index, instrument in enumerate(instruments):
            result = self._update_instrument(instrument, lookback, today)
            report[{"success": "succeeded", "failed": "failed", "skipped": "skipped"}[result["outcome"]]].append(result)
            if result["stale"]:
                report["stale"].append(instrument.canonical_symbol)
            if index < len(instruments) - 1:
                self._sleep(0.15)
        report["total"] = len(instruments)
        return report

    def _update_instrument(self, instrument: Instrument, lookback: str, today: date) -> dict:
        cached = self._read_cache(instrument)
        path = self._cache_path(instrument)
        start = self._start_for_lookback(lookback, today)
        if not cached.empty:
            latest = date.fromisoformat(str(cached["Date"].iloc[-1]))
            start = max(start, latest - timedelta(days=OVERLAP_DAYS))
        response = None
        error = None
        for attempt in range(2):
            try:
                response = self.provider.fetch_daily(instrument, start, today + timedelta(days=1))
                break
            except ProviderError as exc:
                error = str(exc)
                if attempt == 0:
                    self._sleep(0.25)
        catalog = self._catalog()
        record = catalog["symbols"].get(instrument.canonical_symbol, {})
        if response is None:
            record.update({"status": "failed", "error": error, "last_attempt": datetime.now(timezone.utc).isoformat()})
            catalog["symbols"][instrument.canonical_symbol] = record
            self._save_catalog(catalog)
            latest = str(cached["Date"].iloc[-1]) if not cached.empty else None
            return {"symbol": instrument.canonical_symbol, "outcome": "failed", "error": error, "latest_date": latest, "stale": self._is_stale(latest, today)}
        fresh, invalid_rows = self._normalize(response)
        merged = pd.concat([cached, fresh], ignore_index=True)
        merged, _ = self._normalize(merged)
        latest = str(merged["Date"].iloc[-1]) if not merged.empty else None
        if merged.empty:
            outcome, status = "skipped", "missing"
        elif fresh.empty:
            outcome, status = "skipped", "stale" if self._is_stale(latest, today) else "current"
        else:
            outcome = "success"
            status = "stale" if self._is_stale(latest, today) else "incomplete" if invalid_rows else "current"
            temporary = path.with_suffix(".tmp")
            merged.to_csv(temporary, index=False)
            temporary.replace(path)
        record.update({
            "status": status,
            "error": None,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "latest_date": latest,
            "source": self.provider.name,
            "provider_symbol": instrument.provider_symbol,
            "currency": instrument.currency,
            "timezone": instrument.timezone,
            "adjustment": "unadjusted OHLCV; Yahoo Adj Close retained when supplied",
        })
        catalog["symbols"][instrument.canonical_symbol] = record
        self._save_catalog(catalog)
        return {"symbol": instrument.canonical_symbol, "outcome": outcome, "latest_date": latest, "rows": int(len(merged)), "new_rows": int(len(fresh)), "invalid_rows": invalid_rows, "stale": self._is_stale(latest, today)}
