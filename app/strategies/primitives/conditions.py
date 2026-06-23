from __future__ import annotations

from typing import Callable
import numpy as np
import pandas as pd

from app.strategies.primitives.indicators import ensure_indicator, operand


def _series(value, index): return value if isinstance(value,pd.Series) else pd.Series(value,index=index)
def greater_than(df,a,b): return operand(df,a)>operand(df,b)
def less_than(df,a,b): return operand(df,a)<operand(df,b)
def greater_equal(df,a,b): return operand(df,a)>=operand(df,b)
def less_equal(df,a,b): return operand(df,a)<=operand(df,b)
def equal(df,a,b): return operand(df,a)==operand(df,b)
def between(df,a,low,high): return operand(df,a).between(low,high)
def outside_range(df,a,low,high): return ~operand(df,a).between(low,high)
def crossover_above(df,a,b):
    x,y=_series(operand(df,a),df.index),_series(operand(df,b),df.index); return (x>y)&(x.shift(1)<=y.shift(1))
def crossover_below(df,a,b):
    x,y=_series(operand(df,a),df.index),_series(operand(df,b),df.index); return (x<y)&(x.shift(1)>=y.shift(1))
def crossunder(df,a,b): return crossover_below(df,a,b)
def cross_above_level(df,a,level): return crossover_above(df,a,level)
def cross_below_level(df,a,level): return crossover_below(df,a,level)
def price_above_ma(df,ma): return greater_than(df,"Close",ma)
def price_below_ma(df,ma): return less_than(df,"Close",ma)
def ma_slope_positive(df,ma,period=5): x=operand(df,ma); return x>x.shift(period)
def ma_slope_negative(df,ma,period=5): x=operand(df,ma); return x<x.shift(period)
def higher_high(df,period=1): return df["High"]>df["High"].shift(period)
def higher_low(df,period=1): return df["Low"]>df["Low"].shift(period)
def lower_high(df,period=1): return df["High"]<df["High"].shift(period)
def lower_low(df,period=1): return df["Low"]<df["Low"].shift(period)
def trend_alignment(df,*columns): return pd.concat([operand(df,c) for c in columns],axis=1).apply(lambda row: all(row.iloc[i]>row.iloc[i+1] for i in range(len(row)-1)),axis=1)
def roc_above(df,period,level): return ensure_indicator(df,f"ROC_{period}")>level
def roc_below(df,period,level): return ensure_indicator(df,f"ROC_{period}")<level
def rsi_above(df,level): return operand(df,"RSI_14")>level
def rsi_below(df,level): return operand(df,"RSI_14")<level
def macd_bullish(df): return operand(df,"MACD")>operand(df,"MACD_Signal")
def macd_bearish(df): return operand(df,"MACD")<operand(df,"MACD_Signal")
def relative_strength_rank(df,*_args): raise KeyError("relative strength rank requires cross-sectional ranking data")
def atr_above_percentile(df,window=100,percentile=.8): x=operand(df,"ATR_14"); return x>x.rolling(window).quantile(percentile)
def atr_below_percentile(df,window=100,percentile=.2): x=operand(df,"ATR_14"); return x<x.rolling(window).quantile(percentile)
def bollinger_squeeze(df,window=20): x=operand(df,"Bollinger_Width"); return x<=x.rolling(window).min()
def bollinger_expansion(df): x=operand(df,"Bollinger_Width"); return x>x.shift(1)
def volatility_contraction(df,window=7): x=ensure_indicator(df,"RANGE_PCT"); return x<=x.rolling(window).min()
def volatility_breakout(df): return (df["Close"]>operand(df,"Bollinger_Upper"))&(operand(df,"ATR_14")>operand(df,"ATR_14").shift(1))
def volume_above_sma(df,multiple=1): return df["Volume"]>operand(df,"Volume_SMA_20")*multiple
def relative_volume_above(df,multiple=2): return volume_above_sma(df,multiple)
def volume_zscore_above(df,level=1.5): return operand(df,"Volume_Z_Score")>level
def obv_breakout(df,*_args): raise KeyError("OBV is unavailable")
def mfi_signal(df,*_args): raise KeyError("MFI is unavailable")
def inside_bar(df): return (df["High"]<df["High"].shift(1))&(df["Low"]>df["Low"].shift(1))
def outside_bar(df): return (df["High"]>df["High"].shift(1))&(df["Low"]<df["Low"].shift(1))
def bullish_engulfing(df): return (df["Close"]>df["Open"])&(df["Close"].shift(1)<df["Open"].shift(1))&(df["Close"]>=df["Open"].shift(1))&(df["Open"]<=df["Close"].shift(1))
def bearish_engulfing(df): return (df["Close"]<df["Open"])&(df["Close"].shift(1)>df["Open"].shift(1))&(df["Open"]>=df["Close"].shift(1))&(df["Close"]<=df["Open"].shift(1))
def hammer(df):
    body=(df["Close"]-df["Open"]).abs(); lower=df[["Open","Close"]].min(axis=1)-df["Low"]; upper=df["High"]-df[["Open","Close"]].max(axis=1); return (lower>=2*body)&(upper<=body)
def shooting_star(df):
    body=(df["Close"]-df["Open"]).abs(); lower=df[["Open","Close"]].min(axis=1)-df["Low"]; upper=df["High"]-df[["Open","Close"]].max(axis=1); return (upper>=2*body)&(lower<=body)
def doji(df,threshold=.1): return (df["Close"]-df["Open"]).abs()<=((df["High"]-df["Low"])*threshold)
def narrow_range(df,window=7): x=df["High"]-df["Low"]; return x<=x.rolling(window).min()
def wide_range(df,window=20,multiple=1.5): x=df["High"]-df["Low"]; return x>x.rolling(window).mean()*multiple
def previous_day_high_break(df): return df["Close"]>df["High"].shift(1)
def previous_day_low_break(df): return df["Close"]<df["Low"].shift(1)
def rolling_high_break(df,window=20): return df["Close"]>df["High"].rolling(window).max().shift(1)
def rolling_low_break(df,window=20): return df["Close"]<df["Low"].rolling(window).min().shift(1)
def weekly_high_break(df): return rolling_high_break(df,5)
def weekly_low_break(df): return rolling_low_break(df,5)
def monthly_high_break(df): return rolling_high_break(df,21)
def monthly_low_break(df): return rolling_low_break(df,21)
def support_bounce(df,window=50,tolerance=.01):
    support=df["Low"].rolling(window).min(); close_location=(df["Close"]-df["Low"])/(df["High"]-df["Low"]).replace(0,np.nan); return (df["Low"]<=support*(1+tolerance))&(close_location>.65)
def resistance_rejection(df,window=50,tolerance=.01):
    resistance=df["High"].rolling(window).max(); close_location=(df["Close"]-df["Low"])/(df["High"]-df["Low"]).replace(0,np.nan); return (df["High"]>=resistance*(1-tolerance))&(close_location<.35)
def pullback_to(df,column,tolerance=.01,direction="long"):
    level=operand(df,column); near=(df["Low"]<=level*(1+tolerance))&(df["Close"]>=level) if direction=="long" else (df["High"]>=level*(1-tolerance))&(df["Close"]<=level); return near


PRIMITIVES: dict[str,Callable] = {name:value for name,value in list(globals().items()) if callable(value) and name in {
"greater_than","less_than","greater_equal","less_equal","equal","between","outside_range","crossover_above","crossover_below","crossunder","cross_above_level","cross_below_level","price_above_ma","price_below_ma","ma_slope_positive","ma_slope_negative","higher_high","higher_low","lower_high","lower_low","trend_alignment","roc_above","roc_below","rsi_above","rsi_below","macd_bullish","macd_bearish","relative_strength_rank","atr_above_percentile","atr_below_percentile","bollinger_squeeze","bollinger_expansion","volatility_contraction","volatility_breakout","volume_above_sma","relative_volume_above","volume_zscore_above","obv_breakout","mfi_signal","inside_bar","outside_bar","bullish_engulfing","bearish_engulfing","hammer","shooting_star","doji","narrow_range","wide_range","previous_day_high_break","previous_day_low_break","weekly_high_break","weekly_low_break","monthly_high_break","monthly_low_break","rolling_high_break","rolling_low_break","support_bounce","resistance_rejection","pullback_to"}}


def evaluate_primitive(df:pd.DataFrame,name:str,args=None):
    if name not in PRIMITIVES: raise ValueError(f"Unknown primitive: {name}")
    args=[] if args is None else args; args=args if isinstance(args,list) else [args]
    return PRIMITIVES[name](df,*args).fillna(False).astype(bool)


def evaluate_logic(df:pd.DataFrame,node) -> pd.Series:
    if not node: return pd.Series(False,index=df.index)
    if isinstance(node,list): return pd.concat([evaluate_logic(df,x) for x in node],axis=1).all(axis=1)
    if "primitive" in node: return evaluate_primitive(df,node["primitive"],node.get("args",[]))
    for mode in ("all","any"):
        if mode in node:
            frame=pd.concat([evaluate_logic(df,x) for x in node[mode]],axis=1); return frame.all(axis=1) if mode=="all" else frame.any(axis=1)
    if "not" in node: return ~evaluate_logic(df,node["not"])
    if "min_confirmations" in node:
        spec=node["min_confirmations"]; frame=pd.concat([evaluate_logic(df,x) for x in spec["rules"]],axis=1); return frame.sum(axis=1)>=int(spec["minimum"])
    if "weighted_vote" in node or "score_threshold" in node:
        spec=node.get("weighted_vote",node.get("score_threshold")); score=sum(evaluate_logic(df,item["rule"]).astype(float)*float(item.get("weight",1)) for item in spec["rules"]); return score>=float(spec["threshold"])
    if len(node)==1:
        name,args=next(iter(node.items())); return evaluate_primitive(df,name,args)
    raise ValueError(f"Unsupported logic node: {node}")
