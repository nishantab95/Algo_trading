from __future__ import annotations

import numpy as np
import pandas as pd

from app.strategies.primitives.conditions import evaluate_logic
from app.strategies.schemas import CatalogStrategy
from app.strategies.validator import validate_strategy


def generate_strategy_signals(data:pd.DataFrame,strategy:CatalogStrategy) -> pd.DataFrame:
    validation=validate_strategy(strategy,set(data.columns))
    if not validation.valid: raise ValueError("; ".join(validation.errors) or f"Strategy status is {validation.status}")
    frames=[]
    for symbol,group in data.groupby("Ticker",sort=False):
        frame=group.sort_values("Date").copy()
        entry=evaluate_logic(frame,strategy.entry)
        if strategy.filters: entry &= evaluate_logic(frame,strategy.filters)
        value=-1 if strategy.direction=="short" else 1
        frame[strategy.strategy_id]=np.where(entry,value,0).astype(int)
        frames.append(frame)
    return pd.concat(frames,ignore_index=True).sort_values(["Date","Ticker"])
