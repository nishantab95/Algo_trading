from __future__ import annotations

import re
import numpy as np
import pandas as pd


def ensure_indicator(df: pd.DataFrame, name: str) -> pd.Series:
    if name in df: return df[name]
    match = re.fullmatch(r"SMA_(\d+)", name)
    if match: df[name] = df["Close"].rolling(int(match.group(1))).mean(); return df[name]
    match = re.fullmatch(r"EMA_(\d+)", name)
    if match: df[name] = df["Close"].ewm(span=int(match.group(1)), adjust=False).mean(); return df[name]
    match = re.fullmatch(r"ROC_(\d+)", name)
    if match: df[name] = df["Close"].pct_change(int(match.group(1))) * 100; return df[name]
    match = re.fullmatch(r"ROLLING_HIGH_(\d+)", name)
    if match: df[name] = df["High"].rolling(int(match.group(1))).max(); return df[name]
    match = re.fullmatch(r"ROLLING_LOW_(\d+)", name)
    if match: df[name] = df["Low"].rolling(int(match.group(1))).min(); return df[name]
    if name == "PRICE_ZSCORE_20":
        mean=df["Close"].rolling(20).mean(); std=df["Close"].rolling(20).std().replace(0,np.nan); df[name]=(df["Close"]-mean)/std; return df[name]
    if name == "RANGE_PCT": df[name]=(df["High"]-df["Low"])/df["Close"].replace(0,np.nan)*100; return df[name]
    if name == "BODY_PCT": df[name]=(df["Close"]-df["Open"])/df["Open"].replace(0,np.nan)*100; return df[name]
    if name == "GAP_PCT": df[name]=(df["Open"]/df["Close"].shift(1)-1)*100; return df[name]
    raise KeyError(f"Indicator column is unavailable: {name}")


def operand(df: pd.DataFrame, value):
    if isinstance(value, str): return ensure_indicator(df, value)
    return value
