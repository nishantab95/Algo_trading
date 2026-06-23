from __future__ import annotations

import re
from app.strategies.builtin import CATALOG_GROUPS
from app.strategies.schemas import CatalogStrategy

BASE_COLUMNS=["Open","High","Low","Close","Volume"]


def _slug(category:str,index:int,name:str)->str:
    token=re.sub(r"[^A-Z0-9]+","_",name.upper()).strip("_")[:48]
    return f"{category.upper()[:8]}_{index:03d}_{token}"


def _unsupported(category,index,name,reason,status="needs_data",timeframe="daily",asset_class="equity"):
    return CatalogStrategy(_slug(category,index,name),name,category,"catalogued",("short" if "short" in name.lower() or "breakdown" in name.lower() else "long"),timeframe,asset_class,status,
        f"Catalogued research definition: {name}.","This candidate is visible for learning but cannot run until its declared data dependency is available.",
        {"required_columns":BASE_COLUMNS+[reason.split()[0]],"optional_columns":[]},{},{"primitive":"greater_than","args":["Close",0]}, {},unsupported_reason=reason,tags=(category,status),enabled=False)


def _active(category,index,name,entry,direction="long",required=None,filters=None,parameters=None):
    return CatalogStrategy(_slug(category,index,name),name,category,"daily_technical",direction,"daily","equity","active",
        f"Config-driven {category.replace('_',' ')} research rule: {name}.","Treat this as a testable hypothesis, not evidence of profitability.",
        {"required_columns":BASE_COLUMNS+(required or []),"optional_columns":[]},parameters or {},entry,filters or {},
        {"any":[{"stop_loss_pct":5},{"target_pct":15},{"trailing_stop_pct":7}]},{"max_holding_bars":60,"max_position_value_pct":10},
        "{name}: {passed_rules}; indicators {indicator_values}.",(category,"daily","config_driven"),None,False)


def _build(category,index,name):
    lower=name.lower()
    intraday_terms=("vwap","opening range","first-hour","first range","first 30-minute","first 15 minutes")
    missing_terms=("p/e","p/b","ev/ebitda","dividend","roe","debt","sales growth","profit growth","garp","cash flow","beta","sector","relative strength","nifty","index","basket","sip","fibonacci","trendline","supertrend","adx","parabolic","ichimoku","keltner","heikin","obv","mfi","accumulation distribution","cpr","camarilla","pivot point","volume profile","anchored")
    if any(term in lower for term in intraday_terms): return _unsupported(category,index,name,"INTRADAY_DATA requires intraday bars", "needs_intraday_data","intraday")
    if any(term in lower for term in missing_terms): return _unsupported(category,index,name,"AUXILIARY_DATA required for this definition")
    ma=re.search(r"close above (sma|ema) (\d+)",lower)
    if ma: col=f"{ma.group(1).upper()}_{ma.group(2)}"; return _active(category,index,name,{"primitive":"greater_than","args":["Close",col]},required=[col])
    ma=re.search(r"close below (sma|ema) (\d+)",lower)
    if ma: col=f"{ma.group(1).upper()}_{ma.group(2)}"; return _active(category,index,name,{"primitive":"less_than","args":["Close",col]},"short",[col])
    cross=re.search(r"(sma|ema) (\d+)/(\d+) crossover",lower)
    if cross:
        a=f"{cross.group(1).upper()}_{cross.group(2)}"; b=f"{cross.group(1).upper()}_{cross.group(3)}"
        return _active(category,index,name,{"primitive":"crossover_above","args":[a,b]},required=[a,b])
    swing=re.search(r"(\d+)/(\d+) (ema|sma)",lower)
    if swing:
        a=f"{swing.group(3).upper()}_{swing.group(1)}"; b=f"{swing.group(3).upper()}_{swing.group(2)}"
        return _active(category,index,name,{"primitive":"crossover_above","args":[a,b]},required=[a,b])
    triple=re.search(r"alignment (\d+)/(\d+)/(\d+)",lower)
    if triple:
        cols=[f"EMA_{x}" for x in triple.groups()]; return _active(category,index,name,{"primitive":"trend_alignment","args":cols},required=cols)
    if "higher-high higher-low" in lower: return _active(category,index,name,{"all":[{"primitive":"higher_high"},{"primitive":"higher_low"}]})
    if "lower-high lower-low" in lower: return _active(category,index,name,{"all":[{"primitive":"lower_high"},{"primitive":"lower_low"}]},"short")
    don=re.search(r"donchian (20|55)",lower)
    if don: return _active(category,index,name,{"primitive":"rolling_high_break","args":[int(don.group(1))]})
    roc=re.search(r"(20|55|90)-day roc",lower)
    if roc: return _active(category,index,name,{"primitive":"roc_above","args":[int(roc.group(1)),5]},required=[f"ROC_{roc.group(1)}"])
    month=re.search(r"(6|12)-month momentum",lower)
    if month: period=126 if month.group(1)=="6" else 252; return _active(category,index,name,{"primitive":"roc_above","args":[period,0]},required=[f"ROC_{period}"])
    high=re.search(r"(20|55|90|100)-day high",lower)
    if high: return _active(category,index,name,{"primitive":"rolling_high_break","args":[int(high.group(1))]})
    low=re.search(r"(20|55|100)-day low",lower)
    if low: return _active(category,index,name,{"primitive":"rolling_low_break","args":[int(low.group(1))]},"short")
    rsi=re.search(r"rsi (?:above|below) (20|25|30|50|60|70|80)",lower)
    if rsi:
        level=int(rsi.group(1)); below="below" in lower; direction="long" if below else ("short" if "short" in lower else "long")
        return _active(category,index,name,{"primitive":"rsi_below" if below else "rsi_above","args":[level]},direction,["RSI_14"])
    if "rsi crosses above 30" in lower: return _active(category,index,name,{"primitive":"cross_above_level","args":["RSI_14",30]},required=["RSI_14"])
    if "rsi crosses below 70" in lower: return _active(category,index,name,{"primitive":"cross_below_level","args":["RSI_14",70]},"short",["RSI_14"])
    if "macd bullish" in lower: return _active(category,index,name,{"primitive":"macd_bullish"},required=["MACD","MACD_Signal"])
    if "macd histogram turns positive" in lower: return _active(category,index,name,{"primitive":"cross_above_level","args":["MACD_Hist",0]},required=["MACD_Hist"])
    if "z-score below" in lower: return _active(category,index,name,{"primitive":"less_than","args":["PRICE_ZSCORE_20",-2]},required=["PRICE_ZSCORE_20"])
    if "z-score above" in lower: return _active(category,index,name,{"primitive":"greater_than","args":["PRICE_ZSCORE_20",2]},"short",["PRICE_ZSCORE_20"])
    if "bollinger lower" in lower: return _active(category,index,name,{"primitive":"less_equal","args":["Close","Bollinger_Lower"]},required=["Bollinger_Lower"])
    if "bollinger upper" in lower: return _active(category,index,name,{"primitive":"greater_equal","args":["Close","Bollinger_Upper"]},"short",["Bollinger_Upper"])
    if "bollinger squeeze" in lower: return _active(category,index,name,{"all":[{"primitive":"bollinger_squeeze"},{"primitive":"greater_than","args":["Close","Bollinger_Upper"]}]},required=["Bollinger_Width","Bollinger_Upper"])
    if "previous-day high" in lower: return _active(category,index,name,{"primitive":"previous_day_high_break"})
    if "previous-day low" in lower: return _active(category,index,name,{"primitive":"previous_day_low_break"},"short")
    if "weekly high" in lower: return _active(category,index,name,{"primitive":"weekly_high_break"})
    if "weekly low" in lower: return _active(category,index,name,{"primitive":"weekly_low_break"},"short")
    if "monthly high" in lower: return _active(category,index,name,{"primitive":"monthly_high_break"})
    if "monthly low" in lower: return _active(category,index,name,{"primitive":"monthly_low_break"},"short")
    if "inside-bar" in lower or "inside bar" in lower: return _active(category,index,name,{"all":[{"primitive":"inside_bar"},{"primitive":"previous_day_high_break"}]})
    if "outside-bar" in lower or "outside bar" in lower: return _active(category,index,name,{"primitive":"outside_bar"})
    if "narrow range" in lower: window=4 if "4" in lower else 7; return _active(category,index,name,{"all":[{"primitive":"narrow_range","args":[window]},{"primitive":"previous_day_high_break"}]})
    if "bullish engulfing" in lower: return _active(category,index,name,{"primitive":"bullish_engulfing"})
    if "bearish engulfing" in lower: return _active(category,index,name,{"primitive":"bearish_engulfing"},"short")
    if "hammer" in lower: return _active(category,index,name,{"primitive":"hammer"})
    if "shooting star" in lower: return _active(category,index,name,{"primitive":"shooting_star"},"short")
    if "doji" in lower: return _active(category,index,name,{"all":[{"primitive":"doji"},{"primitive":"previous_day_high_break"}]})
    if "volume spike" in lower or "relative volume above 2" in lower: return _active(category,index,name,{"all":[{"primitive":"relative_volume_above","args":[2]},{"primitive":"previous_day_high_break"}]},required=["Volume_SMA_20"])
    if "high-volume bullish" in lower: return _active(category,index,name,{"all":[{"primitive":"volume_above_sma","args":[1.5]},{"primitive":"greater_than","args":["Close","Open"]}]},required=["Volume_SMA_20"])
    if "high-volume bearish" in lower: return _active(category,index,name,{"all":[{"primitive":"volume_above_sma","args":[1.5]},{"primitive":"less_than","args":["Close","Open"]}]},"short",["Volume_SMA_20"])
    if "atr expansion" in lower: return _active(category,index,name,{"all":[{"primitive":"atr_above_percentile"},{"primitive":"previous_day_high_break"}]},required=["ATR_14"])
    if "atr contraction" in lower: return _active(category,index,name,{"primitive":"atr_below_percentile"},required=["ATR_14"])
    if "bandwidth expansion" in lower: return _active(category,index,name,{"primitive":"bollinger_expansion"},required=["Bollinger_Width"])
    if "bandwidth contraction" in lower: return _active(category,index,name,{"primitive":"bollinger_squeeze"},required=["Bollinger_Width"])
    pull=re.search(r"pullback to (ema|sma) (\d+)",lower)
    if pull: col=f"{pull.group(1).upper()}_{pull.group(2)}"; return _active(category,index,name,{"primitive":"pullback_to","args":[col,.01,"long"]},required=[col])
    if "support" in lower: return _active(category,index,name,{"primitive":"support_bounce"})
    if "resistance" in lower: return _active(category,index,name,{"primitive":"resistance_rejection"},"short")
    return _unsupported(category,index,name,"UNMAPPED_PATTERN requires an audited primitive mapping")


def build_catalog() -> list[CatalogStrategy]:
    definitions=[]
    for category,names in CATALOG_GROUPS.items():
        for index,name in enumerate(names,1): definitions.append(_build(category,index,name))
    for index,name in enumerate(("Covered call simulation","Protective put simulation","Long straddle simulation"),1):
        definitions.append(CatalogStrategy(f"OPTIONS_SIM_{index:03d}",name,"options_simulation","options","simulation_only","daily","options_simulation","simulation_only",f"{name} requires historical option-chain data.","Registered for future simulation research only.",{"required_columns":["OPTION_CHAIN","IV","OPEN_INTEREST"],"optional_columns":[]},{},{"primitive":"greater_than","args":["Close",0]},unsupported_reason="Historical F&O chain data is unavailable",tags=("options","simulation_only")))
    ids=[item.strategy_id for item in definitions]
    if len(ids)!=len(set(ids)): raise ValueError("Duplicate generated strategy IDs")
    return definitions

BASE_STRATEGY_CATALOG=build_catalog()
