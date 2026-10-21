from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from app.patterns.detectors import DETECTORS, confirmed_pivots
from app.patterns.registry import IMPLEMENTED_IDS, PATTERN_REGISTRY
from app.patterns.scanner import PatternScanService


NEW_IDS = {
    "bearish_flag", "bullish_pennant", "bearish_pennant",
    "bullish_rectangle", "bearish_rectangle", "cup_and_handle",
}


def frame_from_closes(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    dates = [date(2025, 1, 1) + timedelta(days=index) for index in range(len(closes))]
    return pd.DataFrame({
        "Date": dates, "Open": closes, "High": [value + 1 for value in closes],
        "Low": [value - 1 for value in closes], "Close": closes,
        "Volume": volumes or [1_000_000] * len(closes),
    })


def structure(pattern_id: str, state: str = "FORMING") -> pd.DataFrame:
    prefixes = {
        "bearish_flag": list(range(170, 150, -1)),
        "bullish_pennant": list(range(70, 91)),
        "bearish_pennant": list(range(170, 150, -1)),
        "bullish_rectangle": list(range(80, 100)),
        "bearish_rectangle": list(range(150, 130, -1)),
        "cup_and_handle": list(range(80, 100)),
    }
    shapes = {
        # Bearish impulse, then a compact sideways/upward L-H-L-H channel.
        "bearish_flag": [145, 140, 135, 130, 125, 120, 115, 110, 112, 114, 116, 118, 116, 114, 112, 110, 112, 114, 116, 118, 116, 114, 112],
        # Bullish impulse, then decreasing highs and increasing lows.
        "bullish_pennant": [94, 98, 102, 106, 110, 114, 118, 122, 118, 114, 110, 112, 114, 116, 118, 116, 114, 112, 113, 114, 115, 116, 115, 114, 113],
        "bearish_pennant": [148, 144, 140, 136, 132, 128, 124, 120, 124, 128, 130, 128, 126, 124, 126, 127, 128, 127, 126, 125, 126, 127, 126],
        # Repeated horizontal resistance/support tests after an eligible trend.
        "bullish_rectangle": [104, 108, 112, 116, 120, 116, 112, 108, 110, 114, 118, 120, 116, 112, 108, 110, 114, 118, 120, 116, 112, 110],
        "bearish_rectangle": [126, 122, 118, 114, 110, 114, 118, 122, 120, 116, 112, 110, 114, 118, 122, 120, 116, 112, 110, 114, 118, 120],
        # Comparable rims, a broad multi-bar low, recovery, and a smaller handle.
        "cup_and_handle": [104, 108, 112, 116, 120, 118, 115, 112, 108, 104, 100, 96, 93, 91, 90, 91, 92, 94, 97, 101, 105, 109, 113, 116, 119, 120, 118, 116, 114, 115, 116, 117],
    }
    additions = {
        "bearish_flag": {"CONFIRMED": [105], "INVALIDATED": [125], "FALSE_BREAKOUT": [105]},
        "bullish_pennant": {"CONFIRMED": [122], "INVALIDATED": [108], "FALSE_BREAKOUT": [122]},
        "bearish_pennant": {"CONFIRMED": [120], "INVALIDATED": [135], "FALSE_BREAKOUT": [120]},
        "bullish_rectangle": {"CONFIRMED": [124], "INVALIDATED": [104]},
        "bearish_rectangle": {"CONFIRMED": [106], "INVALIDATED": [127]},
        "cup_and_handle": {"CONFIRMED": [123], "INVALIDATED": [110]},
    }
    closes = prefixes[pattern_id] + shapes[pattern_id] + additions[pattern_id].get(state, [])
    volumes = [1_000_000] * len(closes)
    if pattern_id in {"bearish_flag", "bullish_pennant", "bearish_pennant"} and state == "CONFIRMED":
        volumes[-1] = 2_000_000
    return frame_from_closes(closes, volumes)


def test_registry_has_all_55_topics_and_exactly_eighteen_experimental_detectors():
    experimental = {pattern.id for pattern in PATTERN_REGISTRY if pattern.implementation_status == "EXPERIMENTAL"}
    not_implemented = {pattern.id for pattern in PATTERN_REGISTRY if pattern.implementation_status == "NOT_IMPLEMENTED"}
    assert len(PATTERN_REGISTRY) == len({pattern.id for pattern in PATTERN_REGISTRY}) == 55
    assert IMPLEMENTED_IDS == experimental and len(experimental) == 18
    assert len(not_implemented) == 37
    assert NEW_IDS <= set(DETECTORS)


@pytest.mark.parametrize("pattern_id", sorted(NEW_IDS))
def test_stage_3b2_detectors_report_forming_confirmed_and_invalidated_states(pattern_id):
    detector = DETECTORS[pattern_id]
    forming = detector("NASDAQ:AAPL", structure(pattern_id))
    confirmed = detector("NASDAQ:AAPL", structure(pattern_id, "CONFIRMED"))
    invalidated = detector("NASDAQ:AAPL", structure(pattern_id, "INVALIDATED"))
    assert forming is not None and forming["status"] == "FORMING"
    assert confirmed is not None and confirmed["status"] == "CONFIRMED"
    assert invalidated is not None and invalidated["status"] == "INVALIDATED"
    assert confirmed["pivots"] and "annotations" in confirmed["evidence"]


@pytest.mark.parametrize("pattern_id", sorted(NEW_IDS))
def test_stage_3b2_detectors_reject_insufficient_malformed_and_flat_data(pattern_id):
    detector = DETECTORS[pattern_id]
    assert detector("NASDAQ:AAPL", frame_from_closes([100] * 12))["status"] == "INSUFFICIENT_DATA"
    assert detector("NASDAQ:AAPL", frame_from_closes([100] * 25).drop(columns=["High"]))["status"] == "INSUFFICIENT_DATA"
    assert detector("NASDAQ:AAPL", frame_from_closes([100] * 60)) is None


@pytest.mark.parametrize("pattern_id", sorted(NEW_IDS))
def test_stage_3b2_detectors_are_scale_invariant_and_repeatable(pattern_id):
    original = structure(pattern_id, "CONFIRMED")
    scaled = original.copy()
    for column in ("Open", "High", "Low", "Close"):
        scaled[column] *= 7.25
    detector = DETECTORS[pattern_id]
    first, second = detector("NASDAQ:AAPL", original), detector("NASDAQ:AAPL", scaled)
    assert first is not None and second is not None
    assert first["status"] == second["status"] == "CONFIRMED"
    assert detector("NASDAQ:AAPL", original) == first


def test_directional_flag_and_pennants_require_their_pole_geometry_and_volume_confirmation():
    assert DETECTORS["bearish_flag"]("NASDAQ:AAPL", structure("bearish_flag", "FALSE_BREAKOUT"))["status"] == "FORMING"
    assert DETECTORS["bullish_pennant"]("NASDAQ:AAPL", structure("bullish_pennant", "FALSE_BREAKOUT"))["status"] == "FORMING"
    assert DETECTORS["bearish_pennant"]("NASDAQ:AAPL", structure("bearish_pennant", "FALSE_BREAKOUT"))["status"] == "FORMING"
    assert DETECTORS["bearish_flag"]("NASDAQ:AAPL", frame_from_closes([100, 99, 98, 97] * 15)) is None
    assert DETECTORS["bullish_pennant"]("NASDAQ:AAPL", structure("bullish_rectangle")) is None
    no_volume_requirement = DETECTORS["bearish_flag"](
        "NASDAQ:AAPL", structure("bearish_flag", "FALSE_BREAKOUT"), {"require_breakout_volume_confirmation": False},
    )
    assert no_volume_requirement is not None and no_volume_requirement["status"] == "CONFIRMED"
    assert no_volume_requirement["evidence"]["volume_confirmation_required"] is False


def test_rectangles_reject_a_sloped_or_too_narrow_range_and_the_wrong_prior_trend():
    sloped = structure("bullish_rectangle")
    sloped.loc[20:, "Close"] += list(range(len(sloped) - 20))
    sloped.loc[20:, "Open"] = sloped.loc[20:, "Close"]
    sloped.loc[20:, "High"] = sloped.loc[20:, "Close"] + 1
    sloped.loc[20:, "Low"] = sloped.loc[20:, "Close"] - 1
    assert DETECTORS["bullish_rectangle"]("NASDAQ:AAPL", sloped) is None
    assert DETECTORS["bullish_rectangle"]("NASDAQ:AAPL", structure("bullish_rectangle"), {"rectangle_min_range_width_pct": 0.20}) is None
    wrong_trend = structure("bullish_rectangle")
    wrong_trend.loc[:19, ["Open", "High", "Low", "Close"]] = frame_from_closes(list(range(150, 130, -1))).loc[:, ["Open", "High", "Low", "Close"]]
    assert DETECTORS["bullish_rectangle"]("NASDAQ:AAPL", wrong_trend) is None


def test_cup_and_handle_rejects_a_v_bottom_or_an_oversized_handle():
    v_bottom = structure("cup_and_handle")
    closes = v_bottom["Close"].tolist()
    for index in (32, 33, 35, 36):
        closes[index] = 96
    v_bottom = frame_from_closes(closes)
    assert DETECTORS["cup_and_handle"]("NASDAQ:AAPL", v_bottom) is None
    assert DETECTORS["cup_and_handle"]("NASDAQ:AAPL", structure("cup_and_handle"), {"handle_max_retracement_pct": 0.10}) is None


def test_final_pivots_are_not_used_before_their_right_hand_confirmation_candles():
    candles = structure("cup_and_handle", "CONFIRMED")
    pivots = confirmed_pivots(candles, 3, 3, 3)
    assert all(pivot.known_index > pivot.index for pivot in pivots)
    early = DETECTORS["cup_and_handle"]("NASDAQ:AAPL", candles.iloc[:-2].copy())
    assert early is None or early["status"] != "CONFIRMED"


def test_overlap_metadata_keeps_each_individual_finding():
    findings = [
        {"symbol": "NASDAQ:AAPL", "pattern_id": "bullish_flag", "pattern_name": "Bullish Flag", "formation_start_date": "2025-01-01", "formation_end_date": "2025-01-20", "evidence": {}},
        {"symbol": "NASDAQ:AAPL", "pattern_id": "bullish_pennant", "pattern_name": "Bullish Pennant", "formation_start_date": "2025-01-05", "formation_end_date": "2025-01-18", "evidence": {}},
    ]
    PatternScanService._annotate_overlaps(findings)
    assert len(findings) == 2
    assert findings[0]["evidence"]["overlapping_patterns"][0]["pattern_id"] == "bullish_pennant"
    assert findings[1]["evidence"]["overlapping_patterns"][0]["pattern_id"] == "bullish_flag"


def test_scan_selection_deduplicates_repeated_pattern_ids(tmp_path):
    from app.discovery.service import DiscoveryDataService

    scanner = PatternScanService(DiscoveryDataService(tmp_path / "discovery", sleep=lambda _seconds: None))
    result = scanner.scan("nse", ["bearish_flag", "bearish_flag"])
    assert result["patterns"] == ["bearish_flag"]
