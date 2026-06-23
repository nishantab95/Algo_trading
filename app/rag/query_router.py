def classify_query(query: str) -> str:
    text = query.lower()
    if any(word in text for word in ("strategy", "rsi", "ema", "combo")): return "strategy"
    if any(word in text for word in ("trade", "order", "position")): return "trade"
    if any(word in text for word in ("backtest", "drawdown", "sharpe")): return "backtest"
    if any(word in text for word in ("readme", "report", "documentation")): return "docs"
    return "all"
