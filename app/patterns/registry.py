from __future__ import annotations

from dataclasses import asdict, dataclass


REGISTRY_VERSION = "3b2.1"
IMPLEMENTED_IDS = {
    "head_and_shoulders", "inverse_head_and_shoulders", "double_top",
    "double_bottom", "triple_top", "triple_bottom",
    "ascending_triangle", "descending_triangle", "symmetrical_triangle",
    "rising_wedge", "falling_wedge", "bullish_flag",
    "bearish_flag", "bullish_pennant", "bearish_pennant", "bullish_rectangle",
    "bearish_rectangle", "cup_and_handle",
}


@dataclass(frozen=True)
class PatternDefinition:
    id: str
    name: str
    family: str
    direction: str
    description: str
    data_requirements: str
    implementation_status: str
    algorithm_version: str | None
    parameters: dict

    def payload(self) -> dict:
        return asdict(self)


_NAMES = [
    ("head_and_shoulders", "Head and Shoulders", "reversal", "bearish"),
    ("inverse_head_and_shoulders", "Inverse Head and Shoulders", "reversal", "bullish"),
    ("double_top", "Double Top", "reversal", "bearish"),
    ("double_bottom", "Double Bottom", "reversal", "bullish"),
    ("triple_top", "Triple Top", "reversal", "bearish"),
    ("triple_bottom", "Triple Bottom", "reversal", "bullish"),
    ("ascending_triangle", "Ascending Triangle", "continuation", "bullish"),
    ("descending_triangle", "Descending Triangle", "continuation", "bearish"),
    ("symmetrical_triangle", "Symmetrical Triangle", "continuation", "neutral"),
    ("rising_wedge", "Rising Wedge", "reversal", "bearish"),
    ("falling_wedge", "Falling Wedge", "reversal", "bullish"),
    ("bullish_flag", "Bullish Flag", "continuation", "bullish"),
    ("bearish_flag", "Bearish Flag", "continuation", "bearish"),
    ("bullish_pennant", "Bullish Pennant", "continuation", "bullish"),
    ("bearish_pennant", "Bearish Pennant", "continuation", "bearish"),
    ("bullish_rectangle", "Bullish Rectangle", "continuation", "bullish"),
    ("bearish_rectangle", "Bearish Rectangle", "continuation", "bearish"),
    ("cup_and_handle", "Cup & Handle", "continuation", "bullish"),
    ("rounding_top", "Rounding Top", "reversal", "bearish"),
    ("rounding_bottom", "Rounding Bottom", "reversal", "bullish"),
    ("channel_patterns", "Channel Patterns", "continuation", "neutral"),
    ("broadening_wedge", "Broadening Wedge", "reversal", "neutral"),
    ("megaphone", "Megaphone", "reversal", "neutral"),
    ("diamond_top", "Diamond Top", "reversal", "bearish"),
    ("diamond_bottom", "Diamond Bottom", "reversal", "bullish"),
    ("bump_and_run", "Bump and Run", "reversal", "bearish"),
    ("island_reversal", "Island Reversal", "reversal", "neutral"),
    ("dead_cat_bounce", "Dead Cat Bounce", "reversal", "bearish"),
    ("parabolic_curve", "Parabolic Curve", "trend", "neutral"),
    ("v_pattern", "V Pattern", "reversal", "neutral"),
    ("ascending_staircase", "Ascending Staircase", "trend", "bullish"),
    ("descending_staircase", "Descending Staircase", "trend", "bearish"),
    ("tower_top", "Tower Top", "reversal", "bearish"),
    ("tower_bottom", "Tower Bottom", "reversal", "bullish"),
    ("pipe_top", "Pipe Top", "reversal", "bearish"),
    ("pipe_bottom", "Pipe Bottom", "reversal", "bullish"),
    ("scallop", "Scallop", "continuation", "neutral"),
    ("spikes", "Spikes", "volatility", "neutral"),
    ("shakeout", "Shakeout", "reversal", "bullish"),
    ("bull_trap", "Bull Trap", "trap", "bearish"),
    ("bear_trap", "Bear Trap", "trap", "bullish"),
    ("kicker", "Kicker", "candlestick", "neutral"),
    ("morning_star", "Morning Star", "candlestick", "bullish"),
    ("evening_star", "Evening Star", "candlestick", "bearish"),
    ("running_correction", "Running Correction", "continuation", "neutral"),
    ("complex_double_top_bottom", "Complex Double Top / Double Bottom", "reversal", "neutral"),
    ("complex_head_and_shoulders", "Complex Head and Shoulder", "reversal", "neutral"),
    ("harmonic_pattern", "Harmonic Pattern", "harmonic", "neutral"),
    ("elliott_wave_pattern", "Elliott Wave Pattern", "wave", "neutral"),
    ("three_drives", "Three Drives", "reversal", "neutral"),
    ("bullish_wolfe_wave", "Bullish Wolfe Wave", "wave", "bullish"),
    ("bearish_wolfe_wave", "Bearish Wolfe Wave", "wave", "bearish"),
    ("gaps_pattern", "Gaps Pattern", "gap", "neutral"),
    ("triple_inside_out_reversal", "Triple Inside-Out Reversal", "candlestick", "neutral"),
    ("candlestick_pattern", "Candlestick Pattern", "candlestick", "neutral"),
]

_PARAMETERS = {
    "pivot_left": 3, "pivot_right": 3, "minimum_pivot_separation": 3,
    "level_tolerance_pct": 0.03, "breakout_buffer_pct": 0.002,
    "recent_confirmation_sessions": 5, "forming_window_sessions": 20,
    "minimum_boundary_touches": 2, "minimum_formation_sessions": 10,
    "maximum_formation_sessions": 45, "line_touch_tolerance_pct": 0.035,
    "flat_slope_pct_per_session": 0.0015, "minimum_boundary_slope_pct_per_session": 0.001,
    "maximum_boundary_width_pct": 0.30, "maximum_convergence_ratio": 0.80,
    "maximum_apex_sessions": 60, "flagpole_min_return_pct": 0.08,
    "flagpole_min_sessions": 5, "flagpole_max_sessions": 20,
    "flagpole_min_volatility_multiple": 3.0,
    "flag_max_consolidation_sessions": 20, "flag_max_retracement_pct": 0.50,
    "flag_parallel_slope_pct_per_session": 0.003, "breakout_volume_ratio": 1.05,
    "require_breakout_volume_confirmation": True,
    "pennant_max_consolidation_sessions": 20, "pennant_max_height_to_pole_ratio": 0.60,
    "rectangle_minimum_boundary_touches": 2, "rectangle_min_range_width_pct": 0.025,
    "rectangle_max_width_change_pct": 0.04, "rectangle_max_formation_sessions": 45,
    "cup_min_duration_sessions": 14, "cup_max_duration_sessions": 80,
    "cup_min_depth_pct": 0.08, "cup_max_depth_pct": 0.45,
    "cup_rim_tolerance_pct": 0.05, "cup_bottom_zone_pct": 0.035,
    "cup_min_bottom_zone_candles": 3, "cup_min_side_sessions": 5,
    "handle_min_sessions": 3, "handle_max_sessions": 20,
    "handle_max_retracement_pct": 0.40,
}


def _description(name: str, direction: str) -> str:
    return f"{name} is a {direction} chart-structure topic evaluated from completed daily OHLCV candles."


PATTERN_REGISTRY = tuple(
    PatternDefinition(
        id=pattern_id,
        name=name,
        family=family,
        direction=direction,
        description=_description(name, direction),
        data_requirements="Validated daily OHLCV candles with sufficient completed bars for confirmed pivots.",
        implementation_status="EXPERIMENTAL" if pattern_id in IMPLEMENTED_IDS else "NOT_IMPLEMENTED",
        algorithm_version=REGISTRY_VERSION if pattern_id in IMPLEMENTED_IDS else None,
        parameters=dict(_PARAMETERS) if pattern_id in IMPLEMENTED_IDS else {},
    )
    for pattern_id, name, family, direction in _NAMES
)


def registry_payload() -> list[dict]:
    return [pattern.payload() for pattern in PATTERN_REGISTRY]


def get_pattern(pattern_id: str) -> PatternDefinition:
    for pattern in PATTERN_REGISTRY:
        if pattern.id == pattern_id:
            return pattern
    raise KeyError(pattern_id)
