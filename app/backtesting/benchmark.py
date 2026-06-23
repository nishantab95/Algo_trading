from __future__ import annotations

import pandas as pd


def apply_benchmark(equity_curve: list[dict], data: pd.DataFrame, benchmark_symbol: str | None, initial_capital: float) -> tuple[dict, list[str]]:
    if not benchmark_symbol: return {}, ["No benchmark configured."]
    benchmark = data[data["Ticker"] == benchmark_symbol].sort_values("Date")
    if benchmark.empty: return {}, [f"Benchmark {benchmark_symbol} is unavailable; comparison omitted."]
    if equity_curve:
        start, end = pd.Timestamp(equity_curve[0]["timestamp"]), pd.Timestamp(equity_curve[-1]["timestamp"])
        dates = pd.to_datetime(benchmark["Date"])
        benchmark = benchmark[(dates >= start) & (dates <= end)]
    prices = benchmark.set_index(pd.to_datetime(benchmark["Date"]))["Close"].astype(float)
    if prices.empty: return {}, [f"Benchmark {benchmark_symbol} has no valid prices."]
    base = prices.iloc[0]; values = initial_capital * prices / base; peak = values.cummax(); drawdowns = (values / peak - 1) * 100
    lookup = {str(index): (float(value), float(drawdowns.loc[index])) for index, value in values.items()}
    for row in equity_curve:
        ts = str(pd.Timestamp(row["timestamp"])); match = lookup.get(ts)
        if match: row["benchmark_value"], row["benchmark_drawdown_pct"] = round(match[0], 4), round(match[1], 4)
    days = max((prices.index.max() - prices.index.min()).days, 1)
    total_return = (values.iloc[-1] / initial_capital - 1) * 100
    cagr = ((values.iloc[-1] / initial_capital) ** (365.25 / days) - 1) * 100
    return {"symbol": benchmark_symbol, "return_pct": round(float(total_return), 4), "cagr": round(float(cagr), 4), "max_drawdown_pct": round(abs(float(drawdowns.min())), 4)}, []
