"""
Interactive Zerodha broker bridge with simulated paper-trading fallback.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime

import pandas as pd

import config_settings as cfg
import preprocessing
import strategy as strategy_selector


@dataclass
class Position:
    ticker: str
    quantity: int
    average_price: float
    last_price: float
    side: str = "LONG"

    @property
    def invested_value(self) -> float:
        return self.quantity * self.average_price

    @property
    def current_value(self) -> float:
        return self.quantity * self.last_price

    @property
    def unrealized_pnl(self) -> float:
        return self.current_value - self.invested_value

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.invested_value <= 0:
            return 0.0
        return self.unrealized_pnl / self.invested_value * 100.0


class TradingStateMachine:
    def __init__(self, initial_capital: float = cfg.INITIAL_CAPITAL) -> None:
        self.initial_capital = float(initial_capital)
        self.cash_balance = float(initial_capital)
        self.connected = False
        self.mode = "PAPER"
        self.api_key = ""
        self.api_secret = ""
        self.access_token = ""
        self.request_token = ""
        self.positions: dict[str, Position] = {}
        self.order_log: list[str] = []

    def log(self, message: str, payload: dict | None = None) -> None:
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": self.mode,
            "message": message,
            "payload": payload or {},
        }
        line = json.dumps(entry, ensure_ascii=False)
        self.order_log.append(line)
        if len(self.order_log) > 500:
            del self.order_log[: len(self.order_log) - 500]
        print(f"[BOT] {line}")

    def initialize_kite_session(self, api_key: str, api_secret: str, request_token: str) -> dict:
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.request_token = request_token.strip()
        self.access_token = request_token.strip()
        self.connected = bool(self.api_key and self.api_secret and self.request_token)
        self.mode = "LIVE" if self.connected else "PAPER"
        cfg.update_zerodha_session(self.api_key, self.api_secret, self.access_token, self.request_token)
        status = {
            "connected": self.connected,
            "mode": self.mode,
            "api_key": self.api_key[:4] + "****" if self.api_key else "",
            "authenticated_at": datetime.now().isoformat() if self.connected else "",
        }
        self.log("Kite session initialized" if self.connected else "Paper mode active", status)
        return status

    def build_order_payload(self, symbol: str, transaction_type: str, quantity: int) -> dict:
        side = transaction_type.strip().upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("transaction_type must be BUY or SELL.")
        qty = int(quantity)
        if qty <= 0:
            raise ValueError("quantity must be greater than zero.")
        return {
            "tradingsymbol": cfg.to_file_symbol(symbol),
            "exchange": "NSE",
            "transaction_type": side,
            "quantity": qty,
            "order_type": "MARKET",
            "product": "CNC",
            "variety": "regular",
            "validity": "DAY",
        }

    def _latest_price(self, symbol: str) -> float:
        path = os.path.join(cfg.DATA_DIR, f"{cfg.to_file_symbol(symbol)}.csv")
        if not os.path.exists(path):
            raise FileNotFoundError(f"No local price file found for {symbol}.")
        df = pd.read_csv(path, index_col=0, parse_dates=True).rename(columns=str.title)
        if "Close" not in df.columns or df.empty:
            raise ValueError(f"No close price available for {symbol}.")
        return float(df["Close"].dropna().iloc[-1])

    def execute_order(self, symbol: str, transaction_type: str, quantity: int) -> dict:
        payload = self.build_order_payload(symbol, transaction_type, quantity)
        ticker = payload["tradingsymbol"]
        price = self._latest_price(ticker)
        slippage = 0.0007 if payload["transaction_type"] == "BUY" else -0.0007
        fill_price = round(price * (1.0 + slippage), 2)
        notional = fill_price * payload["quantity"]

        if self.connected:
            result = {
                "status": "LIVE_PAYLOAD_READY",
                "paper_filled": False,
                "fill_price": fill_price,
                "notional": notional,
                "payload": payload,
            }
            self.log("Live Kite order payload formatted", result)
            return result

        if payload["transaction_type"] == "BUY":
            if notional > self.cash_balance:
                raise ValueError(f"Insufficient paper balance. Need {notional:,.2f}, available {self.cash_balance:,.2f}.")
            existing = self.positions.get(ticker)
            if existing:
                new_qty = existing.quantity + payload["quantity"]
                new_avg = ((existing.average_price * existing.quantity) + notional) / new_qty
                existing.quantity = new_qty
                existing.average_price = round(new_avg, 2)
                existing.last_price = fill_price
            else:
                self.positions[ticker] = Position(ticker, payload["quantity"], fill_price, fill_price)
            self.cash_balance -= notional
        else:
            existing = self.positions.get(ticker)
            if not existing or existing.quantity < payload["quantity"]:
                raise ValueError(f"Cannot sell {payload['quantity']} {ticker}; open quantity is {existing.quantity if existing else 0}.")
            existing.quantity -= payload["quantity"]
            existing.last_price = fill_price
            self.cash_balance += notional
            if existing.quantity == 0:
                del self.positions[ticker]

        cfg.ACTIVE_PORTFOLIO = self.positions_snapshot()
        result = {
            "status": "PAPER_FILLED",
            "paper_filled": True,
            "fill_price": fill_price,
            "notional": round(notional, 2),
            "payload": payload,
            "cash_balance": round(self.cash_balance, 2),
        }
        self.log("Paper order executed", result)
        return result

    def mark_to_market(self) -> None:
        for position in self.positions.values():
            try:
                position.last_price = self._latest_price(position.ticker)
            except Exception:
                continue

    def positions_snapshot(self) -> list[dict]:
        self.mark_to_market()
        rows = []
        for position in self.positions.values():
            row = asdict(position)
            row.update(
                {
                    "invested_value": round(position.invested_value, 2),
                    "current_value": round(position.current_value, 2),
                    "unrealized_pnl": round(position.unrealized_pnl, 2),
                    "unrealized_pnl_pct": round(position.unrealized_pnl_pct, 2),
                }
            )
            rows.append(row)
        return rows

    def account_snapshot(self) -> dict:
        positions = self.positions_snapshot()
        current_value = sum(row["current_value"] for row in positions)
        invested_value = sum(row["invested_value"] for row in positions)
        unrealized = current_value - invested_value
        return {
            "mode": self.mode,
            "connected": self.connected,
            "initial_capital": self.initial_capital,
            "cash_balance": round(self.cash_balance, 2),
            "portfolio_value": round(self.cash_balance + current_value, 2),
            "active_positions": len(positions),
            "unrealized_pnl": round(unrealized, 2),
            "positions": positions,
            "logs": self.order_log[-120:],
        }

    def reset(self) -> None:
        self.cash_balance = self.initial_capital
        self.positions.clear()
        cfg.ACTIVE_PORTFOLIO = []
        self.log("Paper session reset")


TRADING_ENGINE = TradingStateMachine()

SYSTEM_LOGS = TRADING_ENGINE.order_log
OPEN_POSITIONS: list[str] = []
CURRENT_EQUITY: float = cfg.INITIAL_CAPITAL
WINNING_STRATEGY: str = ""
KITE_SESSION: dict | None = None


def initialize_kite_session(api_key: str, api_secret: str, request_token: str) -> dict:
    global KITE_SESSION
    KITE_SESSION = TRADING_ENGINE.initialize_kite_session(api_key, api_secret, request_token)
    return KITE_SESSION


def connect_zerodha_api(api_key: str, api_secret: str) -> dict:
    return initialize_kite_session(api_key, api_secret, cfg.ACCESS_TOKEN or "paper_request_token")


def execute_order(symbol: str, transaction_type: str, quantity: int) -> dict:
    return TRADING_ENGINE.execute_order(symbol, transaction_type, quantity)


def _load_latest_bar(ticker: str) -> pd.Series | None:
    path = os.path.join(cfg.DATA_DIR, f"{cfg.to_file_symbol(ticker)}.csv")
    if not os.path.exists(path):
        return None
    try:
        raw = pd.read_csv(path, index_col=0, parse_dates=True).rename(columns=str.title)
        raw = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
        raw.index = pd.to_datetime(raw.index)
        raw = raw.sort_index()
        featured = preprocessing.engineer_technical_indicators(raw)
        signaled = preprocessing.compute_strategy_signals(featured)
        if signaled.empty:
            return None
        return signaled.iloc[-1]
    except Exception as exc:
        TRADING_ENGINE.log(f"Failed latest bar load for {ticker}", {"error": str(exc)})
        return None


def run_daily_pipeline(active_tickers: list[str] | None = None, winning_strategy: str | None = None) -> dict:
    global WINNING_STRATEGY, OPEN_POSITIONS, CURRENT_EQUITY
    tickers = active_tickers or cfg.get_full_ticker_universe()
    WINNING_STRATEGY = winning_strategy or strategy_selector.select_winning_strategy()
    TRADING_ENGINE.log("Daily signal scan started", {"strategy": WINNING_STRATEGY, "tickers": len(tickers)})

    signals_checked = 0
    orders_placed = 0
    buy_candidates = 0

    for ticker in tickers:
        if len(TRADING_ENGINE.positions) >= cfg.MAX_PORTFOLIO_POSITIONS:
            break
        latest = _load_latest_bar(ticker)
        if latest is None:
            continue
        signals_checked += 1
        signal_value = int(latest.get(WINNING_STRATEGY, 0))
        if signal_value != 1:
            continue
        buy_candidates += 1
        close_price = float(latest["Close"])
        qty = max(int((TRADING_ENGINE.cash_balance / max(cfg.MAX_PORTFOLIO_POSITIONS, 1)) / close_price), 1)
        try:
            TRADING_ENGINE.execute_order(ticker, "BUY", qty)
            orders_placed += 1
        except Exception as exc:
            TRADING_ENGINE.log("Order rejected during scan", {"ticker": ticker, "error": str(exc)})

    snapshot = TRADING_ENGINE.account_snapshot()
    OPEN_POSITIONS = [row["ticker"] for row in snapshot["positions"]]
    CURRENT_EQUITY = snapshot["portfolio_value"]
    summary = {
        "winning_strategy": WINNING_STRATEGY,
        "signals_checked": signals_checked,
        "buy_candidates": buy_candidates,
        "orders_placed": orders_placed,
        "open_positions": OPEN_POSITIONS,
        "equity": CURRENT_EQUITY,
    }
    TRADING_ENGINE.log("Daily signal scan complete", summary)
    return summary


def account_state() -> dict:
    return TRADING_ENGINE.account_snapshot()


def reset_session() -> None:
    TRADING_ENGINE.reset()


if __name__ == "__main__":
    initialize_kite_session(cfg.API_KEY, cfg.API_SECRET, cfg.ACCESS_TOKEN or "paper_request_token")
    run_daily_pipeline(cfg.get_full_ticker_universe()[:25])
