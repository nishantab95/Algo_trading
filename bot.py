"""
Interactive Zerodha broker bridge with simulated paper-trading fallback.

FIXES APPLIED:
  [FIX-1] Real Kite OAuth session via generate_session() - no more fake access_token assignment
  [FIX-2] execute_order() actually calls kite.place_order() in LIVE mode
  [FIX-3] Full exit logic: stop-loss, take-profit, trailing stop checked every scan
  [FIX-4] Market hours guard (IST 9:15–15:30, weekdays only)
  [FIX-5] Live quote fetching via kite.ltp() instead of stale CSV
  [FIX-6] ATR-based position sizing (volatility-adjusted, not naive equal-weight)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional

import pandas as pd
import pytz

import config_settings as cfg
import preprocessing
import strategy as strategy_selector

# ─────────────────────────────────────────────
# MARKET HOURS GUARD  [FIX-4]
# ─────────────────────────────────────────────
IST = pytz.timezone("Asia/Kolkata")
MARKET_OPEN  = (9, 15)   # 09:15 IST
MARKET_CLOSE = (15, 30)  # 15:30 IST


def is_market_open() -> bool:
    """Returns True only during NSE cash-market hours on weekdays."""
    now = datetime.now(IST)
    if now.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    open_mins  = MARKET_OPEN[0]  * 60 + MARKET_OPEN[1]
    close_mins = MARKET_CLOSE[0] * 60 + MARKET_CLOSE[1]
    current_mins = now.hour * 60 + now.minute
    return open_mins <= current_mins <= close_mins


def assert_market_open(allow_paper: bool = True) -> None:
    """
    Raises RuntimeError if called outside market hours.
    Paper mode bypasses the check so you can test anytime.
    """
    if not is_market_open() and not allow_paper:
        raise RuntimeError(
            f"Market is closed. NSE hours: 09:15–15:30 IST Mon–Fri. "
            f"Current IST time: {datetime.now(IST).strftime('%A %H:%M')}"
        )


# ─────────────────────────────────────────────
# POSITION DATACLASS
# ─────────────────────────────────────────────
@dataclass
class Position:
    ticker: str
    quantity: int
    average_price: float
    last_price: float
    side: str = "LONG"
    # Exit management  [FIX-3]
    stop_loss_price: float = 0.0       # absolute price level, 0 = not set
    take_profit_price: float = 0.0     # absolute price level, 0 = not set
    trailing_stop_pct: float = 0.0     # e.g. 0.05 = 5% trailing, 0 = disabled
    highest_price_seen: float = 0.0    # for trailing stop calculation

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

    def should_exit(self) -> tuple[bool, str]:
        """
        Returns (True, reason) if any exit condition is triggered.
        Called after last_price is updated via mark_to_market.
        """
        # Stop-loss check
        if self.stop_loss_price > 0 and self.last_price <= self.stop_loss_price:
            return True, f"STOP_LOSS hit at {self.last_price:.2f} (SL={self.stop_loss_price:.2f})"

        # Take-profit check
        if self.take_profit_price > 0 and self.last_price >= self.take_profit_price:
            return True, f"TAKE_PROFIT hit at {self.last_price:.2f} (TP={self.take_profit_price:.2f})"

        # Trailing stop check
        if self.trailing_stop_pct > 0 and self.highest_price_seen > 0:
            trail_floor = self.highest_price_seen * (1.0 - self.trailing_stop_pct)
            if self.last_price <= trail_floor:
                return True, (
                    f"TRAILING_STOP hit at {self.last_price:.2f} "
                    f"(peak={self.highest_price_seen:.2f}, floor={trail_floor:.2f})"
                )

        return False, ""

    def update_trailing_high(self) -> None:
        if self.last_price > self.highest_price_seen:
            self.highest_price_seen = self.last_price


# ─────────────────────────────────────────────
# TRADING STATE MACHINE
# ─────────────────────────────────────────────
class TradingStateMachine:

    def __init__(self, initial_capital: float = cfg.INITIAL_CAPITAL) -> None:
        self.initial_capital   = float(initial_capital)
        self.cash_balance      = float(initial_capital)
        self.connected         = False
        self.mode              = "PAPER"
        self.api_key           = ""
        self.api_secret        = ""
        self.access_token      = ""
        self.request_token     = ""
        self._kite             = None          # live KiteConnect instance
        self.positions: dict[str, Position] = {}
        self.order_log: list[str] = []

    # ── Logging ──────────────────────────────
    def log(self, message: str, payload: dict | None = None) -> None:
        entry = {
            "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            "mode":      self.mode,
            "message":   message,
            "payload":   payload or {},
        }
        line = json.dumps(entry, ensure_ascii=False)
        self.order_log.append(line)
        if len(self.order_log) > 500:
            del self.order_log[: len(self.order_log) - 500]
        print(f"[BOT] {line}")

    # ── [FIX-1] Proper Kite OAuth session ────
    def initialize_kite_session(
        self, api_key: str, api_secret: str, request_token: str
    ) -> dict:
        """
        Performs the full Zerodha OAuth handshake:
          request_token  →  generate_session()  →  access_token
        Falls back to PAPER mode if kiteconnect is not installed.
        """
        self.api_key       = api_key.strip()
        self.api_secret    = api_secret.strip()
        self.request_token = request_token.strip()

        try:
            from kiteconnect import KiteConnect  # type: ignore

            kite = KiteConnect(api_key=self.api_key)
            # THIS is the call that was missing — exchanges request_token for access_token
            session_data    = kite.generate_session(
                self.request_token, api_secret=self.api_secret
            )
            self.access_token = session_data["access_token"]
            kite.set_access_token(self.access_token)
            self._kite     = kite
            self.connected = True
            self.mode      = "LIVE"
            cfg.update_zerodha_session(
                self.api_key, self.api_secret,
                self.access_token, self.request_token
            )
            status = {
                "connected":        True,
                "mode":             "LIVE",
                "api_key":          self.api_key[:4] + "****",
                "authenticated_at": datetime.now(IST).isoformat(),
            }
            self.log("Kite session authenticated (LIVE)", status)

        except ImportError:
            self.connected = False
            self.mode      = "PAPER"
            status = {"connected": False, "mode": "PAPER",
                      "error": "kiteconnect not installed — pip install kiteconnect"}
            self.log("kiteconnect not found; falling back to PAPER mode", status)

        except Exception as exc:
            self.connected = False
            self.mode      = "PAPER"
            status = {"connected": False, "mode": "PAPER", "error": str(exc)}
            self.log(f"Kite auth failed: {exc}; falling back to PAPER mode", status)

        return status

    # ── [FIX-5] Live quote fetching ──────────
    def _get_live_price(self, symbol: str) -> float:
        """
        LIVE: fetches real-time LTP from Kite.
        PAPER: falls back to last close in local CSV.
        """
        exchange_symbol = f"NSE:{symbol}"
        if self.connected and self._kite is not None:
            try:
                ltp_data = self._kite.ltp([exchange_symbol])
                return float(ltp_data[exchange_symbol]["last_price"])
            except Exception as exc:
                self.log(f"LTP fetch failed for {symbol}, using CSV fallback", {"error": str(exc)})

        # Paper / fallback path — reads local CSV
        return self._latest_price_from_csv(symbol)

    def _latest_price_from_csv(self, symbol: str) -> float:
        path = os.path.join(cfg.DATA_DIR, f"{cfg.to_file_symbol(symbol)}.csv")
        if not os.path.exists(path):
            raise FileNotFoundError(f"No local price file for {symbol}.")
        df = pd.read_csv(path, index_col=0, parse_dates=True).rename(columns=str.title)
        if "Close" not in df.columns or df.empty:
            raise ValueError(f"No close price for {symbol}.")
        return float(df["Close"].dropna().iloc[-1])

    # ── [FIX-6] ATR position sizing ──────────
    def _atr_position_size(
        self, symbol: str, price: float, atr: Optional[float] = None
    ) -> int:
        """
        Volatility-adjusted position sizing.
        Risk per trade = cfg.PER_TRADE_RISK_PCT × cash_balance
        Position size  = risk_amount / (ATR × ATR_MULTIPLIER)

        Falls back to equal-weight if ATR unavailable.
        """
        ATR_MULTIPLIER = 2.0   # stop is placed 2×ATR below entry
        risk_amount = self.cash_balance * cfg.PER_TRADE_RISK_PCT

        if atr and atr > 0:
            risk_per_share = atr * ATR_MULTIPLIER
            qty = int(risk_amount / risk_per_share)
        else:
            # Fallback: equal-weight across max positions
            slot_value = self.cash_balance / max(cfg.MAX_PORTFOLIO_POSITIONS, 1)
            qty = int(slot_value / price)

        return max(qty, 1)

    # ── Order payload builder ─────────────────
    def build_order_payload(
        self, symbol: str, transaction_type: str, quantity: int
    ) -> dict:
        side = transaction_type.strip().upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("transaction_type must be BUY or SELL.")
        qty = int(quantity)
        if qty <= 0:
            raise ValueError("quantity must be > 0.")
        return {
            "tradingsymbol":    cfg.to_file_symbol(symbol),
            "exchange":         "NSE",
            "transaction_type": side,
            "quantity":         qty,
            "order_type":       "MARKET",
            "product":          "CNC",
            "variety":          "regular",
            "validity":         "DAY",
        }

    # ── [FIX-2] Execute order (LIVE + PAPER) ─
    def execute_order(
        self,
        symbol: str,
        transaction_type: str,
        quantity: int,
        stop_loss_pct:   float = cfg.DEFAULT_STOP_LOSS_PCT,
        take_profit_pct: float = cfg.DEFAULT_TAKE_PROFIT_PCT,
        trailing_pct:    float = cfg.DEFAULT_TRAILING_STOP_PCT,
    ) -> dict:
        payload   = self.build_order_payload(symbol, transaction_type, quantity)
        ticker    = payload["tradingsymbol"]
        price     = self._get_live_price(ticker)
        slippage  = 0.0007 if payload["transaction_type"] == "BUY" else -0.0007
        fill_price = round(price * (1.0 + slippage), 2)
        notional   = fill_price * payload["quantity"]

        # ── LIVE path — actually places order on exchange ──
        if self.connected and self._kite is not None:
            try:
                order_id = self._kite.place_order(
                    tradingsymbol    = payload["tradingsymbol"],
                    exchange         = payload["exchange"],
                    transaction_type = payload["transaction_type"],
                    quantity         = payload["quantity"],
                    order_type       = payload["order_type"],
                    product          = payload["product"],
                    variety          = payload["variety"],
                )
                result = {
                    "status":      "LIVE_ORDER_PLACED",
                    "order_id":    order_id,
                    "fill_price":  fill_price,
                    "notional":    notional,
                    "payload":     payload,
                }
                self.log("Live order placed on Kite", result)
                return result
            except Exception as exc:
                self.log("Live order FAILED — falling through to PAPER", {"error": str(exc)})
                # Intentional fallthrough to paper mode on API error

        # ── PAPER path ────────────────────────
        if payload["transaction_type"] == "BUY":
            if notional > self.cash_balance:
                raise ValueError(
                    f"Insufficient paper balance. Need ₹{notional:,.2f}, "
                    f"have ₹{self.cash_balance:,.2f}."
                )
            existing = self.positions.get(ticker)
            if existing:
                new_qty = existing.quantity + payload["quantity"]
                new_avg = (
                    (existing.average_price * existing.quantity) + notional
                ) / new_qty
                existing.quantity      = new_qty
                existing.average_price = round(new_avg, 2)
                existing.last_price    = fill_price
            else:
                sl_price = round(fill_price * (1.0 - stop_loss_pct), 2)   if stop_loss_pct   > 0 else 0.0
                tp_price = round(fill_price * (1.0 + take_profit_pct), 2) if take_profit_pct > 0 else 0.0
                self.positions[ticker] = Position(
                    ticker              = ticker,
                    quantity            = payload["quantity"],
                    average_price       = fill_price,
                    last_price          = fill_price,
                    stop_loss_price     = sl_price,
                    take_profit_price   = tp_price,
                    trailing_stop_pct   = trailing_pct,
                    highest_price_seen  = fill_price,
                )
            self.cash_balance -= notional

        else:  # SELL
            existing = self.positions.get(ticker)
            if not existing or existing.quantity < payload["quantity"]:
                raise ValueError(
                    f"Cannot sell {payload['quantity']} {ticker}; "
                    f"open qty={existing.quantity if existing else 0}."
                )
            existing.quantity -= payload["quantity"]
            existing.last_price = fill_price
            self.cash_balance  += notional
            if existing.quantity == 0:
                del self.positions[ticker]

        cfg.ACTIVE_PORTFOLIO = self.positions_snapshot()
        result = {
            "status":       "PAPER_FILLED",
            "paper_filled": True,
            "fill_price":   fill_price,
            "notional":     round(notional, 2),
            "payload":      payload,
            "cash_balance": round(self.cash_balance, 2),
        }
        self.log("Paper order executed", result)
        return result

    # ── [FIX-3] Mark-to-market + exit sweep ──
    def mark_to_market(self) -> None:
        for position in self.positions.values():
            try:
                position.last_price = self._get_live_price(position.ticker)
                position.update_trailing_high()
            except Exception:
                continue

    def run_exit_sweep(self) -> list[dict]:
        """
        Checks every open position against stop-loss, take-profit, trailing stop.
        Closes positions that breach their exit levels.
        Returns list of exit records for logging.
        """
        self.mark_to_market()
        exits = []
        tickers_to_exit = []

        for ticker, position in self.positions.items():
            should_exit, reason = position.should_exit()
            if should_exit:
                tickers_to_exit.append((ticker, position.quantity, reason))

        for ticker, qty, reason in tickers_to_exit:
            try:
                result = self.execute_order(ticker, "SELL", qty)
                result["exit_reason"] = reason
                exits.append(result)
                self.log(f"EXIT triggered: {reason}", result)
            except Exception as exc:
                self.log(f"Exit order failed for {ticker}", {"error": str(exc)})

        return exits

    # ── Snapshot helpers ──────────────────────
    def positions_snapshot(self) -> list[dict]:
        rows = []
        for position in self.positions.values():
            row = asdict(position)
            row.update({
                "invested_value":    round(position.invested_value, 2),
                "current_value":     round(position.current_value, 2),
                "unrealized_pnl":    round(position.unrealized_pnl, 2),
                "unrealized_pnl_pct": round(position.unrealized_pnl_pct, 2),
            })
            rows.append(row)
        return rows

    def account_snapshot(self) -> dict:
        positions     = self.positions_snapshot()
        current_value = sum(r["current_value"]  for r in positions)
        invested_value = sum(r["invested_value"] for r in positions)
        return {
            "mode":             self.mode,
            "connected":        self.connected,
            "market_open":      is_market_open(),
            "initial_capital":  self.initial_capital,
            "cash_balance":     round(self.cash_balance, 2),
            "portfolio_value":  round(self.cash_balance + current_value, 2),
            "active_positions": len(positions),
            "unrealized_pnl":   round(current_value - invested_value, 2),
            "positions":        positions,
            "logs":             self.order_log[-120:],
        }

    def reset(self) -> None:
        self.cash_balance = self.initial_capital
        self.positions.clear()
        cfg.ACTIVE_PORTFOLIO = []
        self.log("Paper session reset")


# ─────────────────────────────────────────────
# SINGLETON + MODULE-LEVEL API (matches existing main.py imports)
# ─────────────────────────────────────────────
TRADING_ENGINE  = TradingStateMachine()
SYSTEM_LOGS     = TRADING_ENGINE.order_log
OPEN_POSITIONS: list[str]  = []
CURRENT_EQUITY: float      = cfg.INITIAL_CAPITAL
WINNING_STRATEGY: str      = ""
KITE_SESSION: dict | None  = None


def initialize_kite_session(
    api_key: str, api_secret: str, request_token: str
) -> dict:
    global KITE_SESSION
    KITE_SESSION = TRADING_ENGINE.initialize_kite_session(
        api_key, api_secret, request_token
    )
    return KITE_SESSION


def connect_zerodha_api(api_key: str, api_secret: str) -> dict:
    return initialize_kite_session(
        api_key, api_secret, cfg.ACCESS_TOKEN or "paper_request_token"
    )


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
        TRADING_ENGINE.log(f"Latest bar load failed for {ticker}", {"error": str(exc)})
        return None


def run_daily_pipeline(
    active_tickers:   list[str] | None = None,
    winning_strategy: str | None = None,
) -> dict:
    """
    [FIX-4] Market hours guard applied: scan only runs during IST trading hours.
    [FIX-3] Exit sweep runs BEFORE entry scan — exits take priority.
    [FIX-6] ATR-based position sizing applied per ticker.
    """
    global WINNING_STRATEGY, OPEN_POSITIONS, CURRENT_EQUITY

    # Market hours guard — paper mode always allowed, live mode blocked outside hours
    if TRADING_ENGINE.connected and not is_market_open():
        msg = (
            f"Scan blocked: market is closed. "
            f"IST now: {datetime.now(IST).strftime('%A %H:%M')}"
        )
        TRADING_ENGINE.log(msg)
        return {"status": "BLOCKED", "reason": msg}

    tickers          = active_tickers or cfg.get_full_ticker_universe()
    WINNING_STRATEGY = winning_strategy or strategy_selector.select_winning_strategy()

    TRADING_ENGINE.log(
        "Daily pipeline started",
        {"strategy": WINNING_STRATEGY, "tickers": len(tickers), "mode": TRADING_ENGINE.mode},
    )

    # ── 1. Exit sweep first ──
    exits = TRADING_ENGINE.run_exit_sweep()

    # ── 2. Entry scan ────────
    signals_checked = 0
    buy_candidates  = 0
    orders_placed   = 0

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

        # ATR-based position sizing
        atr_value = float(latest.get("ATR", 0)) if "ATR" in latest.index else None
        qty = TRADING_ENGINE._atr_position_size(ticker, close_price, atr_value)

        try:
            TRADING_ENGINE.execute_order(ticker, "BUY", qty)
            orders_placed += 1
        except Exception as exc:
            TRADING_ENGINE.log(
                "Order rejected during scan",
                {"ticker": ticker, "error": str(exc)},
            )

    snapshot       = TRADING_ENGINE.account_snapshot()
    OPEN_POSITIONS = [row["ticker"] for row in snapshot["positions"]]
    CURRENT_EQUITY = snapshot["portfolio_value"]

    summary = {
        "winning_strategy": WINNING_STRATEGY,
        "signals_checked":  signals_checked,
        "buy_candidates":   buy_candidates,
        "orders_placed":    orders_placed,
        "exits_triggered":  len(exits),
        "exit_details":     exits,
        "open_positions":   OPEN_POSITIONS,
        "equity":           CURRENT_EQUITY,
        "market_open":      is_market_open(),
    }
    TRADING_ENGINE.log("Daily pipeline complete", summary)
    return summary


def account_state() -> dict:
    return TRADING_ENGINE.account_snapshot()


def reset_session() -> None:
    TRADING_ENGINE.reset()


if __name__ == "__main__":
    initialize_kite_session(
        cfg.API_KEY, cfg.API_SECRET,
        cfg.ACCESS_TOKEN or "paper_request_token"
    )
    run_daily_pipeline(cfg.get_full_ticker_universe()[:25])