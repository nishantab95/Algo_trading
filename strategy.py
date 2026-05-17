"""
Algorithmic alpha selector matrix for live strategy routing.
"""

from __future__ import annotations

import os

import pandas as pd

import config_settings as cfg


def load_performance_report(report_path: str | None = None) -> pd.DataFrame:
    report_path = report_path or cfg.STRATEGY_REPORT_FILE
    if not os.path.exists(report_path):
        raise FileNotFoundError(
            f"Strategy report not found at {report_path}. Run report.generate_performance_report() first."
        )
    return pd.read_csv(report_path)


def _normalize(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0).astype(float)
    min_value = values.min()
    max_value = values.max()
    if max_value == min_value:
        return pd.Series(0.5, index=values.index)
    normalized = (values - min_value) / (max_value - min_value)
    return normalized if higher_is_better else 1.0 - normalized


def score_strategies(summary: pd.DataFrame) -> pd.DataFrame:
    """
    Institutional-style weighted selector:
      profit quality 30%, risk-adjusted return 25%, coverage 20%,
      drawdown control 15%, average return 10%.
    """
    if summary.empty:
        return summary.copy()

    ranked = summary.copy()
    enabled = set(cfg.enabled_strategy_columns())
    if enabled and "Strategy" in ranked.columns:
        ranked = ranked[ranked["Strategy"].isin(enabled)].copy()
        if ranked.empty:
            ranked = summary.copy()

    drawdown_abs = pd.to_numeric(ranked.get("Max_Drawdown_pct", 0), errors="coerce").fillna(0.0).abs()
    ranked["Selection_Score"] = (
        _normalize(ranked.get("Global_Profit_Factor", 0)) * 30.0
        + _normalize(ranked.get("Sharpe_Ratio", 0)) * 25.0
        + _normalize(ranked.get("Market_Coverage_Hit_Rate_pct", 0)) * 20.0
        + _normalize(drawdown_abs, higher_is_better=False) * 15.0
        + _normalize(ranked.get("Avg_Return_Per_Asset_pct", 0)) * 10.0
    ).round(3)
    return ranked.sort_values("Selection_Score", ascending=False).reset_index(drop=True)


def select_winning_strategy(report_path: str | None = None) -> str:
    try:
        summary = load_performance_report(report_path)
        if summary.empty:
            raise ValueError("Performance summary is empty.")

        ranked = score_strategies(summary)
        winner = str(ranked.iloc[0]["Strategy"])
        score = float(ranked.iloc[0]["Selection_Score"])
        display_cols = [
            "Strategy",
            "Selection_Score",
            "Global_Profit_Factor",
            "Sharpe_Ratio",
            "Max_Drawdown_pct",
            "Market_Coverage_Hit_Rate_pct",
        ]
        print("=" * 80)
        print("  ALPHA SELECTOR MATRIX")
        print("=" * 80)
        print(ranked[[column for column in display_cols if column in ranked.columns]].head(10).to_string(index=False))
        print("=" * 80)
        print(f"[STRATEGY] Selected winner: {winner} (score={score})")
        print("=" * 80)
        return winner

    except Exception as exc:
        print(f"[STRATEGY] Selection failed: {exc}")
        fallback = cfg.enabled_strategy_columns()[0] if cfg.enabled_strategy_columns() else "Volatility_Breakout"
        print(f"[STRATEGY] Using fallback strategy: {fallback}")
        return fallback


def get_ranked_strategies(report_path: str | None = None) -> pd.DataFrame:
    return score_strategies(load_performance_report(report_path))


if __name__ == "__main__":
    print(select_winning_strategy())
