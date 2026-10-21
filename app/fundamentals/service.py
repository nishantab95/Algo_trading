from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.discovery.providers import parse_instrument
from app.fundamentals.analysis import assess
from app.fundamentals.providers import FundamentalDataProvider, FundamentalProviderError, YahooFundamentalProvider


STATEMENT_FRESHNESS_DAYS = 7
VALUATION_FRESHNESS_DAYS = 1


class FundamentalService:
    """On-demand, atomic snapshot cache; no price download or trade action occurs here."""

    def __init__(self, storage_dir: str | Path, provider: FundamentalDataProvider | None = None) -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.provider = provider or YahooFundamentalProvider()
        self._lock = threading.RLock()

    @staticmethod
    def _filename(canonical_symbol: str) -> str:
        return canonical_symbol.replace(":", "__") + ".json"

    def _path(self, canonical_symbol: str) -> Path:
        return self.storage_dir / self._filename(canonical_symbol)

    def _read(self, canonical_symbol: str) -> dict | None:
        path = self._path(canonical_symbol)
        if not path.exists(): return None
        try: return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return None

    def _write(self, canonical_symbol: str, record: dict) -> None:
        path = self._path(canonical_symbol); temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, sort_keys=True, indent=2), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _age_days(record: dict) -> float | None:
        try: return (datetime.now(timezone.utc) - datetime.fromisoformat(record["last_successful_refresh"])).total_seconds() / 86400
        except (KeyError, TypeError, ValueError): return None

    def _present(self, record: dict, stale: bool = False, valuation_stale: bool = False) -> dict:
        assessment = dict(record.get("assessment", {})); warnings = list(assessment.get("warnings", []))
        if stale: warnings.append("Fundamental snapshot is stale or refresh failed; last valid values are retained for reference.")
        if valuation_stale: warnings.append("Price-sensitive Yahoo valuation multiples are stale or could not be refreshed; statement-based health remains available.")
        assessment["warnings"] = warnings
        return {"symbol": record.get("symbol"), "snapshot": record.get("snapshot"), "assessment": assessment, "freshness": "stale" if stale else "fresh", "valuation_freshness": "stale" if valuation_stale else "fresh", "last_successful_refresh": record.get("last_successful_refresh"), "last_attempted_refresh": record.get("last_attempted_refresh"), "valuation_last_successful_refresh": record.get("valuation_last_successful_refresh"), "valuation_last_attempted_refresh": record.get("valuation_last_attempted_refresh"), "last_error": record.get("last_error")}

    def cached(self, canonical_symbol: str) -> dict:
        instrument = parse_instrument(canonical_symbol)
        record = self._read(instrument.canonical_symbol)
        if record is None:
            return {"symbol": instrument.canonical_symbol, "snapshot": None, "assessment": {"health": "UNKNOWN", "valuation": {"classification": "UNKNOWN", "raw_multiples": {}}, "reasons": ["Fundamental data has not been retrieved for this company."], "warnings": ["Select Refresh Fundamentals to retrieve on-demand Yahoo data."], "checks": [], "completeness": "insufficient"}, "freshness": "missing", "valuation_freshness": "missing", "last_successful_refresh": None, "last_attempted_refresh": None, "valuation_last_successful_refresh": None, "valuation_last_attempted_refresh": None, "last_error": None}
        statement_age = self._age_days(record)
        valuation_age = self._age_days({"last_successful_refresh": record.get("valuation_last_successful_refresh")})
        return self._present(record, stale=(statement_age is None or statement_age > STATEMENT_FRESHNESS_DAYS), valuation_stale=(valuation_age is None or valuation_age > VALUATION_FRESHNESS_DAYS))

    def get(self, canonical_symbol: str, refresh: bool = False) -> dict:
        instrument = parse_instrument(canonical_symbol)
        with self._lock:
            existing = self._read(instrument.canonical_symbol)
            age = self._age_days(existing) if existing else None
            if existing and not refresh and age is not None and age <= STATEMENT_FRESHNESS_DAYS:
                valuation_age = self._age_days({"last_successful_refresh": existing.get("valuation_last_successful_refresh")})
                if valuation_age is not None and valuation_age <= VALUATION_FRESHNESS_DAYS:
                    return self._present(existing)
                attempted_valuation = datetime.now(timezone.utc).isoformat()
                try:
                    update = self.provider.fetch_valuation(instrument)
                    if not isinstance(update, dict) or not isinstance(update.get("valuation"), dict):
                        raise FundamentalProviderError("Provider does not support a valid valuation-only refresh.")
                    existing["snapshot"]["valuation"] = update["valuation"]
                    existing["snapshot"]["valuation_retrieved_at"] = update.get("retrieved_at", attempted_valuation)
                    existing["assessment"] = assess(existing["snapshot"])
                    existing["valuation_last_successful_refresh"] = attempted_valuation
                    existing["valuation_last_attempted_refresh"] = attempted_valuation
                    existing["last_error"] = None
                    self._write(instrument.canonical_symbol, existing)
                    return self._present(existing)
                except Exception as exc:
                    existing["valuation_last_attempted_refresh"] = attempted_valuation
                    existing["last_error"] = str(exc)
                    self._write(instrument.canonical_symbol, existing)
                    return self._present(existing, valuation_stale=True)
            attempted = datetime.now(timezone.utc).isoformat()
            try:
                snapshot = self.provider.fetch(instrument)
                if not isinstance(snapshot, dict) or snapshot.get("symbol") != instrument.canonical_symbol:
                    raise FundamentalProviderError("Provider returned an invalid or mismatched fundamental snapshot.")
                result = {"symbol": instrument.canonical_symbol, "snapshot": snapshot, "assessment": assess(snapshot), "last_successful_refresh": attempted, "last_attempted_refresh": attempted, "valuation_last_successful_refresh": attempted, "valuation_last_attempted_refresh": attempted, "last_error": None}
                self._write(instrument.canonical_symbol, result)
                return self._present(result)
            except Exception as exc:
                if existing:
                    existing["last_attempted_refresh"] = attempted; existing["last_error"] = str(exc)
                    self._write(instrument.canonical_symbol, existing)
                    return self._present(existing, stale=True)
                return {"symbol": instrument.canonical_symbol, "snapshot": None, "assessment": {"health": "UNKNOWN", "valuation": {"classification": "UNKNOWN", "raw_multiples": {}}, "reasons": ["Fundamental data could not be retrieved."], "warnings": [str(exc)], "checks": [], "completeness": "insufficient"}, "freshness": "failed", "valuation_freshness": "missing", "last_successful_refresh": None, "last_attempted_refresh": attempted, "valuation_last_successful_refresh": None, "valuation_last_attempted_refresh": None, "last_error": str(exc)}
