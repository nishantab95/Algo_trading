from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

import main
from app.discovery.service import DiscoveryDataService
from app.patterns.detectors import DETECTORS, confirmed_pivots
from app.patterns.registry import IMPLEMENTED_IDS, PATTERN_REGISTRY
from app.patterns.scanner import PatternScanService


STAGE_3A_IDS = {
    "head_and_shoulders", "inverse_head_and_shoulders", "double_top",
    "double_bottom", "triple_top", "triple_bottom",
}


def frame_from_closes(closes: list[float]) -> pd.DataFrame:
    dates = [date(2025, 1, 1) + timedelta(days=index) for index in range(len(closes))]
    return pd.DataFrame({"Date": dates, "Open": closes, "High": [value + 1 for value in closes], "Low": [value - 1 for value in closes], "Close": closes, "Volume": [1_000_000] * len(closes)})


def structure(kind: str, state: str = "FORMING") -> pd.DataFrame:
    base_up = list(range(80, 95))
    base_down = list(range(120, 105, -1))
    shapes = {
        "double_top": base_up + [100, 105, 110, 105, 100, 95, 100, 105, 109, 105, 103, 102, 101, 100],
        "double_bottom": base_down + [100, 95, 90, 95, 100, 105, 100, 95, 91, 95, 97, 98, 99, 100],
        "triple_top": base_up + [100, 105, 110, 105, 100, 95, 100, 105, 109, 105, 100, 96, 100, 105, 110, 105, 103, 102, 101, 100],
        "triple_bottom": base_down + [100, 95, 90, 95, 100, 105, 100, 95, 91, 95, 100, 104, 100, 95, 90, 95, 97, 98, 99, 100],
        "head_and_shoulders": base_up + [100, 105, 108, 105, 100, 95, 100, 107, 114, 107, 100, 96, 100, 105, 108, 105, 103, 102, 101, 100],
        "inverse_head_and_shoulders": base_down + [100, 95, 92, 95, 100, 105, 100, 93, 86, 93, 100, 104, 100, 95, 92, 95, 97, 98, 99, 100],
    }
    closes = shapes[kind].copy()
    if state == "CONFIRMED":
        closes.extend(([90, 89, 88] if kind in {"double_top", "triple_top", "head_and_shoulders"} else [110, 111, 112]))
    elif state == "INVALIDATED":
        if kind == "head_and_shoulders": closes.extend([90, 116, 117])
        elif kind == "inverse_head_and_shoulders": closes.extend([110, 84, 83])
        else: closes.extend(([90, 112, 113] if kind in {"double_top", "triple_top"} else [110, 88, 87]))
    return frame_from_closes(closes)


@pytest.mark.parametrize("pattern_id", sorted(STAGE_3A_IDS))
def test_registry_has_exactly_55_unique_entries_and_original_six_remain_runnable(pattern_id):
    assert len(PATTERN_REGISTRY) == 55
    assert len({pattern.id for pattern in PATTERN_REGISTRY}) == 55
    assert {pattern.id for pattern in PATTERN_REGISTRY if pattern.implementation_status != "NOT_IMPLEMENTED"} == IMPLEMENTED_IDS
    assert pattern_id in DETECTORS


@pytest.mark.parametrize("pattern_id", sorted(STAGE_3A_IDS))
def test_each_detector_rejects_insufficient_and_malformed_data(pattern_id):
    detector = DETECTORS[pattern_id]
    assert detector("NASDAQ:AAPL", frame_from_closes([100] * 10))["status"] == "INSUFFICIENT_DATA"
    malformed = frame_from_closes([100] * 25).drop(columns=["Volume"])
    assert detector("NASDAQ:AAPL", malformed)["status"] == "INSUFFICIENT_DATA"


@pytest.mark.parametrize("pattern_id", sorted(STAGE_3A_IDS))
def test_each_detector_is_repeatable_and_does_not_match_flat_data(pattern_id):
    detector = DETECTORS[pattern_id]
    flat = frame_from_closes([100] * 50)
    assert detector("NASDAQ:AAPL", flat) is None
    data = structure(pattern_id)
    assert detector("NASDAQ:AAPL", data) == detector("NASDAQ:AAPL", data.copy())


@pytest.mark.parametrize("pattern_id", sorted(STAGE_3A_IDS))
def test_each_detector_reports_forming_confirmed_and_invalidated_states(pattern_id):
    detector = DETECTORS[pattern_id]
    assert detector("NASDAQ:AAPL", structure(pattern_id), {"forming_window_sessions": 30})["status"] == "FORMING"
    assert detector("NASDAQ:AAPL", structure(pattern_id, "CONFIRMED"), {"forming_window_sessions": 30})["status"] == "CONFIRMED"
    assert detector("NASDAQ:AAPL", structure(pattern_id, "INVALIDATED"), {"forming_window_sessions": 30})["status"] == "INVALIDATED"


def test_pivots_have_later_known_dates_and_no_lookahead_confirmation():
    data = structure("double_top")
    pivots = confirmed_pivots(data, 3, 3, 4)
    assert all(pivot.known_index > pivot.index for pivot in pivots)
    finding = DETECTORS["double_top"]("NASDAQ:AAPL", structure("double_top", "CONFIRMED"), {"forming_window_sessions": 30})
    assert finding["signal_detection_date"] > finding["pivots"][-1]["known_date"]


def _cache(service: DiscoveryDataService, canonical_symbol: str, candles: pd.DataFrame) -> None:
    from app.discovery.providers import parse_instrument
    candles.to_csv(service._cache_path(parse_instrument(canonical_symbol)), index=False)


def test_scanner_reads_cached_nse_and_us_data_and_is_idempotent(tmp_path):
    data = DiscoveryDataService(tmp_path / "discovery", sleep=lambda _seconds: None)
    _cache(data, "NSE:RELIANCE", structure("double_top"))
    _cache(data, "NASDAQ:AAPL", structure("double_bottom"))
    scanner = PatternScanService(data)

    nse = scanner.scan("nse", ["double_top"])
    us = scanner.scan("us", ["double_bottom"])
    repeated = scanner.scan("nse", ["double_top"])

    assert nse["findings"][0]["symbol"] == "NSE:RELIANCE"
    assert us["findings"][0]["symbol"] == "NASDAQ:AAPL"
    assert nse["symbols_skipped"] and us["symbols_skipped"]
    assert repeated["reused"] is True and repeated["scan_id"] == nse["scan_id"]


def test_scanner_handles_missing_cache_and_refuses_unimplemented_patterns(tmp_path):
    scanner = PatternScanService(DiscoveryDataService(tmp_path / "discovery", sleep=lambda _seconds: None))
    empty = scanner.scan("nse", ["double_top"])
    assert empty["findings"] == [] and len(empty["symbols_skipped"]) == 3
    with pytest.raises(ValueError, match="Only implemented patterns"):
        scanner.scan("nse", ["rounding_top"])


def test_scan_api_shows_results_and_keeps_trading_endpoints_blocked(tmp_path, monkeypatch):
    data = DiscoveryDataService(tmp_path / "discovery", sleep=lambda _seconds: None)
    _cache(data, "NSE:RELIANCE", structure("double_top"))
    scanner = PatternScanService(data)
    monkeypatch.setattr(main, "_DISCOVERY_DATA", data)
    monkeypatch.setattr(main, "_PATTERN_SCANNER", scanner)
    client = main.create_flask_app().test_client()

    registry = client.get("/api/discovery/patterns").get_json()["data"]["patterns"]
    scan = client.post("/api/discovery/scan", json={"universe": "nse", "patterns": ["double_top"]})
    blocked = client.post("/api/paper/orders", json={"symbol": "RELIANCE", "side": "BUY", "quantity": 1})

    assert len(registry) == 55
    assert scan.status_code == 200 and scan.get_json()["data"]["findings"]
    assert blocked.status_code == 403 and blocked.get_json()["success"] is False
