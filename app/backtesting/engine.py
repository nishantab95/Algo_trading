from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from app.backtesting.cost_model import CostModel, FeeSchedule
from app.backtesting.execution_model import ExecutionModel
from app.backtesting.metrics import calculate_metrics, metric_breakdown
from app.backtesting.models import BacktestConfig, BacktestResult, OrderEvent, Position, SignalEvent, Trade
from app.backtesting.portfolio import Portfolio
from app.backtesting.validators import require_valid_config


class BacktestEngine:
    """Event-driven, no-leverage simulator. Exits are evaluated before entries."""

    def __init__(self, config: BacktestConfig) -> None:
        require_valid_config(config)
        self.config = config
        custom = FeeSchedule("custom", **config.custom_cost_settings) if config.cost_model_name == "custom" else None
        self.cost_model = CostModel.named(config.cost_model_name, custom)
        self.execution = ExecutionModel(config.execution_price_model, config.slippage_bps, config.spread_bps)
        self.portfolio = Portfolio(config)
        self.orders: list[OrderEvent] = []
        self.trades: list[Trade] = []
        self.pending: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self._entry_dates: set[tuple[str, str]] = set()
        self.current_prices: dict[str, float] = {}

    def run(self, data: pd.DataFrame) -> BacktestResult:
        frame = self._prepare(data)
        if frame.empty: return self._empty_result("No valid rows in requested period.")
        timestamps = list(frame["Date"].drop_duplicates().sort_values())
        bars_by_time = {ts: group.set_index("Ticker") for ts, group in frame.groupby("Date", sort=True)}
        equity_curve: list[dict[str, Any]] = []
        daily: list[dict[str, Any]] = []
        last_prices: dict[str, float] = {}

        for index, timestamp in enumerate(timestamps):
            bars = bars_by_time[timestamp]
            starting_equity = self.portfolio.equity(last_prices)
            closed_before = len(self.trades); orders_before = len(self.orders)
            realized_before = self.portfolio.realized_pnl
            costs_before = sum(order.costs for order in self.orders if order.status == "FILLED")

            execution_prices = dict(last_prices)
            for symbol, bar in bars.iterrows():
                execution_prices[symbol] = float(bar["Open"] if self.config.execution_price_model == "next_open" else bar["Close"])
            self.current_prices = execution_prices
            self._execute_pending(index, timestamp, bars, "exit")
            self._execute_pending(index, timestamp, bars, "entry")
            for symbol, bar in bars.iterrows(): last_prices[symbol] = float(bar["Close"])
            self.current_prices = dict(last_prices)
            self._update_and_exit(timestamp, index, bars)
            self._observe_signals(timestamp, index, bars, len(timestamps))

            if index == len(timestamps) - 1:
                for symbol in list(self.portfolio.positions):
                    if symbol in bars.index: self._close(symbol, timestamp, bars.loc[symbol], "END_OF_BACKTEST", float(bars.loc[symbol]["Close"]), timestamp)

            equity = self.portfolio.equity(last_prices)
            self.portfolio.peak_equity = max(self.portfolio.peak_equity, equity)
            drawdown = (equity / self.portfolio.peak_equity - 1) * 100 if self.portfolio.peak_equity else 0.0
            position_value = self.portfolio.position_value(last_prices)
            gross_exposure = sum(abs(p.reserved_capital) for p in self.portfolio.positions.values())
            net_exposure = sum(p.reserved_capital * (1 if p.direction == "long" else -1) for p in self.portfolio.positions.values())
            unrealized = position_value - sum(p.reserved_capital for p in self.portfolio.positions.values())
            self.portfolio.exposure_observations.append(gross_exposure / equity if equity > 0 else 0.0)
            now = datetime.now(timezone.utc).isoformat()
            equity_curve.append({"timestamp": str(timestamp), "cash": round(self.portfolio.cash, 4), "position_value": round(position_value, 4), "total_equity": round(equity, 4), "drawdown_pct": round(drawdown, 4), "benchmark_value": None, "benchmark_drawdown_pct": None, "created_at": now})
            new_orders = self.orders[orders_before:]
            opened_today = sum(order.status == "FILLED" and order.reason.startswith(self.config.strategy_id) for order in new_orders)
            daily.append({"date": str(timestamp), "starting_equity": round(starting_equity, 4), "ending_equity": round(equity, 4), "realized_pnl": round(self.portfolio.realized_pnl-realized_before, 4), "unrealized_pnl": round(unrealized, 4), "gross_exposure": round(gross_exposure, 4), "net_exposure": round(net_exposure, 4), "trades_opened": opened_today, "trades_closed": len(self.trades) - closed_before, "costs": round(sum(order.costs for order in self.orders if order.status == "FILLED") - costs_before, 4), "created_at": now})

        metrics = calculate_metrics(self.trades, equity_curve, self.config.initial_capital, self.portfolio.turnover, self.portfolio.exposure_observations)
        return BacktestResult(str(uuid.uuid4()), self.config, self.trades, self.orders, equity_curve, daily, metrics, metric_breakdown(metrics), self.warnings)

    def _prepare(self, data: pd.DataFrame) -> pd.DataFrame:
        required = {"Date", "Ticker", "Open", "High", "Low", "Close", "Volume", self.config.strategy_id}
        missing = required - set(data.columns)
        if missing: raise ValueError(f"Backtest data missing columns: {sorted(missing)}")
        frame = data.copy(); frame["Date"] = pd.to_datetime(frame["Date"])
        frame = frame[frame["Ticker"].isin(self.config.symbols)]
        if self.config.start_date: frame = frame[frame["Date"] >= pd.Timestamp(self.config.start_date)]
        if self.config.end_date: frame = frame[frame["Date"] <= pd.Timestamp(self.config.end_date)]
        frame = frame.sort_values(["Date", "Ticker"]).drop_duplicates(["Date", "Ticker"], keep="last")
        if "Volume_SMA_20" not in frame: frame["Volume_SMA_20"] = frame.groupby("Ticker")["Volume"].transform(lambda x: x.rolling(20, min_periods=1).mean())
        return frame

    def _execute_pending(self, index: int, timestamp, bars: pd.DataFrame, kind: str) -> None:
        remaining = []
        for item in self.pending:
            if item["kind"] != kind: remaining.append(item); continue
            if item["due_index"] > index: remaining.append(item); continue
            symbol = item["symbol"]
            if symbol not in bars.index:
                remaining.append(item); continue
            bar = bars.loc[symbol]
            reference = self.execution.reference_price(bar)
            if item["kind"] == "entry": self._open(item["signal"], timestamp, bar, reference)
            else: self._close(symbol, timestamp, bar, item["reason"], reference, item.get("signal_time"))
        self.pending = remaining

    def _update_and_exit(self, timestamp, index: int, bars: pd.DataFrame) -> None:
        for symbol, position in list(self.portfolio.positions.items()):
            if symbol not in bars.index: continue
            if position.entry_time == timestamp and self.config.execution_price_model == "next_close":
                continue
            bar = bars.loc[symbol]; position.bars_held += 1
            position.highest_price = max(position.highest_price, float(bar["High"])); position.lowest_price = min(position.lowest_price, float(bar["Low"]))
            sign = 1 if position.direction == "long" else -1
            adverse = ((float(bar["Low"]) - position.entry_price) / position.entry_price * 100) if sign == 1 else ((position.entry_price - float(bar["High"])) / position.entry_price * 100)
            favorable = ((float(bar["High"]) - position.entry_price) / position.entry_price * 100) if sign == 1 else ((position.entry_price - float(bar["Low"])) / position.entry_price * 100)
            position.mae = min(position.mae, adverse); position.mfe = max(position.mfe, favorable)
            reason = None; reference = float(bar["Close"])
            # Conservative collision convention: stop is checked before target.
            if position.direction == "long":
                trail = position.highest_price * (1 - position.trailing_stop_pct)
                if float(bar["Low"]) <= position.stop_loss: reason, reference = "STOP_LOSS", min(position.stop_loss, float(bar["Open"]))
                elif float(bar["Low"]) <= trail and position.highest_price > position.entry_price: reason, reference = "TRAILING_STOP", min(trail, float(bar["Open"]))
                elif float(bar["High"]) >= position.target: reason, reference = "TARGET", max(position.target, float(bar["Open"]))
            else:
                trail = position.lowest_price * (1 + position.trailing_stop_pct)
                if float(bar["High"]) >= position.stop_loss: reason, reference = "STOP_LOSS", max(position.stop_loss, float(bar["Open"]))
                elif float(bar["High"]) >= trail and position.lowest_price < position.entry_price: reason, reference = "TRAILING_STOP", max(trail, float(bar["Open"]))
                elif float(bar["Low"]) <= position.target: reason, reference = "TARGET", min(position.target, float(bar["Open"]))
            if not reason and position.bars_held >= self.config.max_holding_bars: reason = "MAX_HOLDING_PERIOD"
            if reason:
                if self.config.exit_delay_bars > 0:
                    self.pending.append({"kind": "exit", "symbol": symbol, "reason": reason, "due_index": index + self.config.exit_delay_bars, "signal_time": timestamp})
                else: self._close(symbol, timestamp, bar, reason, reference, timestamp)

    def _observe_signals(self, timestamp, index: int, bars: pd.DataFrame, total_bars: int) -> None:
        for symbol, bar in bars.iterrows():
            value = pd.to_numeric(bar.get(self.config.strategy_id, 0), errors="coerce")
            raw = 0 if pd.isna(value) else int(np.sign(float(value)))
            if raw == 0: continue
            direction = "long" if raw > 0 else "short"
            if direction == "short" and self.config.direction_mode == "long_only": continue
            if direction == "long" and self.config.direction_mode == "short_only": continue
            existing = self.portfolio.positions.get(symbol)
            if existing and existing.direction != direction:
                if self.config.execution_price_model == "signal_close_for_research_only" and self.config.exit_delay_bars == 0:
                    self._close(symbol, timestamp, bar, "OPPOSITE_SIGNAL", float(bar["Close"]), timestamp)
                else:
                    due = index + 1 + self.config.exit_delay_bars
                    self.pending.append({"kind": "exit", "symbol": symbol, "reason": "OPPOSITE_SIGNAL", "due_index": due, "signal_time": timestamp})
                continue
            if existing and not self.config.allow_multiple_positions_per_symbol: continue
            day_key = (symbol, str(timestamp))
            if day_key in self._entry_dates and not self.config.allow_reentry_same_day: continue
            indicator_names = ["RSI_14", "ATR_14", "EMA_9", "EMA_21", "EMA_50", "EMA_200", "Volume_SMA_20"]
            indicators = {key: float(bar[key]) for key in indicator_names if key in bar and pd.notna(bar[key])}
            signal = SignalEvent(timestamp, symbol, self.config.strategy_id, direction, raw, f"{self.config.strategy_id} emitted {raw:+d}", indicators)
            if self.config.execution_price_model == "signal_close_for_research_only": self._open(signal, timestamp, bar, float(bar["Close"]))
            else:
                due = index + 1 + self.config.entry_delay_bars
                if due < total_bars: self.pending.append({"kind": "entry", "symbol": symbol, "signal": signal, "due_index": due})

    def _open(self, signal: SignalEvent, timestamp, bar, reference: float) -> None:
        symbol, direction = signal.symbol, signal.direction
        approved, reason = self.portfolio.can_open(symbol)
        side = "BUY" if direction == "long" else "SELL"
        if not approved: self._reject(timestamp, symbol, side, reason or "risk rejection", signal.timestamp); return
        avg_volume = float(signal.indicator_values.get("Volume_SMA_20", bar.get("Volume_SMA_20", bar.get("Volume", 0))))
        if self.config.liquidity_filter_enabled and avg_volume < self.config.min_avg_volume:
            self._reject(timestamp, symbol, side, "average volume below threshold", signal.timestamp); return
        if reference < self.config.min_price or reference > self.config.max_price:
            self._reject(timestamp, symbol, side, "price outside configured range", signal.timestamp); return
        fill = self.execution.fill_price(reference, side)
        stop = fill * (1 - self.config.stop_loss_pct) if direction == "long" else fill * (1 + self.config.stop_loss_pct)
        target = fill * (1 + self.config.target_pct) if direction == "long" else fill * (1 - self.config.target_pct)
        atr = signal.indicator_values.get("ATR_14")
        qty, sizing_error = self.portfolio.size_position(fill, stop, atr, self.portfolio.equity(self.current_prices))
        if sizing_error: self._reject(timestamp, symbol, side, sizing_error, signal.timestamp); return
        notional = fill * qty
        if self.config.liquidity_filter_enabled and notional > avg_volume * reference * self.config.liquidity_order_value_pct:
            self._reject(timestamp, symbol, side, "order exceeds configured liquidity share", signal.timestamp); return
        costs = self.cost_model.calculate(side, qty, reference, fill, self.config.spread_bps)
        cash_fees = costs.brokerage + costs.taxes_and_charges
        required_cash = notional + cash_fees
        if required_cash > self.portfolio.cash:
            self._reject(timestamp, symbol, side, "insufficient cash including costs", signal.timestamp); return
        self.portfolio.cash -= required_cash; self.portfolio.turnover += notional
        self.portfolio.positions[symbol] = Position(symbol, direction, qty, timestamp, signal.timestamp, fill, reference, costs, notional, stop, target, self.config.trailing_stop_pct, fill, fill, entry_reason=signal.signal_reason)
        self._entry_dates.add((symbol, str(timestamp)))
        self.orders.append(OrderEvent(signal.timestamp, symbol, side, qty, reference, fill, "FILLED", None, abs(fill-reference)*qty, costs.total_costs, timestamp, signal.timestamp, signal.signal_reason, direction))

    def _close(self, symbol: str, timestamp, bar, reason: str, reference: float, signal_time=None) -> None:
        position = self.portfolio.positions.pop(symbol, None)
        if position is None: return
        side = "SELL" if position.direction == "long" else "BUY"
        fill = self.execution.fill_price(reference, side)
        exit_costs = self.cost_model.calculate(side, position.quantity, reference, fill, self.config.spread_bps)
        sign = 1 if position.direction == "long" else -1
        gross = (reference - position.entry_reference_price) * position.quantity * sign
        fill_pnl = (fill - position.entry_price) * position.quantity * sign
        total_costs = position.entry_costs.total_costs + exit_costs.total_costs
        net = gross - total_costs
        exit_cash_fees = exit_costs.brokerage + exit_costs.taxes_and_charges
        self.portfolio.cash += position.reserved_capital + fill_pnl - exit_cash_fees
        self.portfolio.realized_pnl += net; self.portfolio.turnover += abs(fill * position.quantity)
        trade = Trade(symbol, position.direction, position.quantity, position.entry_time, position.entry_price, timestamp, fill, position.stop_loss, position.target,
                      position.highest_price * (1-position.trailing_stop_pct) if position.direction == "long" else position.lowest_price * (1+position.trailing_stop_pct),
                      reason, gross, total_costs, net, position.bars_held, position.mae, position.mfe, position.entry_signal_time, signal_time, position.entry_reason,
                      net / position.reserved_capital * 100 if position.reserved_capital else 0.0,
                      position.entry_costs.brokerage + exit_costs.brokerage, position.entry_costs.taxes_and_charges + exit_costs.taxes_and_charges,
                      position.entry_costs.slippage_cost + exit_costs.slippage_cost, position.entry_costs.spread_cost + exit_costs.spread_cost)
        self.trades.append(trade)
        self.orders.append(OrderEvent(signal_time or timestamp, symbol, side, position.quantity, reference, fill, "FILLED", None, abs(fill-reference)*position.quantity, exit_costs.total_costs, timestamp, signal_time, reason, position.direction))

    def _reject(self, timestamp, symbol: str, side: str, reason: str, signal_time=None) -> None:
        self.orders.append(OrderEvent(signal_time or timestamp, symbol, side, 0, None, None, "REJECTED", reason, 0, 0, None, signal_time, reason))
        warning = f"{timestamp} {symbol}: {reason}"
        if warning not in self.warnings: self.warnings.append(warning)

    def _empty_result(self, warning: str) -> BacktestResult:
        metrics = calculate_metrics([], [], self.config.initial_capital, 0, [])
        return BacktestResult(str(uuid.uuid4()), self.config, [], [], [], [], metrics, metric_breakdown(metrics), [warning])
