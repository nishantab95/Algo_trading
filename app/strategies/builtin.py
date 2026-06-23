from app.strategies.schemas import StrategyDefinition


def _definition(name: str, category: str, direction: str, description: str, entry: str) -> StrategyDefinition:
    return StrategyDefinition(name, name, category, direction, "1d", description, entry)


BUILTIN_STRATEGIES = [
    _definition("Volatility_Breakout", "breakout", "long", "Volatility and participation breakout.", "Close above upper Bollinger band with volume z-score > 1.5."),
    _definition("Golden_Cross", "trend", "long", "Long-term moving-average regime change.", "EMA50 crosses above EMA200."),
    _definition("EMA_Crossover", "trend", "long", "Short-cycle trend crossover.", "EMA9 crosses above EMA21."),
    _definition("RSI_Oversold", "mean_reversion", "long", "Recovery from oversold momentum.", "RSI14 crosses upward through 30."),
    _definition("RSI_Overbought", "mean_reversion", "short", "Retreat from overbought momentum.", "RSI14 crosses downward through 70."),
    _definition("MACD_Histogram_Momentum", "momentum", "long", "Positive MACD acceleration.", "MACD histogram crosses above zero."),
    _definition("Bollinger_Mean_Reversion", "mean_reversion", "long", "Lower-band re-entry.", "Prior close below lower band and current close back above."),
    _definition("Volume_Spike", "volume", "long", "Unusual participation signal.", "Volume > 2.5 times its 20-day average."),
    _definition("Trend_Filter", "trend", "both", "Persistent price and EMA trend regime.", "Long above EMA200 with EMA9 > EMA21; short otherwise."),
    _definition("Turtle_Breakout", "breakout", "long", "Classic channel continuation.", "Close exceeds prior 20-day high."),
    _definition("BB_Squeeze_Breakout", "breakout", "long", "Compression-release breakout.", "Bollinger width at 20-day minimum then upper-band breakout."),
    _definition("SuperTrend_Mimic", "trend", "long", "ATR-aware impulse approximation.", "Close above prior midpoint plus three ATR."),
    _definition("Momentum_20", "momentum", "both", "Twenty-session directional momentum.", "20-day return above 5% or below -5%."),
    _definition("EMA21_Mean_Reversion", "mean_reversion", "both", "Extreme displacement around EMA21.", "Standardized deviation exceeds +/-2.5."),
    _definition("Support_Bounce", "mean_reversion", "long", "Strong close near 50-day support.", "Low within 1% of 50-day low and close-location > 0.65."),
]
