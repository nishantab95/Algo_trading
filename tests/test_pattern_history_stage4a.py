from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

import main
from app.discovery.providers import parse_instrument
from app.discovery.service import DiscoveryDataService
from app.patterns.detectors import confirmed_pivots, pivot_candidates
from app.patterns.scanner import PatternScanService


def frame_from_closes(closes: list[float]) -> pd.DataFrame:
    dates = [date(2023, 1, 1) + timedelta(days=index) for index in range(len(closes))]
    return pd.DataFrame({
        "Date": dates, "Open": closes, "High": [value + 1 for value in closes],
        "Low": [value - 1 for value in closes], "Close": closes, "Volume": [1_000_000] * len(closes),
    })


def double_top(state: str = "FORMING") -> pd.DataFrame:
    closes = list(range(80, 95)) + [100, 105, 110, 105, 100, 95, 100, 105, 109, 105, 103, 102, 101, 100]
    if state == "CONFIRMED":
        closes.extend([90, 89, 88])
    elif state == "INVALIDATED":
        closes.extend([90, 112, 113])
    return frame_from_closes(closes)


def cache(service: DiscoveryDataService, symbol: str, candles: pd.DataFrame, *, status: str = "current") -> None:
    candles.to_csv(service._cache_path(parse_instrument(symbol)), index=False)
    service._save_catalog({"custom_symbols": [], "symbols": {
        symbol: {"status": status, "source": "fixture", "adjustment": "unadjusted fixture OHLCV"},
    }})


def test_historical_review_replays_prefixes_and_keeps_first_detection_separate_from_confirmation(tmp_path):
    service = DiscoveryDataService(tmp_path / "discovery", sleep=lambda _seconds: None)
    cache(service, "NSE:RELIANCE", double_top("CONFIRMED"))
    scanner = PatternScanService(service)

    review = scanner.historical_review("nse", ["double_top"], {"forming_window_sessions": 30})

    assert review["symbols_scanned"] == ["NSE:RELIANCE"]
    assert review["data_manifest"][0]["candles"] == len(double_top("CONFIRMED"))
    assert len(review["events"]) == 1  # Daily replay consolidates one continuing formation.
    event = next(event for event in review["events"] if event["symbol"] == "NSE:RELIANCE")
    assert event["first_detection_date"] < event["confirmation_date"]
    assert event["confirmation_date"] in event["chart"]["dates"]
    assert event["confirmation_date"] > max(pivot["known_date"] for pivot in event["pivots"])
    assert event["review_classification"] in {"RECENTLY_CONFIRMED_AT_INPUT_END", "HISTORICAL_FORMATION"}


def test_chronological_pivot_stream_matches_each_prefix_without_future_leakage():
    candles = double_top("CONFIRMED")
    future_aware_candidates = pivot_candidates(candles, 3, 3)
    known = []
    next_candidate = 0
    for index in range(19, len(candles)):
        while next_candidate < len(future_aware_candidates) and future_aware_candidates[next_candidate].known_index <= index:
            pivot = future_aware_candidates[next_candidate]
            if not known or pivot.kind != known[-1].kind:
                known.append(pivot)
            elif (pivot.kind == "H" and pivot.price > known[-1].price) or (pivot.kind == "L" and pivot.price < known[-1].price):
                known[-1] = pivot
            next_candidate += 1
        direct = confirmed_pivots(candles.iloc[:index + 1], 3, 3, 3)
        assert known == direct


def test_historical_review_is_reproducible_and_cache_visible_after_restart(tmp_path):
    root = tmp_path / "discovery"
    service = DiscoveryDataService(root, sleep=lambda _seconds: None)
    cache(service, "NSE:RELIANCE", double_top("CONFIRMED"))
    first = PatternScanService(service).historical_review("nse", ["double_top"], {"forming_window_sessions": 30})
    restarted = DiscoveryDataService(root, sleep=lambda _seconds: None)
    second = PatternScanService(restarted).historical_review("nse", ["double_top"], {"forming_window_sessions": 30})

    assert restarted.cache_metadata("NSE:RELIANCE")["candles"] == len(double_top("CONFIRMED"))
    assert second["reused"] is True and second["review_id"] == first["review_id"]
    assert [event["event_id"] for event in second["events"]] == [event["event_id"] for event in first["events"]]


def test_historical_review_records_invalidation_without_using_future_candles(tmp_path):
    service = DiscoveryDataService(tmp_path / "discovery", sleep=lambda _seconds: None)
    cache(service, "NSE:RELIANCE", double_top("INVALIDATED"))
    scanner = PatternScanService(service)

    full = scanner.historical_review("nse", ["double_top"], {"forming_window_sessions": 30})
    partial_service = DiscoveryDataService(tmp_path / "partial", sleep=lambda _seconds: None)
    cache(partial_service, "NSE:RELIANCE", double_top("INVALIDATED").iloc[:-2].copy())
    partial = PatternScanService(partial_service).historical_review("nse", ["double_top"], {"forming_window_sessions": 30})

    full_event = next(event for event in full["events"] if event["status"] == "INVALIDATED")
    assert full_event["invalidation_date"] >= full_event["confirmation_date"]
    assert all(event["status"] != "INVALIDATED" for event in partial["events"])


def test_historical_review_handles_missing_invalid_and_stale_cached_data(tmp_path):
    service = DiscoveryDataService(tmp_path / "discovery", sleep=lambda _seconds: None)
    cache(service, "NSE:RELIANCE", double_top(), status="stale")
    malformed = double_top().drop(columns=["Volume"])
    malformed.to_csv(service._cache_path(parse_instrument("NSE:TCS")), index=False)
    scanner = PatternScanService(service)

    review = scanner.historical_review("nse", ["double_top"], {"forming_window_sessions": 30})

    assert review["data_manifest"][0]["data_quality_warnings"] == ["Cache status: stale."]
    assert {row["symbol"] for row in review["symbols_skipped"]} == {"NSE:TCS", "NSE:INFY"}


def test_historical_overlap_metadata_and_api_never_attach_current_fundamentals(tmp_path, monkeypatch):
    service = DiscoveryDataService(tmp_path / "discovery", sleep=lambda _seconds: None)
    scanner = PatternScanService(service)
    events = [
        {"symbol": "NSE:RELIANCE", "pattern_id": "double_top", "pattern_name": "Double Top", "formation_start_date": "2023-01-01", "formation_end_date": "2023-01-20", "evidence": {}},
        {"symbol": "NSE:RELIANCE", "pattern_id": "head_and_shoulders", "pattern_name": "Head and Shoulders", "formation_start_date": "2023-01-05", "formation_end_date": "2023-01-18", "evidence": {}},
    ]
    scanner._annotate_overlaps(events)
    assert len(events) == 2 and events[0]["evidence"]["overlapping_patterns"]

    cache(service, "NSE:RELIANCE", double_top("CONFIRMED"))
    monkeypatch.setattr(main, "_DISCOVERY_DATA", service)
    monkeypatch.setattr(main, "_PATTERN_SCANNER", scanner)
    client = main.create_flask_app().test_client()
    response = client.post("/api/discovery/historical-pattern-review", json={"universe": "nse", "patterns": ["double_top"], "config": {"forming_window_sessions": 30}})
    blocked = client.post("/api/paper/orders", json={"symbol": "RELIANCE", "side": "BUY", "quantity": 1})

    assert response.status_code == 200 and response.get_json()["data"]["events"]
    assert all("fundamentals" not in event for event in response.get_json()["data"]["events"])
    assert all("review_classification" in event for event in response.get_json()["data"]["events"])
    assert blocked.status_code == 403
