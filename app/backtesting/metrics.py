from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from app.backtesting.models import Trade


def _safe(value: Any) -> float:
    try: number = float(value)
    except (TypeError, ValueError): return 0.0
    return number if math.isfinite(number) else 0.0


def _streak(values: list[bool], target: bool) -> int:
    best = current = 0
    for value in values:
        current = current + 1 if value is target else 0; best = max(best, current)
    return best


def calculate_metrics(trades: list[Trade], equity_curve: list[dict], initial_capital: float, turnover: float, exposure_observations: list[float], benchmark_return_pct: float | None = None) -> dict[str, Any]:
    pnls = np.array([trade.net_pnl for trade in trades], dtype=float)
    wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
    gross_profit = float(wins.sum()) if wins.size else 0.0; gross_loss = abs(float(losses.sum())) if losses.size else 0.0
    final_equity = float(equity_curve[-1]["total_equity"]) if equity_curve else initial_capital
    net_profit = final_equity - initial_capital; net_return = net_profit / initial_capital * 100 if initial_capital else 0.0
    curve = pd.DataFrame(equity_curve)
    daily_returns = pd.Series(dtype=float); max_dd = 0.0; dd_duration = 0; cagr = sharpe = sortino = 0.0
    monthly: dict[str, float] = {}; yearly: dict[str, float] = {}
    if not curve.empty:
        curve["timestamp"] = pd.to_datetime(curve["timestamp"]); curve = curve.sort_values("timestamp").set_index("timestamp")
        daily_returns = curve["total_equity"].pct_change().fillna(0.0)
        max_dd = abs(float(curve["drawdown_pct"].min()))
        underwater = curve["drawdown_pct"] < 0; current = 0
        for flag in underwater: current = current + 1 if flag else 0; dd_duration = max(dd_duration, current)
        days = max((curve.index.max() - curve.index.min()).days, 1); years = days / 365.25
        cagr = ((final_equity / initial_capital) ** (1 / years) - 1) * 100 if final_equity > 0 and years > 0 else 0.0
        std = daily_returns.std(ddof=0); downside = daily_returns[daily_returns < 0].std(ddof=0)
        sharpe = np.sqrt(252) * daily_returns.mean() / std if std and math.isfinite(std) else 0.0
        sortino = np.sqrt(252) * daily_returns.mean() / downside if downside and math.isfinite(downside) else 0.0
        monthly = {str(k): round(float(v) * 100, 3) for k, v in curve["total_equity"].resample("ME").last().pct_change().dropna().items()}
        yearly = {str(k.year): round(float(v) * 100, 3) for k, v in curve["total_equity"].resample("YE").last().pct_change().dropna().items()}
    costs = sum(trade.costs for trade in trades)
    avg_win = float(wins.mean()) if wins.size else 0.0; avg_loss = float(losses.mean()) if losses.size else 0.0
    statuses = [trade.net_pnl > 0 for trade in trades]
    metrics = {
        "total_trades": len(trades), "winning_trades": int(wins.size), "losing_trades": int(losses.size),
        "win_rate": wins.size / len(trades) * 100 if trades else 0.0, "average_win": avg_win, "average_loss": avg_loss,
        "payoff_ratio": avg_win / abs(avg_loss) if avg_loss else 0.0, "expectancy": float(pnls.mean()) if pnls.size else 0.0,
        "gross_profit": gross_profit, "gross_loss": gross_loss, "profit_factor": gross_profit / gross_loss if gross_loss else (None if gross_profit else 0.0),
        "net_profit": net_profit, "net_return_pct": net_return, "cagr": cagr, "max_drawdown_pct": max_dd,
        "drawdown_duration_bars": dd_duration, "sharpe": _safe(sharpe), "sortino": _safe(sortino),
        "calmar": cagr / max_dd if max_dd else 0.0, "exposure_pct": np.mean(exposure_observations) * 100 if exposure_observations else 0.0,
        "turnover": turnover, "average_holding_period": np.mean([t.holding_period_bars for t in trades]) if trades else 0.0,
        "max_winning_streak": _streak(statuses, True), "max_losing_streak": _streak(statuses, False),
        "largest_win": float(pnls.max()) if pnls.size else 0.0, "largest_loss": float(pnls.min()) if pnls.size else 0.0,
        "average_costs_per_trade": costs / len(trades) if trades else 0.0,
        "cost_drag_pct": costs / initial_capital * 100 if initial_capital else 0.0,
        "monthly_returns": monthly, "yearly_returns": yearly,
        "benchmark_return_pct": benchmark_return_pct,
        "benchmark_relative_return_pct": net_return - benchmark_return_pct if benchmark_return_pct is not None else None,
    }
    return {key: round(_safe(value), 4) if isinstance(value, (int, float, np.number)) and not isinstance(value, bool) else value for key, value in metrics.items()}


def metric_breakdown(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    explanations = {
        "net_return_pct": "Net portfolio return after modeled costs; not a forecast.",
        "max_drawdown_pct": "Largest peak-to-trough equity decline.",
        "sharpe": "Annualized consistency of daily portfolio returns.",
        "sortino": "Return consistency measured against downside volatility.",
        "profit_factor": "Gross completed-trade profit divided by gross loss.",
        "expectancy": "Average net currency P&L per completed trade.",
        "total_trades": "Completed round trips; small samples are unreliable.",
        "cost_drag_pct": "Modeled total costs as a percentage of starting capital.",
    }
    rows = []
    for name, explanation in explanations.items():
        value = metrics.get(name)
        if name == "total_trades": status = "green" if value >= 30 else "amber" if value >= 10 else "red"
        elif name == "max_drawdown_pct": status = "green" if value <= 15 else "amber" if value <= 30 else "red"
        elif name == "profit_factor" and value is None: status = "amber"
        elif name in {"sharpe", "sortino", "profit_factor", "expectancy", "net_return_pct"}: status = "green" if value > 1 else "amber" if value > 0 else "red"
        else: status = "amber" if value and value > 2 else "green"
        rows.append({"metric_name": name, "metric_value": value, "metric_status": status, "explanation": explanation})
    return rows
