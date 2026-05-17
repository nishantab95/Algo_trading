"""
Unified runtime configuration for the interactive algo trading terminal.

This module intentionally contains both immutable structural paths and mutable
session state used by the Flask cockpit, paper trading engine, and strategy
selection layer.
"""

from __future__ import annotations

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = BASE_DIR

DATA_DIR = os.path.join(BASE_DIR, "data", "raw")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
CONSOLIDATED_FILE = os.path.join(BASE_DIR, "data", "processed_universe.csv")
STRATEGY_REPORT_FILE = os.path.join(REPORTS_DIR, "global_strategy_summary.csv")
ASSET_REPORT_FILE = os.path.join(REPORTS_DIR, "asset_performance_leaderboard.csv")

LEGACY_DATA_SOURCE = r"D:\Git\algo trading\data_strategies\data"

INITIAL_CAPITAL = 1000000.00
MAX_PORTFOLIO_POSITIONS = 10
PER_TRADE_RISK_PCT = 0.01
BAR_INTERVAL = "1d"
YFINANCE_SUFFIX = ".NS"
EXCHANGE_CODE = "NSE"

DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 5000

ACTIVE_PORTFOLIO: list[dict] = []
ZERODHA_CONNECTED = False
API_KEY = ""
API_SECRET = ""
ACCESS_TOKEN = ""
REQUEST_TOKEN = ""

CUSTOM_STRATEGIES: dict[str, str] = {}
ACTIVE_STRATEGIES: set[str] = set()

TICKER_LIST = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
    "SUNPHARMA", "TITAN", "BAJFINANCE", "HCLTECH", "WIPRO", "ULTRACEMCO",
    "NTPC", "POWERGRID", "ONGC", "TATASTEEL", "ADANIENT", "ADANIPORTS",
    "JSWSTEEL", "COALINDIA", "TECHM", "NESTLEIND", "BAJAJFINSV", "M&M",
    "HDFCLIFE", "SBILIFE", "INDUSINDBK", "DIVISLAB", "CIPLA", "DRREDDY",
    "APOLLOHOSP", "EICHERMOT", "HEROMOTOCO", "BRITANNIA", "GRASIM",
    "HINDALCO", "VEDL", "BPCL", "IOC", "SHRIRAMFIN", "PIDILITIND", "DABUR",
]

BASE_STRATEGY_COLUMNS = [
    "Volatility_Breakout",
    "Golden_Cross",
    "EMA_Crossover",
    "RSI_Oversold",
    "RSI_Overbought",
    "MACD_Histogram_Momentum",
    "Bollinger_Mean_Reversion",
    "Volume_Spike",
    "Trend_Filter",
    "Turtle_Breakout",
    "BB_Squeeze_Breakout",
    "SuperTrend_Mimic",
    "Momentum_20",
    "EMA21_Mean_Reversion",
    "Support_Bounce",
]

STRATEGY_COLUMNS = BASE_STRATEGY_COLUMNS

REPORT_DISPLAY_COLUMNS = [
    "Strategy",
    "Avg_Return_Per_Asset_pct",
    "Median_Return_pct",
    "Total_Trades_Executed",
    "Average_Win_Rate_pct",
    "Global_Profit_Factor",
    "Avg_Win_Return_pct",
    "Avg_Loss_Return_pct",
    "Win_Loss_Ratio",
    "Max_Drawdown_pct",
    "Sharpe_Ratio",
    "Market_Coverage_Hit_Rate_pct",
]


def ensure_directories() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)


def all_strategy_columns() -> list[str]:
    return BASE_STRATEGY_COLUMNS + list(CUSTOM_STRATEGIES.keys())


def enabled_strategy_columns() -> list[str]:
    if not ACTIVE_STRATEGIES:
        return all_strategy_columns()
    return [strategy for strategy in all_strategy_columns() if strategy in ACTIVE_STRATEGIES]


def set_strategy_enabled(strategy_name: str, enabled: bool) -> None:
    valid = set(all_strategy_columns())
    if strategy_name not in valid:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    if not ACTIVE_STRATEGIES:
        ACTIVE_STRATEGIES.update(valid)
    if enabled:
        ACTIVE_STRATEGIES.add(strategy_name)
    else:
        ACTIVE_STRATEGIES.discard(strategy_name)


def add_custom_strategy(strategy_name: str, condition: str) -> None:
    clean_name = strategy_name.strip().replace(" ", "_")
    if not clean_name:
        raise ValueError("Strategy name cannot be empty.")
    if clean_name in BASE_STRATEGY_COLUMNS:
        raise ValueError(f"{clean_name} is a protected baseline strategy.")
    CUSTOM_STRATEGIES[clean_name] = condition
    ACTIVE_STRATEGIES.add(clean_name)


def update_zerodha_session(api_key: str, api_secret: str, access_token: str, request_token: str = "") -> None:
    global ZERODHA_CONNECTED, API_KEY, API_SECRET, ACCESS_TOKEN, REQUEST_TOKEN
    API_KEY = api_key.strip()
    API_SECRET = api_secret.strip()
    ACCESS_TOKEN = access_token.strip()
    REQUEST_TOKEN = request_token.strip()
    ZERODHA_CONNECTED = bool(API_KEY and API_SECRET and (ACCESS_TOKEN or REQUEST_TOKEN))


def to_yfinance_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if symbol.endswith(".NS") or symbol.endswith(".BO"):
        return symbol
    return f"{symbol}{YFINANCE_SUFFIX}"


def to_file_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if symbol.endswith(".NS") or symbol.endswith(".BO"):
        return symbol[:-3]
    return symbol


def load_tickers_from_data_dir() -> list[str]:
    if not os.path.isdir(DATA_DIR):
        return []
    return sorted(
        os.path.splitext(filename)[0].upper()
        for filename in os.listdir(DATA_DIR)
        if filename.lower().endswith(".csv")
    )


def get_full_ticker_universe() -> list[str]:
    universe = set(to_file_symbol(ticker) for ticker in TICKER_LIST)
    universe.update(load_tickers_from_data_dir())
    return sorted(universe)
