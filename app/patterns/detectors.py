from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from app.patterns.registry import REGISTRY_VERSION, get_pattern


DEFAULTS = {
    "pivot_left": 3, "pivot_right": 3, "minimum_pivot_separation": 3,
    "level_tolerance_pct": 0.03, "breakout_buffer_pct": 0.002,
    "recent_confirmation_sessions": 5, "forming_window_sessions": 20,
    "minimum_trend_pct": 0.01, "head_prominence_pct": 0.015,
    # Stage 3B1 geometry. Slopes are normalised by the fitted boundary's
    # average price, which keeps these rules scale invariant.
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


@dataclass(frozen=True)
class Pivot:
    kind: str
    index: int
    known_index: int
    date: str
    known_date: str
    price: float

    def payload(self) -> dict:
        return {"kind": self.kind, "date": self.date, "known_date": self.known_date, "price": round(self.price, 4)}


@dataclass(frozen=True)
class TrendLine:
    """Least-squares boundary through confirmed, same-kind pivots."""
    slope: float
    intercept: float
    mean_price: float

    def at(self, index: int) -> float:
        return self.slope * index + self.intercept

    @property
    def normalized_slope(self) -> float:
        return self.slope / self.mean_price if self.mean_price else 0.0


def validate_candles(candles: pd.DataFrame) -> pd.DataFrame:
    required = ["Date", "Open", "High", "Low", "Close", "Volume"]
    if not isinstance(candles, pd.DataFrame) or any(column not in candles.columns for column in required):
        raise ValueError("Daily OHLCV candles must include Date, Open, High, Low, Close, and Volume.")
    frame = candles[required].copy()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    for column in required[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    valid = (
        frame["Date"].notna()
        & np.isfinite(frame[required[1:]]).all(axis=1)
        & (frame[["Open", "High", "Low", "Close"]] > 0).all(axis=1)
        & (frame["Volume"] >= 0)
        & (frame["High"] >= frame[["Open", "Close", "Low"]].max(axis=1))
        & (frame["Low"] <= frame[["Open", "Close", "High"]].min(axis=1))
    )
    if not valid.all():
        raise ValueError("Daily OHLCV candles contain invalid prices, volume, or dates.")
    frame = frame.drop_duplicates("Date", keep="last").sort_values("Date").reset_index(drop=True)
    if len(frame) < 20:
        raise ValueError("At least 20 completed daily candles are required.")
    frame["Date"] = frame["Date"].dt.strftime("%Y-%m-%d")
    return frame


def pivot_candidates(frame: pd.DataFrame, left: int, right: int) -> list[Pivot]:
    """Return pivots with their confirmation dates, including future candidates.

    Callers performing chronological replay must expose a candidate only once
    ``known_index`` has been reached.  The function itself does not make a
    current-time assertion about those candidates.
    """
    pivots: list[Pivot] = []
    for index in range(left, len(frame) - right):
        high_window = frame["High"].iloc[index - left:index + right + 1]
        low_window = frame["Low"].iloc[index - left:index + right + 1]
        if frame.at[index, "High"] == high_window.max() and (high_window == frame.at[index, "High"]).sum() == 1:
            pivots.append(Pivot("H", index, index + right, frame.at[index, "Date"], frame.at[index + right, "Date"], float(frame.at[index, "High"])))
        if frame.at[index, "Low"] == low_window.min() and (low_window == frame.at[index, "Low"]).sum() == 1:
            pivots.append(Pivot("L", index, index + right, frame.at[index, "Date"], frame.at[index + right, "Date"], float(frame.at[index, "Low"])))
    pivots.sort(key=lambda pivot: (pivot.index, pivot.kind))
    return pivots


def select_confirmed_pivots(pivots: list[Pivot]) -> list[Pivot]:
    """Apply the existing alternating-pivot selection rule to known pivots."""
    selected: list[Pivot] = []
    for pivot in pivots:
        if not selected or pivot.kind != selected[-1].kind:
            selected.append(pivot)
        elif (pivot.kind == "H" and pivot.price > selected[-1].price) or (pivot.kind == "L" and pivot.price < selected[-1].price):
            selected[-1] = pivot
    return selected


def confirmed_pivots(frame: pd.DataFrame, left: int, right: int, separation: int) -> list[Pivot]:
    del separation  # Retained in the public API; detectors enforce separation by pattern.
    return select_confirmed_pivots(pivot_candidates(frame, left, right))


def prepare_pattern_data(candles: pd.DataFrame, config: dict | None = None) -> dict:
    """Validate one OHLCV frame and calculate pivots once for a scan symbol."""
    cfg = {**DEFAULTS, **(config or {})}
    frame = validate_candles(candles)
    return {
        "frame": frame,
        "pivots": confirmed_pivots(frame, cfg["pivot_left"], cfg["pivot_right"], cfg["minimum_pivot_separation"]),
    }


def _prepared(candles: pd.DataFrame, cfg: dict) -> dict:
    prepared = cfg.get("_prepared")
    if isinstance(prepared, dict) and isinstance(prepared.get("frame"), pd.DataFrame) and isinstance(prepared.get("pivots"), list):
        return prepared
    return prepare_pattern_data(candles, cfg)


def _rule(name: str, passed: bool, detail: str) -> dict:
    return {"rule": name, "passed": passed, "detail": detail}


def _finding(symbol: str, pattern_id: str, frame: pd.DataFrame, status: str, direction: str, pivots: list[Pivot], level: float | None, confirmation_index: int | None, invalidation: float | None, evidence: dict, rules: list[dict], warnings: list[str] | None = None) -> dict:
    pattern = get_pattern(pattern_id)
    return {
        "symbol": symbol,
        "exchange": symbol.split(":", 1)[0],
        "pattern_id": pattern_id,
        "pattern_name": pattern.name,
        "detector_version": REGISTRY_VERSION,
        "direction": direction,
        "status": status,
        "formation_start_date": pivots[0].date if pivots else None,
        "formation_end_date": pivots[-1].date if pivots else None,
        "signal_detection_date": frame.at[confirmation_index, "Date"] if confirmation_index is not None else None,
        "latest_candle_date": frame.at[len(frame) - 1, "Date"],
        "pivots": [pivot.payload() for pivot in pivots],
        "levels": {"support_resistance_or_neckline": round(level, 4) if level is not None else None, "breakout_confirmation": round(level, 4) if level is not None else None, "invalidation": round(invalidation, 4) if invalidation is not None else None},
        "evidence": evidence,
        "passed_conditions": [rule for rule in rules if rule["passed"]],
        "failed_conditions": [rule for rule in rules if not rule["passed"]],
        "data_quality_warnings": warnings or [],
    }


def _insufficient(symbol: str, pattern_id: str, reason: str) -> dict:
    pattern = get_pattern(pattern_id)
    return {"symbol": symbol, "exchange": symbol.split(":", 1)[0], "pattern_id": pattern_id, "pattern_name": pattern.name, "detector_version": REGISTRY_VERSION, "direction": pattern.direction, "status": "INSUFFICIENT_DATA", "evidence": {"reason": reason}, "pivots": [], "levels": {}, "passed_conditions": [], "failed_conditions": [], "data_quality_warnings": [reason], "formation_start_date": None, "formation_end_date": None, "signal_detection_date": None, "latest_candle_date": None}


def _last_sequence(pivots: list[Pivot], kinds: str) -> list[Pivot] | None:
    size = len(kinds)
    for index in range(len(pivots) - size, -1, -1):
        candidate = pivots[index:index + size]
        if "".join(pivot.kind for pivot in candidate) == kinds:
            return candidate
    return None


def _trend(frame: pd.DataFrame, pivot: Pivot, expected: str, minimum: float) -> tuple[bool, float]:
    if pivot.index < 10:
        return False, 0.0
    change = float(frame.at[pivot.index, "Close"] / frame.at[pivot.index - 10, "Close"] - 1)
    return (change >= minimum if expected == "up" else change <= -minimum), change


def _state(frame: pd.DataFrame, pivots: list[Pivot], neckline: float, direction: str, invalidation: float, cfg: dict) -> tuple[str, int | None, dict]:
    final = pivots[-1]
    start = final.known_index + 1
    closes = frame["Close"].astype(float)
    breakout = closes < neckline * (1 - cfg["breakout_buffer_pct"]) if direction == "bearish" else closes > neckline * (1 + cfg["breakout_buffer_pct"])
    invalid = closes > invalidation * (1 + cfg["breakout_buffer_pct"]) if direction == "bearish" else closes < invalidation * (1 - cfg["breakout_buffer_pct"])
    confirmation = next((index for index in range(start, len(frame)) if bool(breakout.iloc[index])), None)
    invalidation_index = next((index for index in range(start, len(frame)) if bool(invalid.iloc[index])), None)
    if invalidation_index is not None and (confirmation is None or invalidation_index > confirmation):
        return "INVALIDATED", confirmation, {"invalidation_date": frame.at[invalidation_index, "Date"]}
    if confirmation is not None:
        return "CONFIRMED", confirmation, {"sessions_since_confirmation": len(frame) - 1 - confirmation}
    active = len(frame) - 1 - final.known_index <= cfg["forming_window_sessions"]
    return ("FORMING" if active else "INVALIDATED"), None, {"sessions_since_last_confirmed_pivot": len(frame) - 1 - final.known_index}


def _detect(symbol: str, candles: pd.DataFrame, pattern_id: str, kinds: str, direction: str, *, shoulders: bool = False, triples: bool = False, config: dict | None = None) -> dict | None:
    cfg = {**DEFAULTS, **(config or {})}
    try:
        prepared = _prepared(candles, cfg)
    except ValueError as exc:
        return _insufficient(symbol, pattern_id, str(exc))
    frame, pivots = prepared["frame"], prepared["pivots"]
    selected = _last_sequence(pivots, kinds)
    if selected is None:
        return None
    separation_ok = all(
        selected[index + 1].index - selected[index].index >= cfg["minimum_pivot_separation"]
        for index in range(len(selected) - 1)
    )
    tops = [pivot for pivot in selected if pivot.kind == "H"]
    bottoms = [pivot for pivot in selected if pivot.kind == "L"]
    comparable = (tops[::2] if direction == "bearish" else bottoms[::2]) if shoulders else (tops if direction == "bearish" else bottoms)
    base = float(np.mean([pivot.price for pivot in comparable]))
    spread = (max(pivot.price for pivot in comparable) - min(pivot.price for pivot in comparable)) / base
    trend_ok, trend_pct = _trend(frame, selected[0], "up" if direction == "bearish" else "down", cfg["minimum_trend_pct"])
    level_points = bottoms if direction == "bearish" else tops
    neckline = float(np.mean([pivot.price for pivot in level_points]))
    invalidation = max(pivot.price for pivot in tops) if direction == "bearish" else min(pivot.price for pivot in bottoms)
    rules = [
        _rule("prior_trend", trend_ok, f"10-session pre-formation trend was {trend_pct:.2%}."),
        _rule("similar_levels", spread <= cfg["level_tolerance_pct"], f"Comparable pivot spread was {spread:.2%}; maximum is {cfg['level_tolerance_pct']:.2%}."),
        _rule("pivot_separation", separation_ok, f"Each pivot is separated by at least {cfg['minimum_pivot_separation']} completed sessions."),
        _rule("confirmed_pivots", True, f"{len(selected)} pivots were only used after their later confirmation candles."),
    ]
    if shoulders:
        shoulder_mean = (tops[0].price + tops[-1].price) / 2
        prominence = (tops[1].price / shoulder_mean - 1) if direction == "bearish" else (shoulder_mean / bottoms[1].price - 1)
        shoulder_spread = abs(tops[0].price - tops[-1].price) / shoulder_mean if direction == "bearish" else abs(bottoms[0].price - bottoms[-1].price) / shoulder_mean
        rules.extend([
            _rule("head_prominence", prominence >= cfg["head_prominence_pct"], f"Head prominence was {prominence:.2%}."),
            _rule("shoulder_similarity", shoulder_spread <= cfg["level_tolerance_pct"], f"Shoulder spread was {shoulder_spread:.2%}."),
        ])
    if not all(rule["passed"] for rule in rules):
        return None
    status, confirmation, state_evidence = _state(frame, selected, neckline, direction, invalidation, cfg)
    evidence = {"level_spread_pct": round(spread * 100, 4), "prior_trend_pct": round(trend_pct * 100, 4), "neckline": round(neckline, 4), "pivot_confirmation_dates": [pivot.known_date for pivot in selected], **state_evidence}
    return _finding(symbol, pattern_id, frame, status, direction, selected, neckline, confirmation, invalidation, evidence, rules)


def head_and_shoulders(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect(symbol, candles, "head_and_shoulders", "HLHLH", "bearish", shoulders=True, config=config)


def inverse_head_and_shoulders(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect(symbol, candles, "inverse_head_and_shoulders", "LHLHL", "bullish", shoulders=True, config=config)


def double_top(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect(symbol, candles, "double_top", "HLH", "bearish", config=config)


def double_bottom(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect(symbol, candles, "double_bottom", "LHL", "bullish", config=config)


def triple_top(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect(symbol, candles, "triple_top", "HLHLH", "bearish", triples=True, config=config)


def triple_bottom(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect(symbol, candles, "triple_bottom", "LHLHL", "bullish", triples=True, config=config)


def _fit_line(points: list[Pivot]) -> TrendLine:
    indices = np.asarray([point.index for point in points], dtype=float)
    prices = np.asarray([point.price for point in points], dtype=float)
    slope, intercept = np.polyfit(indices, prices, 1)
    return TrendLine(float(slope), float(intercept), float(np.mean(prices)))


def _geometry_candidates(pivots: list[Pivot], cfg: dict, *, maximum_sessions: int | None = None, minimum_sessions: int | None = None) -> list[list[Pivot]]:
    """Return latest alternating pivot windows that can provide two boundaries."""
    candidates: list[list[Pivot]] = []
    seen: set[tuple[int, ...]] = set()
    maximum = maximum_sessions or cfg["maximum_formation_sessions"]
    minimum = minimum_sessions or cfg["minimum_formation_sessions"]
    for end in range(len(pivots) - 1, -1, -1):
        for size in range(min(7, end + 1), 3, -1):
            candidate = pivots[end - size + 1:end + 1]
            if sum(point.kind == "H" for point in candidate) < cfg["minimum_boundary_touches"]:
                continue
            if sum(point.kind == "L" for point in candidate) < cfg["minimum_boundary_touches"]:
                continue
            duration = candidate[-1].index - candidate[0].index
            if duration < minimum or duration > maximum:
                continue
            if any(candidate[index + 1].index - candidate[index].index < cfg["minimum_pivot_separation"] for index in range(len(candidate) - 1)):
                continue
            key = tuple(point.index for point in candidate)
            if key not in seen:
                candidates.append(candidate); seen.add(key)
    return candidates


def _line_residual(line: TrendLine, points: list[Pivot]) -> float:
    return max(abs(point.price - line.at(point.index)) / max(abs(point.price), 1e-9) for point in points)


def _boundary_geometry(candidate: list[Pivot], cfg: dict) -> dict | None:
    highs = [point for point in candidate if point.kind == "H"]
    lows = [point for point in candidate if point.kind == "L"]
    if len(highs) < cfg["minimum_boundary_touches"] or len(lows) < cfg["minimum_boundary_touches"]:
        return None
    upper, lower = _fit_line(highs), _fit_line(lows)
    start, end = candidate[0].index, candidate[-1].index
    start_width, end_width = upper.at(start) - lower.at(start), upper.at(end) - lower.at(end)
    average_price = (upper.mean_price + lower.mean_price) / 2
    slope_gap = upper.slope - lower.slope
    apex_index = (lower.intercept - upper.intercept) / slope_gap if slope_gap < 0 else None
    apex_after = apex_index - end if apex_index is not None else None
    return {
        "upper": upper, "lower": lower, "highs": highs, "lows": lows,
        "start": start, "end": end, "duration": end - start,
        "start_width": start_width, "end_width": end_width,
        "start_width_pct": start_width / average_price if average_price else np.inf,
        "convergence_ratio": end_width / start_width if start_width > 0 else np.inf,
        "upper_residual": _line_residual(upper, highs), "lower_residual": _line_residual(lower, lows),
        "apex_index": apex_index, "apex_after": apex_after,
    }


def _line_payload(name: str, line: TrendLine, frame: pd.DataFrame, geometry: dict) -> dict:
    start, end = geometry["start"], len(frame) - 1
    return {
        "name": name, "start_date": frame.at[start, "Date"], "end_date": frame.at[end, "Date"],
        "start_price": round(line.at(start), 4), "end_price": round(line.at(end), 4),
        "slope": round(line.slope, 8), "slope_pct_per_session": round(line.normalized_slope * 100, 6),
    }


def _line_state(frame: pd.DataFrame, candidate: list[Pivot], upper: TrendLine, lower: TrendLine, direction: str, cfg: dict, *, require_volume: bool = False) -> tuple[str, int | None, dict]:
    """Evaluate only after the final boundary pivot became knowable."""
    start = candidate[-1].known_index + 1
    confirmation: int | None = None
    confirmation_direction: str | None = None
    invalidation: int | None = None
    volume_ratio: float | None = None
    for index in range(start, len(frame)):
        close = float(frame.at[index, "Close"])
        upper_level, lower_level = upper.at(index), lower.at(index)
        bullish = close > upper_level * (1 + cfg["breakout_buffer_pct"])
        bearish = close < lower_level * (1 - cfg["breakout_buffer_pct"])
        if require_volume and (bullish or bearish):
            # Prior completed bars are available at the breakout candle even
            # when it immediately follows the final pivot's known date.
            prior = frame["Volume"].iloc[max(0, index - 5):index]
            baseline = float(prior.mean()) if len(prior) else 0.0
            ratio = float(frame.at[index, "Volume"]) / baseline if baseline > 0 else 0.0
            if bullish or bearish:
                volume_ratio = ratio
            # Volume confirms the directional breakout, not a structural
            # invalidation through the opposite boundary.
            if direction == "bullish":
                bullish = bullish and ratio >= cfg["breakout_volume_ratio"]
            elif direction == "bearish":
                bearish = bearish and ratio >= cfg["breakout_volume_ratio"]
            else:
                bullish = bullish and ratio >= cfg["breakout_volume_ratio"]
                bearish = bearish and ratio >= cfg["breakout_volume_ratio"]
        if direction == "bullish":
            if bearish and invalidation is None: invalidation = index
            if bullish and confirmation is None: confirmation, confirmation_direction = index, "bullish"
        elif direction == "bearish":
            if bullish and invalidation is None: invalidation = index
            if bearish and confirmation is None: confirmation, confirmation_direction = index, "bearish"
        else:
            if confirmation is None and (bullish or bearish):
                confirmation, confirmation_direction = index, "bullish" if bullish else "bearish"
            elif confirmation_direction == "bullish" and bearish and invalidation is None:
                invalidation = index
            elif confirmation_direction == "bearish" and bullish and invalidation is None:
                invalidation = index
    evidence = {}
    if volume_ratio is not None: evidence["breakout_volume_ratio"] = round(volume_ratio, 4)
    if confirmation is not None:
        evidence.update({"sessions_since_confirmation": len(frame) - 1 - confirmation, "breakout_direction": confirmation_direction})
    if invalidation is not None:
        evidence["invalidation_date"] = frame.at[invalidation, "Date"]
    if invalidation is not None:
        return "INVALIDATED", confirmation, evidence
    if confirmation is not None:
        return "CONFIRMED", confirmation, evidence
    active = len(frame) - 1 - candidate[-1].known_index <= cfg["forming_window_sessions"]
    evidence["sessions_since_last_confirmed_pivot"] = len(frame) - 1 - candidate[-1].known_index
    return ("FORMING" if active else "INVALIDATED"), None, evidence


def _geometric_rules(geometry: dict, cfg: dict) -> list[dict]:
    apex_after = geometry["apex_after"]
    return [
        _rule("boundary_touches", len(geometry["highs"]) >= cfg["minimum_boundary_touches"] and len(geometry["lows"]) >= cfg["minimum_boundary_touches"], f"Upper/lower touches: {len(geometry['highs'])}/{len(geometry['lows'])}; minimum is {cfg['minimum_boundary_touches']} each."),
        _rule("formation_duration", cfg["minimum_formation_sessions"] <= geometry["duration"] <= cfg["maximum_formation_sessions"], f"Formation duration was {geometry['duration']} sessions."),
        _rule("line_fit", geometry["upper_residual"] <= cfg["line_touch_tolerance_pct"] and geometry["lower_residual"] <= cfg["line_touch_tolerance_pct"], f"Maximum upper/lower pivot residuals were {geometry['upper_residual']:.2%}/{geometry['lower_residual']:.2%}."),
        _rule("boundary_width", geometry["start_width"] > 0 and geometry["end_width"] > 0 and geometry["start_width_pct"] <= cfg["maximum_boundary_width_pct"], f"Initial boundary width was {geometry['start_width_pct']:.2%} of price."),
        _rule("convergence", geometry["convergence_ratio"] <= cfg["maximum_convergence_ratio"], f"Boundary width ratio from start to end was {geometry['convergence_ratio']:.2f}."),
        _rule("apex_timing", apex_after is not None and 0 < apex_after <= cfg["maximum_apex_sessions"], f"Projected apex is {apex_after:.1f} sessions after the final formation pivot." if apex_after is not None else "Boundaries do not converge to a future apex."),
        _rule("confirmed_pivots", True, "Every boundary touch is a completed pivot with a later known date."),
    ]


def _geometric_evidence(frame: pd.DataFrame, candidate: list[Pivot], geometry: dict, state: dict, explanation: str, direction: str = "bullish") -> dict:
    upper, lower = geometry["upper"], geometry["lower"]
    if direction == "bearish":
        breakout_condition = "Close below fitted lower boundary plus configured buffer."
        invalidation_condition = "Close above fitted upper boundary plus configured buffer."
    elif direction == "neutral":
        breakout_condition = "Close outside either fitted boundary plus configured buffer."
        invalidation_condition = "A confirmed break through the opposite boundary invalidates the structure."
    else:
        breakout_condition = "Close above fitted upper boundary plus configured buffer."
        invalidation_condition = "Close below fitted lower boundary plus configured buffer."
    return {
        "explanation": explanation,
        "upper_slope": round(upper.slope, 8), "lower_slope": round(lower.slope, 8),
        "upper_intercept": round(upper.intercept, 8), "lower_intercept": round(lower.intercept, 8),
        "upper_slope_pct_per_session": round(upper.normalized_slope * 100, 6),
        "lower_slope_pct_per_session": round(lower.normalized_slope * 100, 6),
        "formation_duration_sessions": geometry["duration"],
        "boundary_width_start_pct": round(geometry["start_width_pct"] * 100, 4),
        "boundary_width_end_pct": round(geometry["end_width"] / ((upper.mean_price + lower.mean_price) / 2) * 100, 4),
        "convergence_ratio": round(geometry["convergence_ratio"], 4),
        "apex_sessions_after_formation": round(geometry["apex_after"], 4) if geometry["apex_after"] is not None else None,
        "pivot_confirmation_dates": [point.known_date for point in candidate],
        "resistance_level": round(upper.at(geometry["end"]), 4), "support_level": round(lower.at(geometry["end"]), 4),
        "breakout_condition": breakout_condition,
        "invalidation_condition": invalidation_condition,
        "trendlines": [_line_payload("upper_resistance", upper, frame, geometry), _line_payload("lower_support", lower, frame, geometry)],
        **state,
    }


def _detect_geometric(symbol: str, candles: pd.DataFrame, pattern_id: str, shape: str, config: dict | None = None) -> dict | None:
    cfg = {**DEFAULTS, **(config or {})}
    try:
        prepared = _prepared(candles, cfg)
    except ValueError as exc:
        return _insufficient(symbol, pattern_id, str(exc))
    frame, pivots = prepared["frame"], prepared["pivots"]
    for candidate in _geometry_candidates(pivots, cfg):
        geometry = _boundary_geometry(candidate, cfg)
        if geometry is None:
            continue
        upper, lower = geometry["upper"], geometry["lower"]
        minimum, flat = cfg["minimum_boundary_slope_pct_per_session"], cfg["flat_slope_pct_per_session"]
        if shape == "ascending":
            direction, level, invalidation = "bullish", upper.at(geometry["end"]), lower.at(geometry["end"])
            shape_rules = [_rule("flat_resistance", abs(upper.normalized_slope) <= flat, f"Upper slope was {upper.normalized_slope:.3%} per session."), _rule("rising_support", lower.normalized_slope >= minimum and lower.slope > upper.slope, f"Lower slope was {lower.normalized_slope:.3%} per session.")]
            explanation = "Flat resistance and rising support converge; a close above resistance confirms the bullish structure."
        elif shape == "descending":
            direction, level, invalidation = "bearish", lower.at(geometry["end"]), upper.at(geometry["end"])
            shape_rules = [_rule("flat_support", abs(lower.normalized_slope) <= flat, f"Lower slope was {lower.normalized_slope:.3%} per session."), _rule("falling_resistance", upper.normalized_slope <= -minimum and upper.slope < lower.slope, f"Upper slope was {upper.normalized_slope:.3%} per session.")]
            explanation = "Flat support and falling resistance converge; a close below support confirms the bearish structure."
        elif shape == "symmetrical":
            direction, level, invalidation = "neutral", upper.at(geometry["end"]), lower.at(geometry["end"])
            shape_rules = [_rule("falling_resistance", upper.normalized_slope <= -minimum, f"Upper slope was {upper.normalized_slope:.3%} per session."), _rule("rising_support", lower.normalized_slope >= minimum, f"Lower slope was {lower.normalized_slope:.3%} per session.")]
            explanation = "Falling resistance and rising support converge; confirmation direction follows the first buffered boundary break."
        elif shape == "rising_wedge":
            direction, level, invalidation = "bearish", lower.at(geometry["end"]), upper.at(geometry["end"])
            shape_rules = [_rule("both_boundaries_rise", upper.normalized_slope >= minimum and lower.normalized_slope >= minimum, f"Upper/lower slopes were {upper.normalized_slope:.3%}/{lower.normalized_slope:.3%} per session."), _rule("support_rises_faster", lower.slope > upper.slope, "Lower support rises faster than upper resistance, narrowing the wedge.")]
            explanation = "Both wedge boundaries rise while support catches resistance; only a lower-boundary breakdown confirms bearish direction."
        else:
            direction, level, invalidation = "bullish", upper.at(geometry["end"]), lower.at(geometry["end"])
            shape_rules = [_rule("both_boundaries_fall", upper.normalized_slope <= -minimum and lower.normalized_slope <= -minimum, f"Upper/lower slopes were {upper.normalized_slope:.3%}/{lower.normalized_slope:.3%} per session."), _rule("resistance_falls_faster", upper.slope < lower.slope, "Upper resistance falls faster than lower support, narrowing the wedge.")]
            explanation = "Both wedge boundaries fall while resistance descends faster; only an upper-boundary breakout confirms bullish direction."
        rules = _geometric_rules(geometry, cfg) + shape_rules
        if not all(rule["passed"] for rule in rules):
            continue
        status, confirmation, state = _line_state(frame, candidate, upper, lower, direction, cfg)
        finding_direction = state.get("breakout_direction", direction) if direction == "neutral" else direction
        evidence = _geometric_evidence(frame, candidate, geometry, state, explanation, direction)
        return _finding(symbol, pattern_id, frame, status, finding_direction, candidate, level, confirmation, invalidation, evidence, rules)
    return None


def ascending_triangle(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect_geometric(symbol, candles, "ascending_triangle", "ascending", config)


def descending_triangle(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect_geometric(symbol, candles, "descending_triangle", "descending", config)


def symmetrical_triangle(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect_geometric(symbol, candles, "symmetrical_triangle", "symmetrical", config)


def rising_wedge(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect_geometric(symbol, candles, "rising_wedge", "rising_wedge", config)


def falling_wedge(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect_geometric(symbol, candles, "falling_wedge", "falling_wedge", config)


def _flag_candidates(pivots: list[Pivot], cfg: dict, kinds: str = "HLHL") -> list[list[Pivot]]:
    candidates = []
    for end in range(len(pivots) - 1, 2, -1):
        candidate = pivots[end - 3:end + 1]
        if "".join(point.kind for point in candidate) != kinds:
            continue
        if any(candidate[index + 1].index - candidate[index].index < cfg["minimum_pivot_separation"] for index in range(len(candidate) - 1)):
            continue
        duration = candidate[-1].index - candidate[0].index
        if cfg["minimum_formation_sessions"] <= duration <= cfg["flag_max_consolidation_sessions"]:
            candidates.append(candidate)
    return candidates


def _directional_pole(frame: pd.DataFrame, pole_end: Pivot, direction: str, cfg: dict) -> dict:
    search_start = max(0, pole_end.index - cfg["flagpole_max_sessions"])
    prior = frame["Close"].iloc[search_start:pole_end.index + 1].astype(float)
    local_start = int(prior.idxmin() if direction == "bullish" else prior.idxmax())
    base = float(frame.at[local_start, "Close"])
    endpoint = pole_end.price
    signed_return = endpoint / base - 1 if base > 0 else np.nan
    magnitude = signed_return if direction == "bullish" else -signed_return
    daily_returns = frame["Close"].iloc[local_start:pole_end.index + 1].astype(float).pct_change().abs().dropna()
    volatility = float(daily_returns.mean()) if len(daily_returns) else 0.0
    return {
        "start_index": local_start, "end_index": pole_end.index, "base": base, "endpoint": endpoint,
        "sessions": pole_end.index - local_start, "signed_return": signed_return,
        "magnitude": magnitude, "daily_volatility": volatility,
        "volatility_multiple": magnitude / max(volatility, 1e-9),
    }


def _pole_rule(pole: dict, cfg: dict, direction: str) -> dict:
    verb = "gained" if direction == "bullish" else "fell"
    passed = (
        cfg["flagpole_min_sessions"] <= pole["sessions"] <= cfg["flagpole_max_sessions"]
        and pole["magnitude"] >= cfg["flagpole_min_return_pct"]
        and pole["volatility_multiple"] >= cfg["flagpole_min_volatility_multiple"]
    )
    return _rule("flagpole", passed, f"Flagpole {verb} {pole['magnitude']:.2%} over {pole['sessions']} sessions ({pole['volatility_multiple']:.1f}× mean daily movement).")


def _pole_annotation(frame: pd.DataFrame, pole: dict) -> dict:
    return {
        "type": "line", "name": "flagpole", "start_date": frame.at[pole["start_index"], "Date"],
        "end_date": frame.at[pole["end_index"], "Date"], "start_price": round(pole["base"], 4),
        "end_price": round(pole["endpoint"], 4),
    }


def _detect_flag(symbol: str, candles: pd.DataFrame, pattern_id: str, direction: str, config: dict | None = None) -> dict | None:
    cfg = {**DEFAULTS, **(config or {})}
    try:
        prepared = _prepared(candles, cfg)
    except ValueError as exc:
        return _insufficient(symbol, pattern_id, str(exc))
    frame, pivots = prepared["frame"], prepared["pivots"]
    kinds = "HLHL" if direction == "bullish" else "LHLH"
    for candidate in _flag_candidates(pivots, cfg, kinds):
        geometry = _boundary_geometry(candidate, {**cfg, "maximum_formation_sessions": cfg["flag_max_consolidation_sessions"]})
        if geometry is None:
            continue
        upper, lower = geometry["upper"], geometry["lower"]
        pole = _directional_pole(frame, candidate[0], direction, cfg)
        if direction == "bullish":
            retracement = (pole["endpoint"] - min(point.price for point in geometry["lows"])) / (pole["endpoint"] - pole["base"]) if pole["endpoint"] > pole["base"] else np.inf
            channel_ok = upper.normalized_slope <= cfg["flat_slope_pct_per_session"] and lower.normalized_slope <= cfg["flat_slope_pct_per_session"]
            level, invalidation = upper.at(geometry["end"]), lower.at(geometry["end"])
            explanation = "A measurable bullish flagpole precedes a compact parallel consolidation; a buffered, higher-volume upper-channel break confirms the pattern."
        else:
            retracement = (max(point.price for point in geometry["highs"]) - pole["endpoint"]) / (pole["base"] - pole["endpoint"]) if pole["base"] > pole["endpoint"] else np.inf
            channel_ok = upper.normalized_slope >= -cfg["flat_slope_pct_per_session"] and lower.normalized_slope >= -cfg["flat_slope_pct_per_session"]
            level, invalidation = lower.at(geometry["end"]), upper.at(geometry["end"])
            explanation = "A measurable bearish flagpole precedes a compact parallel consolidation; a buffered, higher-volume lower-channel break confirms the caution signal."
        parallel_gap = abs(upper.normalized_slope - lower.normalized_slope)
        rules = [
            _pole_rule(pole, cfg, direction),
            _rule("shorter_than_pole", geometry["duration"] < pole["sessions"], f"Flag consolidation lasted {geometry['duration']} sessions versus a {pole['sessions']}-session pole."),
            _rule("consolidation_duration", geometry["duration"] <= cfg["flag_max_consolidation_sessions"], f"Flag consolidation lasted {geometry['duration']} sessions."),
            _rule("parallel_channel", parallel_gap <= cfg["flag_parallel_slope_pct_per_session"], f"Normalised boundary-slope gap was {parallel_gap:.3%} per session."),
            _rule("channel_direction", channel_ok, f"Upper/lower channel slopes were {upper.normalized_slope:.3%}/{lower.normalized_slope:.3%} per session."),
            _rule("retracement_limit", 0 <= retracement <= cfg["flag_max_retracement_pct"], f"Flag retracement was {retracement:.2%} of the flagpole."),
            _rule("line_fit", geometry["upper_residual"] <= cfg["line_touch_tolerance_pct"] and geometry["lower_residual"] <= cfg["line_touch_tolerance_pct"], f"Maximum upper/lower pivot residuals were {geometry['upper_residual']:.2%}/{geometry['lower_residual']:.2%}."),
            _rule("confirmed_pivots", True, "The channel uses only pivots whose confirmation candles have completed."),
        ]
        if not all(rule["passed"] for rule in rules):
            continue
        require_volume = bool(cfg["require_breakout_volume_confirmation"])
        status, confirmation, state = _line_state(frame, candidate, upper, lower, direction, cfg, require_volume=require_volume)
        # A flag channel is deliberately parallel, so an intersection/apex is
        # not a meaningful geometric attribute for its evidence payload.
        geometry["apex_after"] = None
        evidence = _geometric_evidence(frame, candidate, geometry, state, explanation, direction)
        evidence.update({
            "flagpole_start_date": frame.at[pole["start_index"], "Date"], "flagpole_end_date": candidate[0].date,
            "flagpole_return_pct": round(pole["signed_return"] * 100, 4), "flagpole_sessions": pole["sessions"],
            "flagpole_volatility_multiple": round(pole["volatility_multiple"], 4),
            "consolidation_start_date": candidate[0].date, "consolidation_end_date": candidate[-1].date,
            "retracement_pct": round(retracement * 100, 4), "parallel_slope_gap_pct_per_session": round(parallel_gap * 100, 6),
            "volume_confirmation_required": require_volume,
            "breakout_condition": (("Close above fitted upper channel plus buffer with the configured volume comparison." if direction == "bullish" else "Close below fitted lower channel plus buffer with the configured volume comparison.") if require_volume else ("Close above fitted upper channel plus buffer." if direction == "bullish" else "Close below fitted lower channel plus buffer.")),
            "annotations": [_pole_annotation(frame, pole)],
        })
        return _finding(symbol, pattern_id, frame, status, direction, candidate, level, confirmation, invalidation, evidence, rules)
    return None


def bullish_flag(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect_flag(symbol, candles, "bullish_flag", "bullish", config)


def bearish_flag(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect_flag(symbol, candles, "bearish_flag", "bearish", config)


def _detect_pennant(symbol: str, candles: pd.DataFrame, pattern_id: str, direction: str, config: dict | None = None) -> dict | None:
    cfg = {**DEFAULTS, **(config or {})}
    try:
        prepared = _prepared(candles, cfg)
    except ValueError as exc:
        return _insufficient(symbol, pattern_id, str(exc))
    frame, pivots = prepared["frame"], prepared["pivots"]
    required_kind = "H" if direction == "bullish" else "L"
    for candidate in _geometry_candidates(pivots, cfg, maximum_sessions=cfg["pennant_max_consolidation_sessions"]):
        if candidate[0].kind != required_kind or candidate[-1].kind != required_kind:
            continue
        geometry = _boundary_geometry(candidate, cfg)
        if geometry is None:
            continue
        upper, lower = geometry["upper"], geometry["lower"]
        pole = _directional_pole(frame, candidate[0], direction, cfg)
        consolidation_height = max(point.price for point in geometry["highs"]) - min(point.price for point in geometry["lows"])
        pole_size = abs(pole["endpoint"] - pole["base"])
        height_ratio = consolidation_height / pole_size if pole_size > 0 else np.inf
        rules = _geometric_rules(geometry, cfg) + [
            _pole_rule(pole, cfg, direction),
            _rule("pennant_duration", geometry["duration"] <= cfg["pennant_max_consolidation_sessions"] and geometry["duration"] < pole["sessions"], f"Pennant duration was {geometry['duration']} sessions versus a {pole['sessions']}-session pole."),
            _rule("smaller_than_pole", height_ratio <= cfg["pennant_max_height_to_pole_ratio"], f"Consolidation height was {height_ratio:.2%} of pole size."),
            _rule("converging_boundaries", upper.normalized_slope <= -cfg["minimum_boundary_slope_pct_per_session"] and lower.normalized_slope >= cfg["minimum_boundary_slope_pct_per_session"], f"Upper/lower slopes were {upper.normalized_slope:.3%}/{lower.normalized_slope:.3%} per session."),
        ]
        if not all(rule["passed"] for rule in rules):
            continue
        require_volume = bool(cfg["require_breakout_volume_confirmation"])
        status, confirmation, state = _line_state(frame, candidate, upper, lower, direction, cfg, require_volume=require_volume)
        explanation = ("A bullish impulse precedes a short converging pennant; only a buffered, volume-supported upper break confirms it." if direction == "bullish" else "A bearish impulse precedes a short converging pennant; only a buffered, volume-supported lower break confirms it.")
        evidence = _geometric_evidence(frame, candidate, geometry, state, explanation, direction)
        evidence.update({
            "flagpole_start_date": frame.at[pole["start_index"], "Date"], "flagpole_end_date": candidate[0].date,
            "flagpole_return_pct": round(pole["signed_return"] * 100, 4), "flagpole_sessions": pole["sessions"],
            "consolidation_start_date": candidate[0].date, "consolidation_end_date": candidate[-1].date,
            "consolidation_height_to_pole_pct": round(height_ratio * 100, 4), "volume_confirmation_required": require_volume,
            "annotations": [_pole_annotation(frame, pole)],
        })
        level = upper.at(geometry["end"]) if direction == "bullish" else lower.at(geometry["end"])
        invalidation = lower.at(geometry["end"]) if direction == "bullish" else upper.at(geometry["end"])
        return _finding(symbol, pattern_id, frame, status, direction, candidate, level, confirmation, invalidation, evidence, rules)
    return None


def bullish_pennant(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect_pennant(symbol, candles, "bullish_pennant", "bullish", config)


def bearish_pennant(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect_pennant(symbol, candles, "bearish_pennant", "bearish", config)


def _detect_rectangle(symbol: str, candles: pd.DataFrame, pattern_id: str, direction: str, config: dict | None = None) -> dict | None:
    cfg = {**DEFAULTS, **(config or {})}
    local_cfg = {**cfg, "minimum_boundary_touches": cfg["rectangle_minimum_boundary_touches"]}
    try:
        prepared = _prepared(candles, cfg)
    except ValueError as exc:
        return _insufficient(symbol, pattern_id, str(exc))
    frame, pivots = prepared["frame"], prepared["pivots"]
    for candidate in _geometry_candidates(pivots, local_cfg, maximum_sessions=cfg["rectangle_max_formation_sessions"]):
        geometry = _boundary_geometry(candidate, local_cfg)
        if geometry is None:
            continue
        upper, lower = geometry["upper"], geometry["lower"]
        average_price = (upper.mean_price + lower.mean_price) / 2
        range_width = (geometry["start_width"] + geometry["end_width"]) / 2
        range_width_pct = range_width / average_price if average_price else np.inf
        width_change = abs(geometry["end_width"] - geometry["start_width"]) / average_price if average_price else np.inf
        trend_ok, trend_pct = _trend(frame, candidate[0], "up" if direction == "bullish" else "down", cfg["minimum_trend_pct"])
        rules = [
            _rule("prior_trend", trend_ok, f"10-session pre-range trend was {trend_pct:.2%}."),
            _rule("horizontal_boundaries", abs(upper.normalized_slope) <= cfg["flat_slope_pct_per_session"] and abs(lower.normalized_slope) <= cfg["flat_slope_pct_per_session"], f"Upper/lower slopes were {upper.normalized_slope:.3%}/{lower.normalized_slope:.3%} per session."),
            _rule("multiple_range_tests", len(geometry["highs"]) >= cfg["rectangle_minimum_boundary_touches"] and len(geometry["lows"]) >= cfg["rectangle_minimum_boundary_touches"], f"Resistance/support touches: {len(geometry['highs'])}/{len(geometry['lows'])}."),
            _rule("range_width", range_width_pct >= cfg["rectangle_min_range_width_pct"], f"Average range width was {range_width_pct:.2%} of price."),
            _rule("stable_range", width_change <= cfg["rectangle_max_width_change_pct"], f"Boundary-width change was {width_change:.2%} of price."),
            _rule("line_fit", geometry["upper_residual"] <= cfg["line_touch_tolerance_pct"] and geometry["lower_residual"] <= cfg["line_touch_tolerance_pct"], f"Maximum upper/lower residuals were {geometry['upper_residual']:.2%}/{geometry['lower_residual']:.2%}."),
            _rule("confirmed_pivots", True, "Range tests use only pivots whose confirmation candles have completed."),
        ]
        if not all(rule["passed"] for rule in rules):
            continue
        status, confirmation, state = _line_state(frame, candidate, upper, lower, direction, cfg)
        geometry["apex_after"] = None
        explanation = ("An eligible prior uptrend entered a horizontal, repeatedly tested range; only an upper-range close confirms continuation." if direction == "bullish" else "An eligible prior downtrend entered a horizontal, repeatedly tested range; only a lower-range close confirms the bearish continuation signal.")
        evidence = _geometric_evidence(frame, candidate, geometry, state, explanation, direction)
        evidence.update({
            "range_width_pct": round(range_width_pct * 100, 4), "support_level": round(lower.at(geometry["end"]), 4), "resistance_level": round(upper.at(geometry["end"]), 4),
            "resistance_touches": [{"date": point.date, "price": round(point.price, 4)} for point in geometry["highs"]],
            "support_touches": [{"date": point.date, "price": round(point.price, 4)} for point in geometry["lows"]],
            "annotations": [{
                "type": "polyline", "name": "rectangle", "points": [
                    {"date": frame.at[geometry["start"], "Date"], "price": round(upper.at(geometry["start"]), 4)},
                    {"date": frame.at[geometry["end"], "Date"], "price": round(upper.at(geometry["end"]), 4)},
                    {"date": frame.at[geometry["end"], "Date"], "price": round(lower.at(geometry["end"]), 4)},
                    {"date": frame.at[geometry["start"], "Date"], "price": round(lower.at(geometry["start"]), 4)},
                    {"date": frame.at[geometry["start"], "Date"], "price": round(upper.at(geometry["start"]), 4)},
                ],
            }],
        })
        level = upper.at(geometry["end"]) if direction == "bullish" else lower.at(geometry["end"])
        invalidation = lower.at(geometry["end"]) if direction == "bullish" else upper.at(geometry["end"])
        return _finding(symbol, pattern_id, frame, status, direction, candidate, level, confirmation, invalidation, evidence, rules)
    return None


def bullish_rectangle(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect_rectangle(symbol, candles, "bullish_rectangle", "bullish", config)


def bearish_rectangle(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    return _detect_rectangle(symbol, candles, "bearish_rectangle", "bearish", config)


def _cup_candidates(pivots: list[Pivot]) -> list[list[Pivot]]:
    candidates = []
    for end in range(len(pivots) - 1, 2, -1):
        candidate = pivots[end - 3:end + 1]
        if "".join(point.kind for point in candidate) == "HLHL":
            candidates.append(candidate)
    return candidates


def cup_and_handle(symbol: str, candles: pd.DataFrame, config: dict | None = None) -> dict | None:
    cfg = {**DEFAULTS, **(config or {})}
    try:
        prepared = _prepared(candles, cfg)
    except ValueError as exc:
        return _insufficient(symbol, "cup_and_handle", str(exc))
    frame, pivots = prepared["frame"], prepared["pivots"]
    for left_rim, bottom, right_rim, handle_low in _cup_candidates(pivots):
        cup_duration = right_rim.index - left_rim.index
        handle_duration = handle_low.index - right_rim.index
        rim_mean = (left_rim.price + right_rim.price) / 2
        cup_depth = (rim_mean - bottom.price) / rim_mean if rim_mean else np.inf
        rim_spread = abs(left_rim.price - right_rim.price) / rim_mean if rim_mean else np.inf
        handle_retracement = (right_rim.price - handle_low.price) / (right_rim.price - bottom.price) if right_rim.price > bottom.price else np.inf
        bottom_slice = frame.iloc[left_rim.index:right_rim.index + 1]
        bottom_zone = bottom_slice[bottom_slice["Low"].astype(float) <= bottom.price * (1 + cfg["cup_bottom_zone_pct"])]
        trend_ok, trend_pct = _trend(frame, left_rim, "up", cfg["minimum_trend_pct"])
        rounded = (
            len(bottom_zone) >= cfg["cup_min_bottom_zone_candles"]
            and bottom.index - left_rim.index >= cfg["cup_min_side_sessions"]
            and right_rim.index - bottom.index >= cfg["cup_min_side_sessions"]
        )
        rules = [
            _rule("prior_uptrend", trend_ok, f"10-session pre-cup trend was {trend_pct:.2%}."),
            _rule("cup_duration", cfg["cup_min_duration_sessions"] <= cup_duration <= cfg["cup_max_duration_sessions"], f"Cup duration was {cup_duration} sessions."),
            _rule("cup_depth", cfg["cup_min_depth_pct"] <= cup_depth <= cfg["cup_max_depth_pct"], f"Cup depth was {cup_depth:.2%}."),
            _rule("rim_similarity", rim_spread <= cfg["cup_rim_tolerance_pct"], f"Rim spread was {rim_spread:.2%}."),
            _rule("rounded_bottom", rounded, f"Bottom-zone candles: {len(bottom_zone)}; left/right cup sides: {bottom.index - left_rim.index}/{right_rim.index - bottom.index} sessions."),
            _rule("handle_after_right_rim", cfg["handle_min_sessions"] <= handle_duration <= cfg["handle_max_sessions"] and handle_duration < cup_duration, f"Handle duration was {handle_duration} sessions."),
            _rule("handle_retracement", 0 <= handle_retracement <= cfg["handle_max_retracement_pct"], f"Handle retracement was {handle_retracement:.2%} of cup depth."),
            _rule("confirmed_pivots", True, "Rims, bottom and handle low are used only after their later pivot confirmations."),
        ]
        if not all(rule["passed"] for rule in rules):
            continue
        resistance = rim_mean
        upper = TrendLine(0.0, resistance, resistance)
        lower = TrendLine(0.0, handle_low.price, handle_low.price)
        candidate = [left_rim, bottom, right_rim, handle_low]
        status, confirmation, state = _line_state(frame, candidate, upper, lower, "bullish", cfg)
        annotation = {
            "type": "polyline", "name": "cup_and_handle", "points": [
                {"date": left_rim.date, "price": round(left_rim.price, 4)}, {"date": bottom.date, "price": round(bottom.price, 4)},
                {"date": right_rim.date, "price": round(right_rim.price, 4)}, {"date": handle_low.date, "price": round(handle_low.price, 4)},
            ],
        }
        trendlines = [
            {"name": "cup_resistance", "start_date": left_rim.date, "end_date": frame.at[len(frame) - 1, "Date"], "start_price": round(resistance, 4), "end_price": round(resistance, 4), "slope": 0.0, "slope_pct_per_session": 0.0},
            {"name": "handle_invalidation", "start_date": right_rim.date, "end_date": frame.at[len(frame) - 1, "Date"], "start_price": round(handle_low.price, 4), "end_price": round(handle_low.price, 4), "slope": 0.0, "slope_pct_per_session": 0.0},
        ]
        evidence = {
            "explanation": "A rounded, multi-session cup recovers to a comparable right rim, then forms a smaller handle; only a close above rim resistance confirms the experimental pattern.",
            "left_rim": {"date": left_rim.date, "known_date": left_rim.known_date, "price": round(left_rim.price, 4)},
            "right_rim": {"date": right_rim.date, "known_date": right_rim.known_date, "price": round(right_rim.price, 4)},
            "cup_bottom": {"date": bottom.date, "known_date": bottom.known_date, "price": round(bottom.price, 4), "zone_candles": len(bottom_zone)},
            "handle": {"start_date": right_rim.date, "low_date": handle_low.date, "known_date": handle_low.known_date, "low": round(handle_low.price, 4), "duration_sessions": handle_duration},
            "cup_duration_sessions": cup_duration, "cup_depth_pct": round(cup_depth * 100, 4), "rim_spread_pct": round(rim_spread * 100, 4),
            "handle_retracement_pct": round(handle_retracement * 100, 4), "resistance_level": round(resistance, 4),
            "breakout_condition": "Close above average rim resistance plus configured buffer.", "invalidation_condition": "Close below the confirmed handle low plus configured buffer.",
            "pivot_confirmation_dates": [point.known_date for point in candidate], "trendlines": trendlines, "annotations": [annotation], **state,
        }
        return _finding(symbol, "cup_and_handle", frame, status, "bullish", candidate, resistance, confirmation, handle_low.price, evidence, rules)
    return None


DETECTORS: dict[str, Callable[[str, pd.DataFrame, dict | None], dict | None]] = {
    "head_and_shoulders": head_and_shoulders, "inverse_head_and_shoulders": inverse_head_and_shoulders,
    "double_top": double_top, "double_bottom": double_bottom,
    "triple_top": triple_top, "triple_bottom": triple_bottom,
    "ascending_triangle": ascending_triangle, "descending_triangle": descending_triangle,
    "symmetrical_triangle": symmetrical_triangle, "rising_wedge": rising_wedge,
    "falling_wedge": falling_wedge, "bullish_flag": bullish_flag,
    "bearish_flag": bearish_flag, "bullish_pennant": bullish_pennant,
    "bearish_pennant": bearish_pennant, "bullish_rectangle": bullish_rectangle,
    "bearish_rectangle": bearish_rectangle, "cup_and_handle": cup_and_handle,
}
