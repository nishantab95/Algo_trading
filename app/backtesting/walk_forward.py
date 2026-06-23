from __future__ import annotations

from dataclasses import replace

import pandas as pd

from app.backtesting.engine import BacktestEngine
from app.backtesting.models import BacktestConfig


def generate_folds(start_date: str, end_date: str, train_days: int = 504, test_days: int = 126, expanding: bool = True) -> list[dict]:
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date); folds = []; train_start = start
    train_end = train_start + pd.Timedelta(days=train_days)
    while train_end < end:
        test_start = train_end + pd.Timedelta(days=1); test_end = min(test_start + pd.Timedelta(days=test_days), end)
        folds.append({"train_start": str(train_start.date()), "train_end": str(train_end.date()), "test_start": str(test_start.date()), "test_end": str(test_end.date())})
        if test_end >= end: break
        if not expanding: train_start += pd.Timedelta(days=test_days)
        train_end += pd.Timedelta(days=test_days)
    return folds


def run_walk_forward(config: BacktestConfig, data: pd.DataFrame, train_days: int = 504, test_days: int = 126, expanding: bool = True) -> dict:
    if not config.start_date or not config.end_date: raise ValueError("Walk-forward requires start_date and end_date.")
    folds = generate_folds(config.start_date, config.end_date, train_days, test_days, expanding)
    results = []
    for number, fold in enumerate(folds, 1):
        test_config = replace(config, start_date=fold["test_start"], end_date=fold["test_end"])
        result = BacktestEngine(test_config).run(data)
        results.append({"fold": number, **fold, "metrics": result.metrics, "warnings": result.warnings})
    returns = [row["metrics"]["net_return_pct"] for row in results]
    return {"mode": "expanding" if expanding else "rolling", "folds": results, "aggregate": {"fold_count": len(results), "average_test_return_pct": sum(returns)/len(returns) if returns else 0.0, "profitable_folds": sum(value > 0 for value in returns)}}
