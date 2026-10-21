from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

import main
from app.discovery.providers import parse_instrument
from app.discovery.service import DiscoveryDataService
from app.fundamentals.analysis import assess, calculate
from app.fundamentals.providers import FundamentalProviderError, normalize_yahoo_payload
from app.fundamentals.service import FundamentalService
from app.patterns.scanner import PatternScanService
from tests.test_pattern_scanner_stage3a import structure


def recent_year_end(years_ago):
    return f"{date.today().year - years_ago}-12-31"


def annual(period, revenue, net_income, cfo, *, sector="Technology", industry="Software", debt=40, equity=100, interest=-4):
    return {"period_end": period, "frequency": "annual", "metrics": {"revenue": revenue, "gross_profit": revenue * .5, "operating_income": revenue * .25, "net_income": net_income, "total_assets": 220, "equity": equity, "total_debt": debt, "cash": 20, "current_assets": 90, "current_liabilities": 45, "interest_expense": interest, "operating_cash_flow": cfo, "capital_expenditure": -10}, "source_fields": {}}


def snapshot(*, sector="Technology", industry="Software", annual_rows=None):
    return {"symbol": "NASDAQ:AAPL", "provider": "yahoo", "provider_symbol": "AAPL", "identity": {"name": "Example Co", "sector": sector, "industry": industry, "statement_currency": "USD", "quote_currency": "USD", "quote_type": "EQUITY"}, "annual": annual_rows or [annual(recent_year_end(1), 120, 20, 25), annual(recent_year_end(2), 100, 16, 20), annual(recent_year_end(3), 90, 12, 17)], "quarterly": [], "valuation": {"pe": 20, "pb": 3, "market_cap": 1000}, "retrieved_at": datetime.now(timezone.utc).isoformat(), "data_quality_warnings": [], "capabilities": {}, "units": "reported"}


class FakeFundamentals:
    name = "fake"
    capabilities = {}
    def __init__(self, responses, valuations=None): self.responses = list(responses); self.valuations = list(valuations or []); self.calls = 0; self.valuation_calls = 0
    def fetch(self, instrument):
        self.calls += 1
        value = self.responses.pop(0)
        if isinstance(value, Exception): raise value
        result = dict(value); result["symbol"] = instrument.canonical_symbol; return result
    def fetch_valuation(self, instrument):
        self.valuation_calls += 1
        if not self.valuations: return None
        value = self.valuations.pop(0)
        if isinstance(value, Exception): raise value
        return {"valuation": value, "retrieved_at": datetime.now(timezone.utc).isoformat()}


def test_yahoo_normaliser_parses_aliases_periods_and_metadata():
    columns = [pd.Timestamp("2024-12-31"), pd.Timestamp("2023-12-31")]
    income = pd.DataFrame([[120, 100], [20, 15], [30, 24]], index=["Operating Revenue", "Net Income Common Stockholders", "EBIT"], columns=columns)
    balance = pd.DataFrame([[200, 180], [100, 90], [40, 35]], index=["Total Assets", "Stockholders Equity", "Total Debt"], columns=columns)
    cashflow = pd.DataFrame([[25, 20], [-10, -8]], index=["Total Cash From Operating Activities", "Capital Expenditures"], columns=columns)
    quarterly_income = pd.DataFrame([[31], [6]], index=["Total Revenue", "Net Income"], columns=[pd.Timestamp("2025-03-31")])
    result = normalize_yahoo_payload(parse_instrument("NASDAQ:AAPL"), {"longName": "Apple", "financialCurrency": "USD", "sector": "Technology", "trailingPE": 20}, income, balance, cashflow, quarterly_income=quarterly_income)
    assert result["annual"][0]["metrics"]["revenue"] == 120
    assert result["annual"][0]["source_fields"]["revenue"] == "Operating Revenue"
    assert result["identity"]["statement_currency"] == "USD" and result["valuation"]["pe"] == 20
    assert result["quarterly"][0]["frequency"] == "quarterly" and result["quarterly"][0]["metrics"]["revenue"] == 31


def test_empty_and_invalid_yahoo_values_remain_missing_not_zero():
    result = normalize_yahoo_payload(parse_instrument("TSE:7203"), {"financialCurrency": "JPY"}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    assert result["annual"] == [] and result["data_quality_warnings"]
    bad = snapshot(annual_rows=[annual(recent_year_end(1), float("nan"), 20, 25), annual(recent_year_end(2), 100, 16, 20)])
    assert assess(bad)["health"] == "UNKNOWN"


@pytest.mark.parametrize("rows,expected", [
    ([annual(recent_year_end(1), 120, 20, 25), annual(recent_year_end(2), 100, 16, 20)], "GREEN"),
    ([annual(recent_year_end(1), 90, 18, 20), annual(recent_year_end(2), 100, 16, 20)], "AMBER"),
    ([annual(recent_year_end(1), 120, -10, -5, debt=300, equity=100), annual(recent_year_end(2), 100, 16, 20)], "RISKY"),
    ([annual(recent_year_end(1), 120, 20, 25)], "UNKNOWN"),
])
def test_operating_company_health_precedence(rows, expected):
    result = assess(snapshot(annual_rows=rows))
    assert result["health"] == expected
    assert result["valuation"]["classification"] == "UNKNOWN"


def test_financial_sector_and_funds_are_not_scored_as_operating_companies():
    bank = assess(snapshot(sector="Financial Services", industry="Banks - Regional"))
    fund = assess({**snapshot(), "identity": {**snapshot()["identity"], "quote_type": "ETF"}})
    assert bank["health"] == fund["health"] == "UNKNOWN"
    assert bank["checks"][0]["status"] == "NOT_APPLICABLE"


def test_calculations_handle_growth_signs_debt_equity_and_capex_convention():
    data = snapshot(annual_rows=[annual(recent_year_end(1), 120, 20, 25), annual(recent_year_end(2), 100, -10, 5)])
    values = calculate(data)["values"]
    assert values["revenue_growth"] == pytest.approx(.2)
    assert values["net_income_growth"] is None and values["net_income_growth_status"] == "sign_or_zero_change"
    assert values["free_cash_flow"] == 15
    negative_equity = calculate(snapshot(annual_rows=[annual(recent_year_end(1), 120, 20, 25, equity=-10), annual(recent_year_end(2), 100, 16, 20)]))["values"]
    assert negative_equity["debt_to_equity"] is None


def test_debt_free_and_low_cash_conversion_are_not_silently_marked_as_passes():
    debt_free = assess(snapshot(annual_rows=[annual(recent_year_end(1), 120, 20, 25, debt=0, interest=None), annual(recent_year_end(2), 100, 16, 20, debt=0, interest=None)]))
    coverage = next(check for check in debt_free["checks"] if check["id"] == "interest_coverage")
    assert debt_free["health"] == "GREEN" and coverage["status"] == "NOT_APPLICABLE"
    weak_conversion = assess(snapshot(annual_rows=[annual(recent_year_end(1), 120, 20, 10), annual(recent_year_end(2), 100, 16, 20)]))
    cash = next(check for check in weak_conversion["checks"] if check["id"] == "cash_flow")
    assert weak_conversion["health"] == "AMBER" and cash["status"] == "CAUTION"


def test_stale_reports_are_unknown_without_a_more_serious_risk_signal():
    result = assess(snapshot(annual_rows=[annual("2020-12-31", 120, 20, 25), annual("2019-12-31", 100, 16, 20)]))
    freshness = next(check for check in result["checks"] if check["id"] == "report_freshness")
    assert result["health"] == "UNKNOWN" and freshness["status"] == "CAUTION"


def test_cache_reuses_fresh_snapshot_and_preserves_old_snapshot_on_failure(tmp_path):
    provider = FakeFundamentals([snapshot(), FundamentalProviderError("Yahoo timeout")])
    service = FundamentalService(tmp_path / "fundamentals", provider)
    first = service.get("NASDAQ:AAPL")
    cached = service.get("NASDAQ:AAPL")
    failed = service.get("NASDAQ:AAPL", refresh=True)
    assert provider.calls == 2
    assert first["assessment"]["health"] == "GREEN" and cached["freshness"] == "fresh"
    assert failed["freshness"] == "stale" and failed["snapshot"] is not None and "timeout" in failed["last_error"]


def test_stale_cache_is_marked_stale_and_manual_refresh_is_atomic(tmp_path):
    provider = FakeFundamentals([snapshot(), snapshot()])
    service = FundamentalService(tmp_path / "fundamentals", provider)
    service.get("NSE:RELIANCE")
    path = service._path("NSE:RELIANCE")
    record = json.loads(path.read_text(encoding="utf-8")); record["last_successful_refresh"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(); path.write_text(json.dumps(record), encoding="utf-8")
    assert service.cached("NSE:RELIANCE")["freshness"] == "stale"
    refreshed = service.get("NSE:RELIANCE", refresh=True)
    assert refreshed["freshness"] == "fresh" and not path.with_suffix(".tmp").exists()


def test_valuation_revalidates_on_a_shorter_schedule_without_reloading_statements(tmp_path):
    provider = FakeFundamentals([snapshot()], valuations=[{"pe": 22, "market_cap": 1200}])
    service = FundamentalService(tmp_path / "fundamentals", provider)
    service.get("NASDAQ:AAPL")
    path = service._path("NASDAQ:AAPL")
    record = json.loads(path.read_text(encoding="utf-8")); record["valuation_last_successful_refresh"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(); path.write_text(json.dumps(record), encoding="utf-8")
    refreshed = service.get("NASDAQ:AAPL")
    assert provider.calls == 1 and provider.valuation_calls == 1
    assert refreshed["valuation_freshness"] == "fresh" and refreshed["snapshot"]["valuation"]["pe"] == 22


def test_scanner_enriches_current_match_and_http_refresh_keeps_trading_blocked(tmp_path, monkeypatch):
    price = DiscoveryDataService(tmp_path / "discovery", sleep=lambda _seconds: None)
    price._cache_path(parse_instrument("NSE:RELIANCE")).write_text(structure("double_top").to_csv(index=False), encoding="utf-8")
    fund = FundamentalService(tmp_path / "fundamentals", FakeFundamentals([snapshot(), snapshot()]))
    scanner = PatternScanService(price, fund)
    monkeypatch.setattr(main, "_DISCOVERY_DATA", price); monkeypatch.setattr(main, "_FUNDAMENTALS", fund); monkeypatch.setattr(main, "_PATTERN_SCANNER", scanner)
    client = main.create_flask_app().test_client()
    scan = client.post("/api/discovery/scan", json={"universe": "nse", "patterns": ["double_top"]}).get_json()["data"]
    refreshed = client.post("/api/discovery/fundamentals/NSE:RELIANCE/refresh").get_json()["data"]
    blocked = client.post("/api/paper/orders", json={"symbol": "RELIANCE", "side": "BUY", "quantity": 1})
    assert scan["findings"][0]["fundamentals"]["assessment"]["health"] == "GREEN"
    assert refreshed["assessment"]["valuation"]["classification"] == "UNKNOWN"
    assert blocked.status_code == 403
