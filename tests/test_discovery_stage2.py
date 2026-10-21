from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
from flask import Flask, request

import main
from app.discovery.providers import ProviderError, parse_instrument
from app.discovery.service import DiscoveryDataService
from app.routes.common import failure
from app.routes.discovery_routes import create_discovery_blueprint


def candles(*days: int, close: float = 100.0) -> pd.DataFrame:
    today = date.today()
    return pd.DataFrame(
        {
            "Date": [today - timedelta(days=day) for day in days],
            "Open": [close] * len(days), "High": [close + 2] * len(days),
            "Low": [close - 2] * len(days), "Close": [close] * len(days), "Volume": [1000] * len(days),
        }
    )


class FakeYahoo:
    name = "yahoo"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def fetch_daily(self, instrument, start, end):
        self.calls.append((instrument, start, end))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def service(tmp_path, responses):
    return DiscoveryDataService(tmp_path / "discovery", FakeYahoo(responses), sleep=lambda _seconds: None)


def test_exchange_qualified_symbols_map_to_yahoo_without_collisions():
    assert parse_instrument("NSE:RELIANCE").provider_symbol == "RELIANCE.NS"
    assert parse_instrument("NASDAQ:AAPL").provider_symbol == "AAPL"
    assert parse_instrument("TSE:7203").provider_symbol == "7203.T"
    assert parse_instrument("NSE:ABC").canonical_symbol != parse_instrument("NYSE:ABC").canonical_symbol


def test_first_download_incremental_merge_and_deduplication(tmp_path):
    first = candles(2, 1)
    second = pd.concat([candles(1, close=101), candles(0, close=102)], ignore_index=True)
    discovery = service(tmp_path, [first, second])
    discovery.add_custom_symbol("AAPL", "NASDAQ")

    initial = discovery.update("custom", "1y")
    repeat = discovery.update("custom", "1y")

    assert initial["succeeded"][0]["symbol"] == "NASDAQ:AAPL"
    assert repeat["succeeded"][0]["rows"] == 3
    assert discovery.provider.calls[1][1] > discovery.provider.calls[0][1]
    cached = pd.read_csv(tmp_path / "discovery" / "NASDAQ__AAPL.csv")
    assert len(cached) == 3 and cached["Date"].is_unique


def test_failed_download_preserves_cached_candles_and_records_failure(tmp_path):
    discovery = service(tmp_path, [candles(1), ProviderError("temporary Yahoo outage"), ProviderError("temporary Yahoo outage")])
    discovery.add_custom_symbol("RELIANCE", "NSE")
    discovery.update("custom", "1y")
    path = tmp_path / "discovery" / "NSE__RELIANCE.csv"
    original = path.read_text(encoding="utf-8")

    report = discovery.update("custom", "1y")

    assert report["failed"][0]["symbol"] == "NSE:RELIANCE"
    assert path.read_text(encoding="utf-8") == original
    assert discovery.list_symbols("custom")[0]["status"] == "failed"


def test_invalid_records_are_reported_without_duplicate_candles(tmp_path):
    invalid = candles(1)
    invalid.loc[0, "High"] = -1
    discovery = service(tmp_path, [pd.concat([candles(2), invalid], ignore_index=True)])
    discovery.add_custom_symbol("MSFT", "NASDAQ")

    report = discovery.update("custom", "1y")

    row = report["succeeded"][0]
    assert row["invalid_rows"] == 1
    assert discovery.list_symbols("custom")[0]["status"] == "incomplete"


def test_stale_records_are_visible_in_the_download_report(tmp_path):
    discovery = service(tmp_path, [candles(20)])
    discovery.add_custom_symbol("TCS", "NSE")

    report = discovery.update("custom", "1y")

    assert report["stale"] == ["NSE:TCS"]
    assert discovery.list_symbols("custom")[0]["status"] == "stale"


def test_discovery_http_writes_are_allowed_but_trading_writes_are_blocked(tmp_path, monkeypatch):
    discovery = service(tmp_path, [candles(1)])
    monkeypatch.setattr(main, "_DISCOVERY_DATA", discovery)
    app = main.create_flask_app()
    client = app.test_client()

    added = client.post("/api/discovery/symbols", json={"symbol": "AAPL", "exchange": "NASDAQ"})
    updated = client.post("/api/discovery/update", json={"universe": "custom", "provider": "yahoo", "lookback": "1y"})
    removed = client.delete("/api/discovery/symbols/NASDAQ:AAPL")
    blocked = client.post("/api/paper/orders", json={"symbol": "AAPL", "side": "BUY", "quantity": 1})

    assert added.status_code == 201 and added.get_json()["success"]
    assert updated.status_code == 200 and updated.get_json()["data"]["succeeded"]
    assert removed.status_code == 200 and discovery.list_symbols("custom") == []
    assert blocked.status_code == 403 and blocked.get_json()["success"] is False
