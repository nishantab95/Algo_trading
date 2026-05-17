"""
Backtesting analytics suite for all 15 rule-based strategies.

The report engine produces a multi-dimensional Risk & Performance Analytics
Suite with combined, long-only, and short-only metrics for each strategy.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

import config_settings as cfg

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE_ANNUAL = 0.06


def _safe_float(value: float | int | np.floating, default: float = 0.0) -> float:
    """Converts NaN/inf values to a stable numeric default."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(numeric):
        return default
    return numeric


def _max_drawdown_pct(return_series: pd.Series) -> float:
    """Returns the largest peak-to-trough drawdown for a return stream."""
    if return_series.empty:
        return 0.0

    equity = (1.0 + return_series.fillna(0.0).astype(float)).cumprod()
    if equity.empty:
        return 0.0

    running_peak = equity.cummax().replace(0.0, np.nan)
    drawdown = (equity / running_peak - 1.0) * 100.0
    return round(_safe_float(drawdown.min()), 2)


def _sharpe_ratio(return_series: pd.Series) -> float:
    """Annualized Sharpe ratio using a 6% Indian-market risk-free baseline."""
    if return_series.empty:
        return 0.0

    returns = return_series.fillna(0.0).astype(float)
    daily_rf = (1.0 + RISK_FREE_RATE_ANNUAL) ** (1.0 / TRADING_DAYS_PER_YEAR) - 1.0
    excess = returns - daily_rf
    volatility = excess.std(ddof=0)
    if volatility <= 0 or not np.isfinite(volatility):
        return 0.0

    sharpe = np.sqrt(TRADING_DAYS_PER_YEAR) * excess.mean() / volatility
    return round(_safe_float(sharpe), 3)


def _performance_metrics(return_series: pd.Series, active_mask: pd.Series) -> dict:
    """
    Computes safe trade magnitude, tail-risk, and capital repair metrics.

    return_series is a full timeline stream, while active_mask marks the dates
    that count as trades for distribution-level statistics.
    """
    returns = return_series.fillna(0.0).astype(float)
    mask = active_mask.fillna(False).astype(bool)
    active_returns = returns[mask]
    total_trades = int(len(active_returns))

    if total_trades > 0:
        wins = active_returns[active_returns > 0]
        losses = active_returns[active_returns < 0]
        win_count = int(len(wins))
        loss_count = int(len(losses))

        gross_profit = _safe_float(wins.sum())
        gross_loss = abs(_safe_float(losses.sum()))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

        avg_win = _safe_float(wins.mean() * 100.0) if win_count > 0 else 0.0
        avg_loss = _safe_float(losses.mean() * 100.0) if loss_count > 0 else 0.0
        win_loss_ratio = avg_win / abs(avg_loss) if abs(avg_loss) > 0 else 0.0
        win_rate = win_count / total_trades * 100.0
    else:
        profit_factor = 0.0
        avg_win = 0.0
        avg_loss = 0.0
        win_loss_ratio = 0.0
        win_rate = 0.0

    total_return = ((1.0 + returns).cumprod().iloc[-1] - 1.0) * 100.0 if not returns.empty else 0.0
    max_drawdown = _max_drawdown_pct(returns)
    sharpe = _sharpe_ratio(returns)
    recovery_factor = total_return / abs(max_drawdown) if abs(max_drawdown) > 0 else 0.0

    return {
        "Total_Return_%": round(_safe_float(total_return), 2),
        "Trades": total_trades,
        "Win_Rate_%": round(_safe_float(win_rate), 2),
        "Profit_Factor": round(_safe_float(profit_factor), 3),
        "Avg_Win_Return_pct": round(_safe_float(avg_win), 2),
        "Avg_Loss_Return_pct": round(_safe_float(avg_loss), 2),
        "Win_Loss_Ratio": round(_safe_float(win_loss_ratio), 3),
        "Max_Drawdown_pct": round(_safe_float(max_drawdown), 2),
        "Sharpe_Ratio": round(_safe_float(sharpe), 3),
        "Recovery_Factor": round(_safe_float(recovery_factor), 3),
    }


def _prefix_metrics(prefix: str, metrics: dict) -> dict:
    return {f"{prefix}_{key}": value for key, value in metrics.items()}


def _evaluate_ticker_strategy(group: pd.DataFrame, strategy: str) -> dict | None:
    """Computes combined, long-only, and short-only metrics for one ticker/strategy."""
    try:
        if "Close" not in group.columns or strategy not in group.columns:
            return None

        group = group.sort_values("Date").copy()
        group["Market_Return"] = group["Close"].pct_change().fillna(0.0)

        signal = group[strategy].fillna(0).astype(float)
        long_mask = signal > 0
        short_mask = signal < 0
        active_mask = signal != 0

        if int(active_mask.sum()) == 0:
            return None

        combined_returns = signal * group["Market_Return"]
        long_returns = group["Market_Return"].where(long_mask, 0.0)
        short_returns = (-group["Market_Return"]).where(short_mask, 0.0)

        combined = _performance_metrics(combined_returns, active_mask)
        long_only = _performance_metrics(long_returns, long_mask)
        short_only = _performance_metrics(short_returns, short_mask)

        row = {
            "Ticker": group["Ticker"].iloc[0],
            "Strategy": strategy,
            **combined,
            **_prefix_metrics("Long", long_only),
            **_prefix_metrics("Short", short_only),
        }
        return row

    except Exception as exc:
        print(f"[REPORT] Evaluation error ({strategy}): {exc}")
        return None


def _weighted_average(df: pd.DataFrame, value_col: str, weight_col: str) -> float:
    if value_col not in df.columns or weight_col not in df.columns:
        return 0.0

    weights = df[weight_col].fillna(0.0).astype(float)
    total_weight = weights.sum()
    if total_weight <= 0:
        return 0.0

    values = df[value_col].fillna(0.0).astype(float)
    return _safe_float((values * weights).sum() / total_weight)


def _aggregate_directional_summary(df_assets: pd.DataFrame, prefix: str, total_assets: int) -> pd.DataFrame:
    rows: list[dict] = []
    trade_col = f"{prefix}_Trades"
    return_col = f"{prefix}_Total_Return_%"

    for strategy, group in df_assets.groupby("Strategy"):
        total_trades = int(group[trade_col].fillna(0).sum()) if trade_col in group else 0
        profitable_assets = int((group[return_col].fillna(0.0) > 0).sum()) if return_col in group else 0

        row = {
            "Strategy": strategy,
            f"{prefix}_Avg_Return_Per_Asset_pct": _safe_float(group[return_col].mean()) if return_col in group else 0.0,
            f"{prefix}_Median_Return_pct": _safe_float(group[return_col].median()) if return_col in group else 0.0,
            f"{prefix}_Total_Trades_Executed": total_trades,
            f"{prefix}_Average_Win_Rate_pct": _weighted_average(group, f"{prefix}_Win_Rate_%", trade_col),
            f"{prefix}_Global_Profit_Factor": _weighted_average(group, f"{prefix}_Profit_Factor", trade_col),
            f"{prefix}_Avg_Win_Return_pct": _weighted_average(group, f"{prefix}_Avg_Win_Return_pct", trade_col),
            f"{prefix}_Avg_Loss_Return_pct": _weighted_average(group, f"{prefix}_Avg_Loss_Return_pct", trade_col),
            f"{prefix}_Win_Loss_Ratio": _weighted_average(group, f"{prefix}_Win_Loss_Ratio", trade_col),
            f"{prefix}_Max_Drawdown_pct": _safe_float(group[f"{prefix}_Max_Drawdown_pct"].min()) if f"{prefix}_Max_Drawdown_pct" in group else 0.0,
            f"{prefix}_Sharpe_Ratio": _weighted_average(group, f"{prefix}_Sharpe_Ratio", trade_col),
            f"{prefix}_Recovery_Factor": _weighted_average(group, f"{prefix}_Recovery_Factor", trade_col),
            f"{prefix}_Profitable_Assets_Count": profitable_assets,
            f"{prefix}_Market_Coverage_Hit_Rate_pct": profitable_assets / max(total_assets, 1) * 100.0,
        }
        rows.append(row)

    return pd.DataFrame(rows)


def _build_summary(df_assets: pd.DataFrame, total_assets: int) -> pd.DataFrame:
    summary = df_assets.groupby("Strategy").agg(
        Avg_Return_Per_Asset_pct=("Total_Return_%", "mean"),
        Median_Return_pct=("Total_Return_%", "median"),
        Total_Trades_Executed=("Trades", "sum"),
        Profitable_Assets_Count=("Total_Return_%", lambda x: int((x > 0).sum())),
    ).reset_index()

    weighted_cols = {
        "Average_Win_Rate_pct": "Win_Rate_%",
        "Global_Profit_Factor": "Profit_Factor",
        "Avg_Win_Return_pct": "Avg_Win_Return_pct",
        "Avg_Loss_Return_pct": "Avg_Loss_Return_pct",
        "Win_Loss_Ratio": "Win_Loss_Ratio",
        "Sharpe_Ratio": "Sharpe_Ratio",
        "Recovery_Factor": "Recovery_Factor",
    }
    for output_col, source_col in weighted_cols.items():
        values = []
        for strategy, group in df_assets.groupby("Strategy"):
            values.append({"Strategy": strategy, output_col: _weighted_average(group, source_col, "Trades")})
        summary = summary.merge(pd.DataFrame(values), on="Strategy", how="left")

    max_dd = df_assets.groupby("Strategy")["Max_Drawdown_pct"].min().reset_index()
    summary = summary.merge(max_dd, on="Strategy", how="left")

    summary["Market_Coverage_Hit_Rate_pct"] = (
        summary["Profitable_Assets_Count"] / max(total_assets, 1) * 100.0
    )

    long_summary = _aggregate_directional_summary(df_assets, "Long", total_assets)
    short_summary = _aggregate_directional_summary(df_assets, "Short", total_assets)
    summary = summary.merge(long_summary, on="Strategy", how="left")
    summary = summary.merge(short_summary, on="Strategy", how="left")

    numeric_cols = [col for col in summary.columns if col != "Strategy"]
    summary[numeric_cols] = summary[numeric_cols].fillna(0.0)

    precision = {
        "Total_Trades_Executed": 0,
        "Profitable_Assets_Count": 0,
        "Long_Total_Trades_Executed": 0,
        "Long_Profitable_Assets_Count": 0,
        "Short_Total_Trades_Executed": 0,
        "Short_Profitable_Assets_Count": 0,
    }
    for col in numeric_cols:
        if col in precision:
            summary[col] = summary[col].round(0).astype(int)
        elif "Ratio" in col or "Factor" in col or "Sharpe" in col:
            summary[col] = summary[col].round(3)
        else:
            summary[col] = summary[col].round(2)

    summary = summary.sort_values(
        by=["Sharpe_Ratio", "Global_Profit_Factor", "Market_Coverage_Hit_Rate_pct"],
        ascending=False,
    ).reset_index(drop=True)

    return summary


def generate_performance_report(
    consolidated_path: str | None = None,
    output_path: str | None = None,
) -> pd.DataFrame:
    """
    Backtests all strategies and returns the global risk/performance summary.
    Saves CSV to reports/ directory.
    """
    cfg.ensure_directories()
    consolidated_path = consolidated_path or cfg.CONSOLIDATED_FILE
    output_path = output_path or cfg.STRATEGY_REPORT_FILE

    if not os.path.exists(consolidated_path):
        print(f"[REPORT] Consolidated file missing: {consolidated_path}")
        print("[REPORT] Run preprocessing.consolidate_universe() first.")
        return pd.DataFrame()

    print("=" * 88)
    print("[REPORT] Loading consolidated universe for advanced risk analytics...")
    print("=" * 88)

    try:
        df = pd.read_csv(consolidated_path, parse_dates=["Date"])
    except Exception as exc:
        print(f"[REPORT] Failed to read consolidated file: {exc}")
        return pd.DataFrame()

    asset_rows: list[dict] = []
    tickers = df["Ticker"].dropna().unique()
    total_assets = len(tickers)

    for strategy in cfg.all_strategy_columns():
        print(f"[REPORT] Computing risk distribution metrics -> {strategy}")
        for ticker in tickers:
            group = df[df["Ticker"] == ticker]
            row = _evaluate_ticker_strategy(group, strategy)
            if row:
                asset_rows.append(row)

    if not asset_rows:
        print("[REPORT] No asset-level results generated.")
        return pd.DataFrame()

    df_assets = pd.DataFrame(asset_rows)
    summary = _build_summary(df_assets, total_assets)

    asset_detail_path = os.path.join(cfg.REPORTS_DIR, "asset_performance_leaderboard.csv")
    asset_display_cols = [
        "Ticker",
        "Strategy",
        "Total_Return_%",
        "Trades",
        "Win_Rate_%",
        "Profit_Factor",
        "Max_Drawdown_pct",
        "Long_Total_Return_%",
        "Long_Trades",
        "Short_Total_Return_%",
        "Short_Trades",
    ]
    existing_asset_cols = [column for column in asset_display_cols if column in df_assets.columns]
    df_assets.sort_values("Total_Return_%", ascending=False)[existing_asset_cols].to_csv(asset_detail_path, index=False)
    summary.to_csv(output_path, index=False)

    display_cols = [
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
        "Recovery_Factor",
        "Long_Total_Trades_Executed",
        "Short_Total_Trades_Executed",
    ]

    print("\n" + "=" * 88)
    print("  ADVANCED STRATEGY RISK & PERFORMANCE SUMMARY")
    print("=" * 88)
    print(summary[display_cols].to_string(index=False))
    print("=" * 88)
    print(f"[REPORT] Risk-free baseline: {RISK_FREE_RATE_ANNUAL:.2%} annualized")
    print(f"[REPORT] Saved advanced summary -> {output_path}")
    print(f"[REPORT] Saved asset-level directional details -> {asset_detail_path}")

    return summary


if __name__ == "__main__":
    generate_performance_report()
