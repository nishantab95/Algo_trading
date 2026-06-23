from app.strategies.schemas import StrategyDefinition

def _definition(name,category,direction,description,entry): return StrategyDefinition(name,name,category,direction,"1d",description,entry)
BUILTIN_STRATEGIES=[
_definition("Volatility_Breakout","breakout","long","Volatility and participation breakout.","Close above upper Bollinger band with volume confirmation."),
_definition("Golden_Cross","trend","long","Long-term moving-average regime change.","EMA50 crosses above EMA200."),
_definition("EMA_Crossover","trend","long","Short-cycle trend crossover.","EMA9 crosses above EMA21."),
_definition("RSI_Oversold","mean_reversion","long","Recovery from oversold momentum.","RSI14 crosses upward through 30."),
_definition("RSI_Overbought","mean_reversion","short","Retreat from overbought momentum.","RSI14 crosses downward through 70."),
_definition("MACD_Histogram_Momentum","momentum","long","Positive MACD acceleration.","MACD histogram crosses above zero."),
_definition("Bollinger_Mean_Reversion","mean_reversion","long","Lower-band re-entry.","Close re-enters lower band."),
_definition("Volume_Spike","volume","long","Unusual participation signal.","Volume exceeds its average."),
_definition("Trend_Filter","trend","both","Persistent price and EMA trend regime.","Price and EMA structure."),
_definition("Turtle_Breakout","breakout","long","Classic channel continuation.","Close exceeds prior 20-day high."),
_definition("BB_Squeeze_Breakout","breakout","long","Compression-release breakout.","Band squeeze then breakout."),
_definition("SuperTrend_Mimic","trend","long","ATR-aware impulse approximation.","Close exceeds ATR band."),
_definition("Momentum_20","momentum","both","Twenty-session directional momentum.","20-day return threshold."),
_definition("EMA21_Mean_Reversion","mean_reversion","both","Extreme displacement around EMA21.","Standardized deviation."),
_definition("Support_Bounce","mean_reversion","long","Strong close near support.","Support bounce."),]
