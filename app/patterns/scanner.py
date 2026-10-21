from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.discovery.providers import parse_instrument
from app.patterns.detectors import DEFAULTS, DETECTORS, pivot_candidates, prepare_pattern_data, validate_candles
from app.patterns.registry import IMPLEMENTED_IDS, REGISTRY_VERSION, registry_payload


HISTORICAL_REVIEW_VERSION = "4a.1"


class PatternScanService:
    """Scans cached Discovery candles; it never downloads data or touches trades."""

    def __init__(self, data_service, fundamental_service=None) -> None:
        self.data_service = data_service
        self.fundamental_service = fundamental_service
        self.storage_dir = data_service.storage_dir
        self.scan_path = self.storage_dir / "pattern_scans.json"
        self.history_path = self.storage_dir / "historical_pattern_reviews.json"

    def _load(self) -> dict:
        if not self.scan_path.exists():
            return {"scans": {}}
        try:
            return json.loads(self.scan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"scans": {}}

    def _save(self, payload: dict) -> None:
        temporary = self.scan_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.scan_path)

    def _load_historical(self) -> dict:
        if not self.history_path.exists():
            return {"reviews": {}}
        try:
            return json.loads(self.history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"reviews": {}}

    def _save_historical(self, payload: dict) -> None:
        temporary = self.history_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.history_path)

    def registry(self) -> list[dict]:
        return registry_payload()

    def _cached_frame(self, canonical_symbol: str) -> pd.DataFrame | None:
        instrument = parse_instrument(canonical_symbol)
        path = self.data_service._cache_path(instrument)
        if not path.exists():
            return None
        try:
            return pd.read_csv(path)
        except (OSError, pd.errors.ParserError):
            return None

    def scan(self, universe: str, pattern_ids: list[str] | None = None, config: dict | None = None) -> dict:
        selected = list(dict.fromkeys(pattern_ids or sorted(IMPLEMENTED_IDS)))
        unknown = set(selected) - IMPLEMENTED_IDS
        if unknown:
            raise ValueError(f"Only implemented patterns can be scanned: {', '.join(sorted(unknown))}.")
        if not selected:
            raise ValueError("Select at least one implemented pattern.")
        effective_config = {**DEFAULTS, **(config or {})}
        symbols = self.data_service.list_symbols(universe)
        inputs = []
        frames: dict[str, pd.DataFrame] = {}
        skipped = []
        for symbol in symbols:
            frame = self._cached_frame(symbol["symbol"])
            if frame is None or frame.empty:
                skipped.append({"symbol": symbol["symbol"], "reason": "No cached daily OHLCV data. Use Update Data first."})
                continue
            frames[symbol["symbol"]] = frame
            inputs.append({"symbol": symbol["symbol"], "latest_date": str(frame["Date"].iloc[-1])})
        fingerprint_input = {"registry_version": REGISTRY_VERSION, "fundamental_version": "3f.1", "universe": universe, "patterns": sorted(selected), "config": effective_config, "inputs": inputs}
        fingerprint = hashlib.sha256(json.dumps(fingerprint_input, sort_keys=True).encode("utf-8")).hexdigest()
        scan_id = f"scan_{fingerprint[:16]}"
        saved = self._load()
        if scan_id in saved["scans"]:
            cached_result = saved["scans"][scan_id]
            # Technical detections may be reused, but their on-demand financial
            # snapshots still obey the independent statement/valuation policies.
            if self.fundamental_service is not None:
                for finding in cached_result.get("findings", []):
                    self._enrich_fundamentals(finding)
                self._save(saved)
            return {**cached_result, "reused": True}
        findings, history = [], []
        for symbol, frame in frames.items():
            try:
                prepared_config = {**effective_config, "_prepared": prepare_pattern_data(frame, effective_config)}
            except ValueError:
                # Each detector returns the established INSUFFICIENT_DATA payload
                # with its own validation message when cached data is malformed.
                prepared_config = effective_config
            for pattern_id in selected:
                finding = DETECTORS[pattern_id](symbol, frame, prepared_config)
                if finding is None:
                    continue
                finding["scan_id"] = scan_id
                finding["configuration_fingerprint"] = fingerprint
                chart_frame = frame.tail(120)
                finding["chart"] = {
                    "dates": chart_frame["Date"].astype(str).tolist(),
                    "closes": [round(float(value), 4) for value in chart_frame["Close"]],
                }
                current = finding["status"] == "FORMING" or (
                    finding["status"] == "CONFIRMED"
                    and finding["evidence"].get("sessions_since_confirmation", 999) <= effective_config["recent_confirmation_sessions"]
                )
                if current:
                    self._enrich_fundamentals(finding)
                    findings.append(finding)
                history.append(finding)
        self._annotate_overlaps(findings)
        health_order = {"GREEN": 0, "AMBER": 1, "UNKNOWN": 2, "RISKY": 3}
        findings.sort(key=lambda finding: (health_order.get(finding.get("fundamentals", {}).get("assessment", {}).get("health", "UNKNOWN"), 2), finding["symbol"], finding["pattern_id"]))
        result = {
            "scan_id": scan_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reused": False,
            "universe": universe,
            "patterns": selected,
            "detector_version": REGISTRY_VERSION,
            "configuration": effective_config,
            "configuration_fingerprint": fingerprint,
            "symbols_scanned": sorted(frames),
            "symbols_skipped": skipped,
            "matches_found": len(findings),
            "findings": findings,
            "history": history,
            "failure_summary": [row for row in skipped],
        }
        saved["scans"][scan_id] = result
        self._save(saved)
        return result

    @staticmethod
    def _event_chart(frame: pd.DataFrame, event: dict) -> dict:
        start_matches = frame.index[frame["Date"].astype(str) == str(event["formation_start_date"])]
        start = max(0, int(start_matches[0]) - 30) if len(start_matches) else 0
        terminal = event.get("invalidation_date") or event.get("confirmation_date") or event.get("last_observed_date")
        terminal_matches = frame.index[frame["Date"].astype(str) == str(terminal)]
        end = int(terminal_matches[-1]) + 1 if len(terminal_matches) else len(frame)
        window = frame.iloc[start:end]
        return {
            "dates": window["Date"].astype(str).tolist(),
            "closes": [round(float(value), 4) for value in window["Close"]],
        }

    @staticmethod
    def _historical_summary(events: list[dict], selected: list[str]) -> dict:
        patterns = {pattern_id: {"events": 0, "forming": 0, "confirmed": 0, "invalidated": 0, "overlapping": 0} for pattern_id in selected}
        for event in events:
            row = patterns[event["pattern_id"]]
            row["events"] += 1
            row[event["status"].lower()] += 1
            row["overlapping"] += int(bool(event.get("evidence", {}).get("overlapping_patterns")))
        return {
            "events": len(events),
            "forming": sum(row["forming"] for row in patterns.values()),
            "confirmed": sum(row["confirmed"] for row in patterns.values()),
            "invalidated": sum(row["invalidated"] for row in patterns.values()),
            "overlapping_events": sum(row["overlapping"] for row in patterns.values()),
            "by_pattern": patterns,
        }

    def historical_review(self, universe: str, pattern_ids: list[str] | None = None, config: dict | None = None, symbols: list[str] | None = None) -> dict:
        """Replay cached daily candles chronologically for research only.

        Each detector sees a prefix ending on the evaluation date.  This keeps
        pivot confirmation and breakout timing exactly as they were knowable.
        """
        selected = list(dict.fromkeys(pattern_ids or sorted(IMPLEMENTED_IDS)))
        unknown = set(selected) - IMPLEMENTED_IDS
        if unknown:
            raise ValueError(f"Only implemented patterns can be reviewed: {', '.join(sorted(unknown))}.")
        if not selected:
            raise ValueError("Select at least one implemented pattern.")
        effective_config = {**DEFAULTS, **(config or {})}
        requested = list(dict.fromkeys(
            parse_instrument(symbol).canonical_symbol
            for symbol in (symbols or [row["symbol"] for row in self.data_service.list_symbols(universe)])
        ))
        frames: dict[str, pd.DataFrame] = {}
        manifests: list[dict] = []
        skipped: list[dict] = []
        for symbol in requested:
            metadata = self.data_service.cache_metadata(symbol)
            raw = self._cached_frame(symbol)
            if raw is None or raw.empty:
                skipped.append({"symbol": symbol, "reason": "No cached daily OHLCV data. Use Update Data first."})
                continue
            try:
                frame = validate_candles(raw)
            except ValueError as exc:
                skipped.append({"symbol": symbol, "reason": str(exc)})
                continue
            data_hash = hashlib.sha256(frame.to_csv(index=False).encode("utf-8")).hexdigest()
            frames[symbol] = frame
            manifests.append({**metadata, "input_date_range": {"start": str(frame["Date"].iloc[0]), "end": str(frame["Date"].iloc[-1])}, "data_hash": data_hash})
        fingerprint_input = {
            "historical_review_version": HISTORICAL_REVIEW_VERSION, "registry_version": REGISTRY_VERSION,
            "universe": universe, "patterns": selected,
            "config": effective_config, "inputs": manifests,
        }
        fingerprint = hashlib.sha256(json.dumps(fingerprint_input, sort_keys=True).encode("utf-8")).hexdigest()
        review_id = f"history_{fingerprint[:16]}"
        saved = self._load_historical()
        if review_id in saved["reviews"]:
            return {**saved["reviews"][review_id], "reused": True}

        events: list[dict] = []
        event_by_key: dict[tuple[str, str, str], dict] = {}
        metadata_by_symbol = {row["symbol"]: row for row in manifests}
        for symbol, frame in frames.items():
            metadata = metadata_by_symbol[symbol]
            all_pivots = pivot_candidates(frame, effective_config["pivot_left"], effective_config["pivot_right"])
            known_pivots = []
            next_pivot = 0
            active_pattern_ids: set[str] = set()
            for evaluation_index in range(19, len(frame)):
                pivots_changed = False
                while next_pivot < len(all_pivots) and all_pivots[next_pivot].known_index <= evaluation_index:
                    pivot = all_pivots[next_pivot]
                    if not known_pivots or pivot.kind != known_pivots[-1].kind:
                        known_pivots.append(pivot)
                    elif (pivot.kind == "H" and pivot.price > known_pivots[-1].price) or (pivot.kind == "L" and pivot.price < known_pivots[-1].price):
                        known_pivots[-1] = pivot
                    next_pivot += 1
                    pivots_changed = True
                prefix = frame.iloc[:evaluation_index + 1]
                prepared_config = {**effective_config, "_prepared": {"frame": prefix, "pivots": list(known_pivots)}}
                evaluation_date = str(prefix["Date"].iloc[-1])
                # A new formation can only arise after a completed pivot is
                # available. Between such dates every already-detected event
                # is still re-evaluated daily, so breakouts, invalidations and
                # formation-window expiry occur on their exact candle without
                # needlessly recalculating every unrelated detector.
                patterns_to_evaluate = selected if pivots_changed else sorted(active_pattern_ids)
                for pattern_id in patterns_to_evaluate:
                    finding = DETECTORS[pattern_id](symbol, prefix, prepared_config)
                    if finding is None or finding["status"] == "INSUFFICIENT_DATA" or not finding.get("formation_start_date"):
                        active_pattern_ids.discard(pattern_id)
                        continue
                    key = (symbol, pattern_id, str(finding["formation_start_date"]))
                    event = event_by_key.get(key)
                    if event is None:
                        identity = hashlib.sha256("|".join((*key, fingerprint)).encode("utf-8")).hexdigest()[:20]
                        event = {
                            "event_id": f"event_{identity}", "symbol": symbol, "exchange": finding["exchange"],
                            "pattern_id": pattern_id, "pattern_name": finding["pattern_name"], "direction": finding["direction"],
                            "detector_version": REGISTRY_VERSION, "configuration_fingerprint": fingerprint,
                            "formation_start_date": finding["formation_start_date"], "formation_end_date": finding["formation_end_date"],
                            "first_detection_date": evaluation_date, "confirmation_date": None, "invalidation_date": None,
                            "status": "FORMING", "levels": finding.get("levels", {}), "pivots": finding.get("pivots", []),
                            "evidence": finding.get("evidence", {}), "data_source": metadata["source"],
                            "data_adjustment_policy": metadata["adjustment"], "input_date_range": metadata["input_date_range"],
                            "data_quality_warnings": list(metadata["data_quality_warnings"]), "last_observed_date": evaluation_date,
                        }
                        events.append(event)
                        event_by_key[key] = event
                    event["formation_end_date"] = finding["formation_end_date"]
                    event["last_observed_date"] = evaluation_date
                    event["levels"] = finding.get("levels", {})
                    event["pivots"] = finding.get("pivots", [])
                    event["evidence"] = finding.get("evidence", {})
                    confirmation_date = finding.get("signal_detection_date")
                    invalidation_date = finding.get("evidence", {}).get("invalidation_date")
                    if confirmation_date and event["confirmation_date"] is None:
                        event["confirmation_date"] = confirmation_date
                    if invalidation_date and event["invalidation_date"] is None:
                        event["invalidation_date"] = invalidation_date
                    event["status"] = "INVALIDATED" if event["invalidation_date"] else "CONFIRMED" if event["confirmation_date"] else "FORMING"
                    if event["status"] == "INVALIDATED":
                        active_pattern_ids.discard(pattern_id)
                    else:
                        active_pattern_ids.add(pattern_id)

        for event in events:
            input_end = metadata_by_symbol[event["symbol"]]["input_date_range"]["end"]
            if event["status"] == "INVALIDATED":
                event["review_classification"] = "INVALIDATED"
            elif event["last_observed_date"] != input_end:
                event["review_classification"] = "HISTORICAL_FORMATION"
            elif event["status"] == "CONFIRMED" and event.get("evidence", {}).get("sessions_since_confirmation", 999) <= effective_config["recent_confirmation_sessions"]:
                event["review_classification"] = "RECENTLY_CONFIRMED_AT_INPUT_END"
            elif event["status"] == "FORMING":
                event["review_classification"] = "FORMING_AT_INPUT_END"
            else:
                event["review_classification"] = "HISTORICAL_FORMATION"
        self._annotate_overlaps(events)
        for event in events:
            event["chart"] = self._event_chart(frames[event["symbol"]], event)
        events.sort(key=lambda event: (event["symbol"], event["first_detection_date"], event["pattern_id"]))
        result = {
            "review_id": review_id, "created_at": datetime.now(timezone.utc).isoformat(), "reused": False,
            "universe": universe, "symbols_requested": requested, "symbols_scanned": sorted(frames), "symbols_skipped": skipped,
            "patterns": selected, "detector_version": REGISTRY_VERSION, "configuration": effective_config,
            "historical_review_version": HISTORICAL_REVIEW_VERSION,
            "configuration_fingerprint": fingerprint, "data_manifest": manifests, "events": events,
            "summary": self._historical_summary(events, selected),
            "research_notice": "Historical pattern review is observational only. It does not calculate trade outcomes, win rates, or profitability.",
        }
        saved["reviews"][review_id] = result
        self._save_historical(saved)
        return result

    @staticmethod
    def _annotate_overlaps(findings: list[dict]) -> None:
        """Expose overlapping formations without collapsing either detection."""
        for index, left in enumerate(findings):
            left_start = pd.Timestamp(left["formation_start_date"])
            left_end = pd.Timestamp(left["formation_end_date"])
            for right in findings[index + 1:]:
                if left["symbol"] != right["symbol"]:
                    continue
                right_start = pd.Timestamp(right["formation_start_date"])
                right_end = pd.Timestamp(right["formation_end_date"])
                overlap_days = max(0, (min(left_end, right_end) - max(left_start, right_start)).days + 1)
                shortest_days = max(1, min((left_end - left_start).days + 1, (right_end - right_start).days + 1))
                overlap_ratio = overlap_days / shortest_days
                if overlap_ratio < 0.60:
                    continue
                for current, other in ((left, right), (right, left)):
                    current.setdefault("evidence", {}).setdefault("overlapping_patterns", []).append({
                        "pattern_id": other["pattern_id"],
                        "pattern_name": other["pattern_name"],
                        "overlap_ratio": round(overlap_ratio, 4),
                        "formation_window": {
                            "start": other["formation_start_date"],
                            "end": other["formation_end_date"],
                        },
                    })

    def _enrich_fundamentals(self, finding: dict) -> None:
        if self.fundamental_service is None:
            finding["fundamentals"] = {"assessment": {"health": "UNKNOWN", "valuation": {"classification": "UNKNOWN", "raw_multiples": {}}, "reasons": ["Fundamental analysis is unavailable."], "warnings": [], "checks": []}, "freshness": "missing", "valuation_freshness": "missing"}
            return
        try:
            finding["fundamentals"] = self.fundamental_service.get(finding["symbol"])
        except Exception as exc:
            finding["fundamentals"] = {"assessment": {"health": "UNKNOWN", "valuation": {"classification": "UNKNOWN", "raw_multiples": {}}, "reasons": ["Fundamental enrichment failed."], "warnings": [str(exc)], "checks": []}, "freshness": "failed", "valuation_freshness": "missing"}

    def get_scan(self, scan_id: str) -> dict | None:
        return self._load()["scans"].get(scan_id)

    def get_historical_review(self, review_id: str) -> dict | None:
        return self._load_historical()["reviews"].get(review_id)
