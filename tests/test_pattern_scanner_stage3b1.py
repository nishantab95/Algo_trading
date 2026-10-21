from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from app.discovery.service import DiscoveryDataService
from app.patterns.detectors import DETECTORS, confirmed_pivots
from app.patterns.registry import IMPLEMENTED_IDS, PATTERN_REGISTRY
from app.patterns.scanner import PatternScanService


NEW_IDS = {
    "ascending_triangle", "descending_triangle", "symmetrical_triangle",
    "rising_wedge", "falling_wedge", "bullish_flag",
}


def frame_from_closes(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    dates = [date(2025, 1, 1) + timedelta(days=index) for index in range(len(closes))]
    return pd.DataFrame({
        "Date": dates, "Open": closes, "High": [value + 1 for value in closes],
        "Low": [value - 1 for value in closes], "Close": closes,
        "Volume": volumes or [1_000_000] * len(closes),
    })


def structure(kind: str, state: str = "FORMING") -> pd.DataFrame:
    prefixes = {
        "ascending_triangle": list(range(80, 95)),
        "descending_triangle": list(range(120, 105, -1)),
        "symmetrical_triangle": list(range(80, 95)),
        "rising_wedge": list(range(80, 95)),
        "falling_wedge": list(range(100, 85, -1)),
        "bullish_flag": list(range(80, 91)),
    }
    shapes = {
        # H-L-H-L-H: flat highs with progressively higher lows.
        "ascending_triangle": [98, 104, 110, 105, 100, 95, 100, 105, 110, 106, 103, 100, 104, 108, 110, 108, 107, 106],
        # L-H-L-H-L: flat lows with progressively lower highs.
        "descending_triangle": [102, 96, 90, 95, 100, 105, 100, 95, 90, 93, 96, 100, 97, 94, 90, 92, 93, 94],
        "symmetrical_triangle": [98, 104, 110, 105, 100, 95, 100, 103, 106, 103, 100, 98, 100, 102, 103, 102, 101, 100],
        # Both boundaries rise; lows rise materially faster than highs.
        "rising_wedge": [100, 105, 110, 106, 103, 100, 105, 110, 114, 112, 110, 108, 112, 115, 118, 117, 116, 115],
        # Both boundaries fall; highs fall materially faster than lows.
        "falling_wedge": [90, 100, 112, 124, 120, 115, 110, 112, 114, 116, 114, 110, 106, 106.5, 107, 108, 107, 106, 105],
        # Rising flagpole followed by H-L-H-L compact downward channel.
        "bullish_flag": [95, 100, 105, 110, 115, 120, 118, 116, 114, 112, 114, 116, 118, 116, 114, 112, 110, 112, 114, 116],
    }
    closes = prefixes[kind] + shapes[kind]
    additions = {
        "ascending_triangle": {"CONFIRMED": [113], "INVALIDATED": [100]},
        "descending_triangle": {"CONFIRMED": [87], "INVALIDATED": [105]},
        "symmetrical_triangle": {"CONFIRMED": [106], "INVALIDATED": [106, 90]},
        "rising_wedge": {"CONFIRMED": [110], "INVALIDATED": [130]},
        "falling_wedge": {"CONFIRMED": [115], "INVALIDATED": [90]},
        "bullish_flag": {"CONFIRMED": [121], "INVALIDATED": [105], "FALSE_BREAKOUT": [121]},
    }
    closes.extend(additions[kind].get(state, []))
    volumes = [1_000_000] * len(closes)
    if kind == "bullish_flag" and state == "CONFIRMED":
        volumes[-1] = 2_000_000
    return frame_from_closes(closes, volumes)


@pytest.mark.parametrize("pattern_id", sorted(NEW_IDS))
def test_registry_includes_the_stage_3b1_experimental_detectors(pattern_id):
    experimental = {pattern.id for pattern in PATTERN_REGISTRY if pattern.implementation_status == "EXPERIMENTAL"}
    assert len(PATTERN_REGISTRY) == len({pattern.id for pattern in PATTERN_REGISTRY}) == 55
    assert IMPLEMENTED_IDS == experimental and len(IMPLEMENTED_IDS) >= 12
    assert pattern_id in DETECTORS


@pytest.mark.parametrize("pattern_id", sorted(NEW_IDS))
def test_new_detectors_reject_insufficient_malformed_and_flat_data(pattern_id):
    detector = DETECTORS[pattern_id]
    assert detector("NASDAQ:AAPL", frame_from_closes([100] * 12))["status"] == "INSUFFICIENT_DATA"
    assert detector("NASDAQ:AAPL", frame_from_closes([100] * 25).drop(columns=["High"]))["status"] == "INSUFFICIENT_DATA"
    assert detector("NASDAQ:AAPL", frame_from_closes([100] * 50)) is None


@pytest.mark.parametrize("pattern_id", sorted(NEW_IDS))
def test_new_detectors_report_forming_confirmed_and_invalidated_states(pattern_id):
    detector = DETECTORS[pattern_id]
    forming = detector("NASDAQ:AAPL", structure(pattern_id))
    confirmed = detector("NASDAQ:AAPL", structure(pattern_id, "CONFIRMED"))
    invalidated = detector("NASDAQ:AAPL", structure(pattern_id, "INVALIDATED"))
    assert forming is not None and forming["status"] == "FORMING"
    assert confirmed is not None and confirmed["status"] == "CONFIRMED"
    assert invalidated is not None and invalidated["status"] == "INVALIDATED"
    assert confirmed["pivots"] and confirmed["evidence"]["trendlines"]
    assert all("slope" in line for line in confirmed["evidence"]["trendlines"])


@pytest.mark.parametrize("pattern_id", sorted(NEW_IDS - {"bullish_flag"}))
def test_wrong_slope_or_nonconverging_structures_do_not_cross_classify(pattern_id):
    opposites = {
        "ascending_triangle": "descending_triangle", "descending_triangle": "ascending_triangle",
        "symmetrical_triangle": "ascending_triangle", "rising_wedge": "falling_wedge",
        "falling_wedge": "rising_wedge",
    }
    assert DETECTORS[pattern_id]("NASDAQ:AAPL", structure(opposites[pattern_id])) is None


@pytest.mark.parametrize("pattern_id", sorted(NEW_IDS))
def test_insufficient_boundary_touches_are_not_promoted_to_patterns(pattern_id):
    assert DETECTORS[pattern_id]("NASDAQ:AAPL", structure(pattern_id), {"minimum_boundary_touches": 3}) is None


def test_excessively_wide_triangle_is_rejected_by_the_configured_boundary_limit():
    assert DETECTORS["ascending_triangle"]("NASDAQ:AAPL", structure("ascending_triangle"), {"maximum_boundary_width_pct": 0.05}) is None


def test_bullish_flag_rejects_false_breakout_without_volume_and_without_flagpole():
    false_breakout = DETECTORS["bullish_flag"]("NASDAQ:AAPL", structure("bullish_flag", "FALSE_BREAKOUT"))
    assert false_breakout is not None and false_breakout["status"] == "FORMING"
    assert DETECTORS["bullish_flag"]("NASDAQ:AAPL", frame_from_closes([100, 99, 98, 97] * 8)) is None


@pytest.mark.parametrize("pattern_id", sorted(NEW_IDS))
def test_scale_invariance_and_repeatability(pattern_id):
    original = structure(pattern_id, "CONFIRMED")
    scaled = original.copy()
    for column in ("Open", "High", "Low", "Close"):
        scaled[column] *= 7.25
    detector = DETECTORS[pattern_id]
    first, second = detector("NASDAQ:AAPL", original), detector("NASDAQ:AAPL", scaled)
    assert first is not None and second is not None
    assert first["status"] == second["status"] == "CONFIRMED"
    assert detector("NASDAQ:AAPL", original) == first


def test_triangle_pivots_are_not_known_before_their_right_hand_confirmation_candles():
    candles = structure("ascending_triangle")
    pivots = confirmed_pivots(candles, 3, 3, 3)
    assert all(pivot.known_index > pivot.index for pivot in pivots)
    partial = candles.iloc[:-2].copy()
    early = DETECTORS["ascending_triangle"]("NASDAQ:AAPL", partial)
    assert early is None or early["status"] != "CONFIRMED"


def _cache(service: DiscoveryDataService, symbol: str, candles: pd.DataFrame) -> None:
    from app.discovery.providers import parse_instrument
    candles.to_csv(service._cache_path(parse_instrument(symbol)), index=False)


def test_scanner_runs_new_detector_from_cache_and_is_reproducible(tmp_path):
    service = DiscoveryDataService(tmp_path / "discovery", sleep=lambda _seconds: None)
    _cache(service, "NSE:RELIANCE", structure("ascending_triangle"))
    scanner = PatternScanService(service)
    first = scanner.scan("nse", ["ascending_triangle"])
    second = scanner.scan("nse", ["ascending_triangle"])
    assert first["findings"][0]["pattern_id"] == "ascending_triangle"
    assert first["findings"][0]["fundamentals"]["assessment"]["health"] == "UNKNOWN"
    assert second["reused"] is True and second["scan_id"] == first["scan_id"]
