from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.backtesting.models import BacktestResult


def export_result(result: BacktestResult, reports_root: str | Path) -> Path:
    target = Path(reports_root) / "backtests" / result.run_id
    target.mkdir(parents=True, exist_ok=True)
    _json(target / "config.json", result.config.to_dict())
    _json(target / "summary.json", result.summary())
    _json(target / "metrics.json", result.metrics)
    _json(target / "warnings.json", result.warnings)
    pd.DataFrame([trade.to_dict() for trade in result.trades]).to_csv(target / "trades.csv", index=False)
    pd.DataFrame(result.equity_curve).to_csv(target / "equity_curve.csv", index=False)
    pd.DataFrame(result.daily_summary).to_csv(target / "daily_summary.csv", index=False)
    return target


def _json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding="utf-8")
