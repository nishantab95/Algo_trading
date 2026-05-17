"""
Feature engineering and dynamic strategy signal generation.
"""

from __future__ import annotations

import ast
import os
import re

import numpy as np
import pandas as pd
import ta

import config_settings as cfg

SAFE_FUNCTIONS = {"abs": abs, "round": round}
SAFE_NUMPY_ATTRIBUTES = {"where", "maximum", "minimum", "abs", "sign", "logical_and", "logical_or"}
SAFE_SERIES_METHODS = {"shift", "rolling", "mean", "std", "min", "max", "sum", "fillna", "clip"}


def engineer_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or len(df) < 220:
        return pd.DataFrame()

    try:
        df = df.copy()
        df["SMA_20"] = df["Close"].rolling(window=20).mean()
        df["SMA_50"] = df["Close"].rolling(window=50).mean()
        df["EMA_9"] = ta.trend.ema_indicator(close=df["Close"], window=9)
        df["EMA_21"] = ta.trend.ema_indicator(close=df["Close"], window=21)
        df["EMA_50"] = ta.trend.ema_indicator(close=df["Close"], window=50)
        df["EMA_200"] = ta.trend.ema_indicator(close=df["Close"], window=200)
        df["RSI_14"] = ta.momentum.rsi(close=df["Close"], window=14)
        df["MACD"] = ta.trend.macd(close=df["Close"], window_slow=26, window_fast=12)
        df["MACD_Signal"] = ta.trend.macd_signal(
            close=df["Close"], window_slow=26, window_fast=12, window_sign=9
        )
        df["MACD_Hist"] = ta.trend.macd_diff(close=df["Close"])

        stoch = ta.momentum.StochasticOscillator(
            high=df["High"], low=df["Low"], close=df["Close"], window=14, smooth_window=3
        )
        df["Stochastic_%K"] = stoch.stoch()
        df["Stochastic_%D"] = stoch.stoch_signal()
        df["ATR_14"] = ta.volatility.average_true_range(
            high=df["High"], low=df["Low"], close=df["Close"], window=14
        )

        bb = ta.volatility.BollingerBands(close=df["Close"], window=20, window_dev=2)
        df["Bollinger_Upper"] = bb.bollinger_hband()
        df["Bollinger_Middle"] = bb.bollinger_mavg()
        df["Bollinger_Lower"] = bb.bollinger_lband()
        df["Bollinger_Width"] = bb.bollinger_wband()

        df["Volume_SMA_20"] = df["Volume"].rolling(window=20).mean()
        vol_std = df["Volume"].rolling(window=20).std()
        df["Volume_Z_Score"] = (df["Volume"] - df["Volume_SMA_20"]) / vol_std
        df["Volume_Z_Score"] = df["Volume_Z_Score"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        return df.dropna().copy()

    except Exception as exc:
        print(f"[PREPROCESS] Indicator error: {exc}")
        return pd.DataFrame()


def _sanitize_strategy_name(strategy_name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]+", "_", strategy_name.strip()).strip("_")
    if not clean:
        raise ValueError("Strategy name must contain letters, numbers, or underscores.")
    if clean[0].isdigit():
        clean = f"Custom_{clean}"
    return clean


def _validate_strategy_ast(expression: str, allowed_names: set[str]) -> ast.Expression:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Strategy syntax error: {exc}") from exc

    allowed_nodes = (
        ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.IfExp, ast.Compare,
        ast.Call, ast.Name, ast.Load, ast.Constant, ast.Subscript, ast.Attribute,
        ast.List, ast.Tuple, ast.keyword, ast.And, ast.Or, ast.Not, ast.Invert, ast.USub, ast.UAdd,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
        ast.BitAnd, ast.BitOr, ast.BitXor, ast.Eq, ast.NotEq, ast.Lt, ast.LtE,
        ast.Gt, ast.GtE,
    )

    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise ValueError(f"Unsupported expression element: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in allowed_names:
            raise ValueError(f"Unknown variable in rule: {node.id}")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise ValueError("Private attributes are not allowed in strategy rules.")
            if isinstance(node.value, ast.Name) and node.value.id == "np":
                if node.attr not in SAFE_NUMPY_ATTRIBUTES:
                    raise ValueError(f"np.{node.attr} is not allowed.")
            elif node.attr not in SAFE_SERIES_METHODS:
                raise ValueError(f"Method .{node.attr} is not allowed.")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id not in SAFE_FUNCTIONS:
                raise ValueError(f"Function {node.func.id} is not allowed.")
            if isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "np":
                    if node.func.attr not in SAFE_NUMPY_ATTRIBUTES:
                        raise ValueError(f"np.{node.func.attr} is not allowed.")
                elif node.func.attr not in SAFE_SERIES_METHODS:
                    raise ValueError(f"Method .{node.func.attr} is not allowed.")
    return tree


def _evaluate_condition(df: pd.DataFrame, expression: str) -> pd.Series:
    env = {column: df[column] for column in df.columns}
    env.update({"df": df, "np": np, **SAFE_FUNCTIONS})
    tree = _validate_strategy_ast(expression, set(env.keys()))
    result = eval(compile(tree, "<custom_strategy>", "eval"), {"__builtins__": {}}, env)

    if isinstance(result, pd.Series):
        series = result.reindex(df.index)
    elif isinstance(result, np.ndarray):
        if len(result) != len(df):
            raise ValueError("Custom strategy array result length does not match dataframe length.")
        series = pd.Series(result, index=df.index)
    elif isinstance(result, (bool, int, float, np.bool_, np.number)):
        series = pd.Series(result, index=df.index)
    else:
        raise ValueError("Custom strategy must return a pandas Series, numpy array, or scalar signal.")

    if series.dtype == bool:
        return series.fillna(False).astype(int)

    numeric = pd.to_numeric(series, errors="coerce").fillna(0.0)
    return pd.Series(np.where(numeric > 0, 1, np.where(numeric < 0, -1, 0)), index=df.index)


def inject_custom_strategy(strategy_name: str, mathematical_condition_string: str, df: pd.DataFrame | None = None):
    """
    Registers or applies a custom strategy.

    When df is None, the strategy is compiled against a sample asset and stored
    in config_settings.CUSTOM_STRATEGIES. When df is provided, the compiled rule
    is applied and the dataframe with a new shifted signal column is returned.
    """
    clean_name = _sanitize_strategy_name(strategy_name)
    expression = mathematical_condition_string.strip()
    if not expression:
        raise ValueError("Custom strategy rule cannot be empty.")

    if df is None:
        sample_tickers = cfg.load_tickers_from_data_dir()
        if not sample_tickers:
            raise ValueError("No local data is available to validate the custom strategy.")
        sample_path = os.path.join(cfg.DATA_DIR, f"{sample_tickers[0]}.csv")
        raw = pd.read_csv(sample_path, index_col=0, parse_dates=True).rename(columns=str.title)
        featured = engineer_technical_indicators(raw[["Open", "High", "Low", "Close", "Volume"]])
        if featured.empty:
            raise ValueError("Could not build indicator frame for custom strategy validation.")
        _evaluate_condition(featured, expression)
        cfg.add_custom_strategy(clean_name, expression)
        print(f"[PREPROCESS] Custom strategy injected: {clean_name} -> {expression}")
        return {"strategy_name": clean_name, "condition": expression}

    output = df.copy()
    signal = _evaluate_condition(output, expression)
    output[clean_name] = signal.shift(1).fillna(0).astype(int)
    return output


def compute_strategy_signals(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    try:
        df = df.copy()
        df["Volatility_Breakout"] = np.where(
            (df["Close"] > df["Bollinger_Upper"]) & (df["Volume_Z_Score"] > 1.5), 1, 0
        )
        golden = (df["EMA_50"] > df["EMA_200"]) & (df["EMA_50"].shift(1) <= df["EMA_200"].shift(1))
        df["Golden_Cross"] = np.where(golden, 1, 0)
        ema_cross = (df["EMA_9"] > df["EMA_21"]) & (df["EMA_9"].shift(1) <= df["EMA_21"].shift(1))
        df["EMA_Crossover"] = np.where(ema_cross, 1, 0)
        df["RSI_Oversold"] = np.where((df["RSI_14"] > 30) & (df["RSI_14"].shift(1) <= 30), 1, 0)
        df["RSI_Overbought"] = np.where((df["RSI_14"] < 70) & (df["RSI_14"].shift(1) >= 70), -1, 0)
        macd_flip = (df["MACD_Hist"] > 0) & (df["MACD_Hist"].shift(1) <= 0)
        df["MACD_Histogram_Momentum"] = np.where(macd_flip, 1, 0)
        outside_lower = df["Close"].shift(1) < df["Bollinger_Lower"].shift(1)
        reenter = df["Close"] > df["Bollinger_Lower"]
        df["Bollinger_Mean_Reversion"] = np.where(outside_lower & reenter, 1, 0)
        df["Volume_Spike"] = np.where(df["Volume"] > (2.5 * df["Volume_SMA_20"]), 1, 0)
        df["Trend_Filter"] = np.where((df["Close"] > df["EMA_200"]) & (df["EMA_9"] > df["EMA_21"]), 1, -1)
        high_20 = df["High"].rolling(20).max()
        df["Turtle_Breakout"] = np.where(df["Close"] > high_20.shift(1), 1, 0)
        width_min_20 = df["Bollinger_Width"].rolling(20).min()
        squeeze = df["Bollinger_Width"].shift(1) <= width_min_20.shift(1)
        breakout = df["Close"] > df["Bollinger_Upper"]
        df["BB_Squeeze_Breakout"] = np.where(squeeze & breakout, 1, 0)
        hl2 = (df["High"] + df["Low"]) / 2.0
        upper_band = hl2 + (3.0 * df["ATR_14"])
        df["SuperTrend_Mimic"] = np.where(df["Close"] > upper_band.shift(1), 1, 0)
        roc_20 = df["Close"].pct_change(20)
        df["Momentum_20"] = np.where(roc_20 > 0.05, 1, np.where(roc_20 < -0.05, -1, 0))
        ema21_std = (df["Close"] - df["EMA_21"]).rolling(20).std()
        deviation = (df["Close"] - df["EMA_21"]) / ema21_std.replace(0, np.nan)
        df["EMA21_Mean_Reversion"] = np.where(deviation < -2.5, 1, np.where(deviation > 2.5, -1, 0))
        low_50 = df["Low"].rolling(50).min()
        near_high = (df["Close"] - df["Low"]) / (df["High"] - df["Low"]).replace(0, np.nan)
        at_support = df["Low"] <= (low_50 * 1.01)
        df["Support_Bounce"] = np.where(at_support & (near_high > 0.65), 1, 0)

        for column in cfg.BASE_STRATEGY_COLUMNS:
            df[column] = df[column].shift(1).fillna(0).astype(int)

        for custom_name, condition in cfg.CUSTOM_STRATEGIES.items():
            df = inject_custom_strategy(custom_name, condition, df)

        return df

    except Exception as exc:
        print(f"[PREPROCESS] Strategy signal error: {exc}")
        return pd.DataFrame()


def process_single_stock(file_path: str, ticker: str) -> pd.DataFrame:
    try:
        raw = pd.read_csv(file_path, index_col=0, parse_dates=True)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        raw = raw.rename(columns=str.title)
        required = ["Open", "High", "Low", "Close", "Volume"]
        if any(column not in raw.columns for column in required):
            return pd.DataFrame()
        raw = raw[required].copy()
        raw.index = pd.to_datetime(raw.index)
        raw = raw.sort_index()
        raw = raw[~raw.index.duplicated(keep="first")]
        featured = engineer_technical_indicators(raw)
        if featured.empty:
            return pd.DataFrame()
        signaled = compute_strategy_signals(featured)
        if signaled.empty:
            return pd.DataFrame()
        signaled["Ticker"] = ticker
        return signaled.reset_index().rename(columns={"index": "Date"})
    except Exception as exc:
        print(f"[PREPROCESS] Failed {ticker}: {exc}")
        return pd.DataFrame()


def consolidate_universe(tickers: list[str] | None = None) -> pd.DataFrame:
    cfg.ensure_directories()
    universe = tickers or cfg.get_full_ticker_universe()
    frames: list[pd.DataFrame] = []
    processed = 0
    skipped = 0

    print("=" * 72)
    print(f"[PREPROCESS] Consolidating universe | tickers={len(universe)}")
    print("=" * 72)

    for index, ticker in enumerate(universe, start=1):
        path = os.path.join(cfg.DATA_DIR, f"{ticker}.csv")
        if not os.path.exists(path):
            skipped += 1
            continue
        frame = process_single_stock(path, ticker)
        if frame.empty:
            skipped += 1
            continue
        frames.append(frame)
        processed += 1
        if index % 50 == 0:
            print(f"[PREPROCESS] Progress {index}/{len(universe)}")

    if not frames:
        print("[PREPROCESS] ERROR: No frames consolidated.")
        return pd.DataFrame()

    master = pd.concat(frames, axis=0, ignore_index=True)
    master.to_csv(cfg.CONSOLIDATED_FILE, index=False)
    print("=" * 72)
    print(f"[PREPROCESS] Saved consolidated file: {cfg.CONSOLIDATED_FILE}")
    print(f"[PREPROCESS] Rows={len(master):,} processed={processed} skipped={skipped}")
    print("=" * 72)
    return master


if __name__ == "__main__":
    cfg.ensure_directories()
    consolidate_universe()
