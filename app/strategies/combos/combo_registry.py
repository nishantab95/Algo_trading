from __future__ import annotations
import json,re
from datetime import datetime,timezone
from app.db.database import Database,get_database
from app.strategies.combos.combo_schema import ComboDefinition

GROUPS={
"trend_momentum":"""EMA 9/21 crossover + RSI above 50|EMA 20/50 crossover + volume above average|SMA 50/200 golden cross + Nifty above 200 DMA|Supertrend long + ADX above 25|Donchian 20 breakout + ATR trailing stop|Donchian 55 breakout + 200 DMA filter|Ichimoku bullish + volume confirmation|Price above VWAP + EMA 9 above EMA 21|Close above EMA 200 + pullback to EMA 20|MACD bullish crossover + close above EMA 50|RSI above 60 + higher-high structure|52-week high + index above 200 DMA|20-day breakout + sector strength|55-day breakout + ATR stop|All-time high + relative volume above 2|ROC top 10 + weekly rebalance|Relative strength top 5 + trailing stop|Top sector + top stock momentum|Gap-up + VWAP hold|Gap-up + first range breakout|Strong close yesterday + continuation today|First-hour high breakout + VWAP support|End-of-day breakout + next-day exit|Close above EMA 20 + MACD histogram rising|Close above EMA 50 + RSI pullback to 50""".split("|"),
"breakout_combo":"""Opening range breakout + volume filter|Opening range breakout + market trend filter|Previous-day high breakout + VWAP confirmation|Weekly high breakout + RSI above 55|Monthly high breakout + EMA 50 slope positive|Consolidation breakout + Bollinger squeeze|Bollinger squeeze + volume expansion|NR7 breakout + ATR stop|Inside-bar breakout + trend filter|Triangle breakout + retest confirmation|Flag breakout + EMA 20 support|Cup-and-handle + weekly uptrend|Darvas box breakout + trailing stop|Pivot high breakout + volume above average|CPR breakout + VWAP confirmation|Camarilla breakout + no-trade first 15 minutes|Resistance breakout + close above level|Resistance breakout + retest + bullish candle|Breakout + relative volume above 2|Breakout + index confirmation|Breakout + sector confirmation|Breakout + avoid earnings day placeholder|Breakout + avoid low-volume stocks|Breakout + ATR volatility filter|Breakout + fixed 2:1 reward-risk exit""".split("|"),
"pullback_combo":"""Uptrend + pullback to EMA 20|Uptrend + pullback to EMA 50|Uptrend + RSI reset to 40-50|Uptrend + VWAP pullback|Uptrend + Fibonacci 38.2 pullback|Uptrend + Fibonacci 50 pullback|Uptrend + Fibonacci 61.8 pullback|200 DMA uptrend + 50 DMA pullback|Sector uptrend + stock pullback|Market uptrend + stock support bounce|EMA 20 pullback + bullish engulfing|EMA 50 pullback + hammer candle|VWAP pullback + bullish candle close|Support bounce + RSI divergence|Support bounce + volume spike|Pullback + MACD histogram recovery|Pullback + ADX trend filter|Pullback + ATR stop below swing low|Previous resistance becomes support|Higher-low pullback confirmation""".split("|"),
"mean_reversion_combo":"""RSI below 30 + support zone|RSI below 25 + bullish candle|Bollinger lower band + RSI oversold|Bollinger lower band + VWAP reclaim|Z-score below -2 + exit at mean|Price 3 ATR below EMA 20 + bounce|Gap-down + first 30-minute low hold|Gap-down + VWAP reclaim|Failed breakdown + volume confirmation|Oversold stock + index positive|Oversold sector + strongest stock bounce|Previous-close reversion + VWAP filter|Intraday range low bounce + tight stop|Lower Bollinger touch + close back inside|RSI divergence + MACD crossover|Panic volume selloff + reversal candle|Three red candles + support bounce|Mean reversion to EMA 20|Mean reversion to VWAP|Mean reversion to previous close""".split("|"),
"volume_volatility_combo":"""Volume spike + breakout|Volume spike + VWAP hold|Volume dry-up + breakout|OBV breakout + price breakout|MFI oversold + support bounce|Accumulation/distribution breakout|Anchored VWAP reclaim + trend filter|Volume profile POC bounce if volume profile exists|High-volume node support bounce if volume profile exists|Low-volume node breakout if volume profile exists|ATR contraction + breakout|ATR expansion + trend-following|Bollinger squeeze + MACD confirmation|Bollinger squeeze + RSI above 50|Low volatility + high relative strength""".split("|"),
"factor_combo":"""Quality + momentum|Value + momentum|Low volatility + quality|Dividend yield + low debt|High ROE + low debt + positive trend|High sales growth + price momentum|Sector momentum + stock quality|Nifty above 200 DMA + top relative strength stocks|Nifty below 200 DMA + cash filter|Monthly rebalance top 10 momentum|Quarterly rebalance quality momentum|Equal weight top 20 trend stocks|Equal weight top 10 low volatility stocks|Momentum basket + trailing market exit|Defensive basket during market downtrend""".split("|")}

ACTIVE_MAP={
"EMA 9/21 crossover + RSI above 50":([{"type":"primitive","ref":"crossover_above","args":["EMA_9","EMA_21"],"required":True},{"type":"primitive","ref":"rsi_above","args":[50],"required":True}],"all"),
"MACD bullish crossover + close above EMA 50":([{"type":"primitive","ref":"macd_bullish","args":[],"required":True},{"type":"primitive","ref":"greater_than","args":["Close","EMA_50"],"required":True}],"all"),
"Weekly high breakout + RSI above 55":([{"type":"primitive","ref":"weekly_high_break","args":[],"required":True},{"type":"primitive","ref":"rsi_above","args":[55],"required":True}],"all"),
"Bollinger squeeze + volume expansion":([{"type":"primitive","ref":"bollinger_squeeze","args":[],"required":True},{"type":"primitive","ref":"relative_volume_above","args":[1.5],"required":True}],"all"),
"Inside-bar breakout + trend filter":([{"type":"primitive","ref":"inside_bar","args":[],"required":True},{"type":"primitive","ref":"greater_than","args":["Close","EMA_200"],"required":True}],"all"),
"Uptrend + pullback to EMA 20":([{"type":"primitive","ref":"greater_than","args":["Close","EMA_200"],"required":True},{"type":"primitive","ref":"pullback_to","args":["EMA_20",.01,"long"],"required":True}],"all"),
"EMA 20 pullback + bullish engulfing":([{"type":"primitive","ref":"pullback_to","args":["EMA_20",.01,"long"],"required":True},{"type":"primitive","ref":"bullish_engulfing","args":[],"required":True}],"all"),
"RSI below 30 + support zone":([{"type":"primitive","ref":"rsi_below","args":[30],"required":True},{"type":"primitive","ref":"support_bounce","args":[],"required":True}],"all"),
"Bollinger lower band + RSI oversold":([{"type":"primitive","ref":"less_equal","args":["Close","Bollinger_Lower"],"required":True},{"type":"primitive","ref":"rsi_below","args":[30],"required":True}],"all"),
"Volume spike + breakout":([{"type":"primitive","ref":"relative_volume_above","args":[2],"required":True},{"type":"primitive","ref":"previous_day_high_break","args":[],"required":True}],"all"),
"ATR contraction + breakout":([{"type":"primitive","ref":"atr_below_percentile","args":[],"required":True},{"type":"primitive","ref":"previous_day_high_break","args":[],"required":True}],"all"),
"Bollinger squeeze + MACD confirmation":([{"type":"primitive","ref":"bollinger_squeeze","args":[],"required":True},{"type":"primitive","ref":"macd_bullish","args":[],"required":True}],"all")}

def build_combo_catalog():
    rows=[]; number=0
    for category,names in GROUPS.items():
        for name in names:
            number+=1; combo_id=f"COMBO_{number:03d}_{re.sub(r'[^A-Z0-9]+','_',name.upper()).strip('_')[:40]}"
            mapped=ACTIVE_MAP.get(name); status="active" if mapped else "needs_data"
            components=tuple(mapped[0]) if mapped else ({"type":"data_requirement","ref":"AUDITED_COMPONENT_MAPPING","required":True},)
            logic={"mode":mapped[1],"threshold":len(components)} if mapped else {"mode":"all","threshold":1}
            rows.append(ComboDefinition(combo_id,name,category,f"Config-driven combo research definition: {name}.",components,logic,status=status,tags=(category,"combo"),unsupported_reason=None if mapped else "Component mapping or required auxiliary data is unavailable"))
    ids=[row.combo_id for row in rows]
    if len(ids)!=len(set(ids)): raise ValueError("Duplicate combo IDs")
    return rows
COMBO_CATALOG=build_combo_catalog()

class ComboRegistry:
    def __init__(self,database:Database|None=None): self.database=database or get_database()
    def load_catalog(self):
        now=datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as connection:
            for combo in COMBO_CATALOG:
                connection.execute("""INSERT INTO combo_strategy_definitions(combo_id,name,category,description,logic_json,components_json,entry_json,exit_json,risk_json,status,tags_json,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(combo_id) DO UPDATE SET name=excluded.name,category=excluded.category,description=excluded.description,logic_json=excluded.logic_json,components_json=excluded.components_json,entry_json=excluded.entry_json,exit_json=excluded.exit_json,risk_json=excluded.risk_json,status=excluded.status,tags_json=excluded.tags_json,updated_at=excluded.updated_at""",(combo.combo_id,combo.name,combo.category,combo.description,json.dumps(combo.logic),json.dumps(combo.components),json.dumps(combo.entry),json.dumps(combo.exit),json.dumps(combo.risk),combo.status,json.dumps(combo.tags),int(combo.enabled),now,now))
    def list(self): return self.database.query("SELECT * FROM combo_strategy_definitions ORDER BY category,name")
    def get(self,combo_id):
        rows=self.database.query("SELECT * FROM combo_strategy_definitions WHERE combo_id=?",(combo_id,))
        if not rows: raise ValueError(f"Unknown combo: {combo_id}")
        return rows[0]
    def save(self,payload):
        now=datetime.now(timezone.utc).isoformat(); combo_id=payload["combo_id"]
        with self.database.transaction() as connection:
            connection.execute("""INSERT INTO combo_strategy_definitions(combo_id,name,category,description,logic_json,components_json,entry_json,exit_json,risk_json,status,tags_json,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(combo_id) DO UPDATE SET name=excluded.name,category=excluded.category,description=excluded.description,logic_json=excluded.logic_json,components_json=excluded.components_json,entry_json=excluded.entry_json,exit_json=excluded.exit_json,risk_json=excluded.risk_json,status=excluded.status,tags_json=excluded.tags_json,enabled=excluded.enabled,updated_at=excluded.updated_at""",(combo_id,payload["name"],payload.get("category","custom_combo"),payload.get("description",""),json.dumps(payload.get("logic",{"mode":"all"})),json.dumps(payload.get("components",[])),json.dumps(payload.get("entry",{"direction":"long"})),json.dumps(payload.get("exit",{})),json.dumps(payload.get("risk",{})),payload.get("status","active"),json.dumps(payload.get("tags",["custom"])),int(payload.get("enabled",False)),now,now))
        return self.get(combo_id)
    def toggle(self,combo_id,enabled):
        with self.database.transaction() as connection: connection.execute("UPDATE combo_strategy_definitions SET enabled=?,updated_at=? WHERE combo_id=?",(int(enabled),datetime.now(timezone.utc).isoformat(),combo_id))
        return self.get(combo_id)
