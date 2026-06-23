from __future__ import annotations
import json,os
from datetime import datetime,timezone
import pandas as pd
import config_settings as cfg
from app.db.database import Database,get_database
from app.strategies.catalog import BASE_STRATEGY_CATALOG
from app.strategies.schemas import CatalogStrategy
from app.strategies.validator import validate_strategy
from app.strategies.loader import generate_strategy_signals
from app.strategies.primitives.conditions import PRIMITIVES
from app.strategies.explanations import explain_signal

KNOWN_COLUMNS={"Date","Ticker","Open","High","Low","Close","Volume","SMA_20","SMA_50","EMA_9","EMA_21","EMA_50","EMA_200","RSI_14","MACD","MACD_Signal","MACD_Hist","ATR_14","Bollinger_Upper","Bollinger_Middle","Bollinger_Lower","Bollinger_Width","Volume_SMA_20","Volume_Z_Score"}

class StrategyLibraryService:
    def __init__(self,database:Database|None=None,backtest_service=None): self.database=database or get_database(); self.backtest_service=backtest_service
    def initialize(self):
        now=datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as connection:
            for strategy in BASE_STRATEGY_CATALOG:
                config=strategy.to_dict()
                validation=validate_strategy(strategy,KNOWN_COLUMNS)
                connection.execute("""INSERT INTO strategy_definitions(strategy_id,name,category,subcategory,direction,timeframe,asset_class,status,description,learning_note,config_json,parameters_json,required_columns_json,tags_json,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(strategy_id) DO UPDATE SET name=excluded.name,category=excluded.category,subcategory=excluded.subcategory,direction=excluded.direction,timeframe=excluded.timeframe,asset_class=excluded.asset_class,status=excluded.status,description=excluded.description,learning_note=excluded.learning_note,config_json=excluded.config_json,parameters_json=excluded.parameters_json,required_columns_json=excluded.required_columns_json,tags_json=excluded.tags_json,updated_at=excluded.updated_at""",(strategy.strategy_id,strategy.name,strategy.category,strategy.subcategory,strategy.direction,strategy.timeframe,strategy.asset_class,strategy.status,strategy.description,strategy.learning_note,json.dumps(config),json.dumps(strategy.parameters),json.dumps(strategy.data_requirements.get("required_columns",[])),json.dumps(strategy.tags),int(strategy.enabled),now,now))
                connection.execute("UPDATE strategy_definitions SET status=? WHERE strategy_id=?",(validation.status,strategy.strategy_id))
                connection.execute("INSERT INTO strategy_validation_results(strategy_id,valid,status,warnings_json,errors_json,checked_at) VALUES(?,?,?,?,?,?)",(strategy.strategy_id,int(validation.valid),validation.status,json.dumps(validation.warnings),json.dumps(validation.errors),now))
            counts={}
            for strategy in BASE_STRATEGY_CATALOG: counts[strategy.category]=counts.get(strategy.category,0)+1
            for category,count in counts.items(): connection.execute("INSERT INTO strategy_categories(category,description,count,created_at,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(category) DO UPDATE SET count=excluded.count,updated_at=excluded.updated_at",(category,f"{category.replace('_',' ').title()} research definitions",count,now,now))
    def list(self,category=None,status=None,direction=None,search=None):
        rows=self.database.query("SELECT * FROM strategy_definitions ORDER BY category,name"); result=[]
        for row in rows:
            if category and row["category"]!=category: continue
            if status and row["status"]!=status: continue
            if direction and row["direction"]!=direction: continue
            if search and search.lower() not in (row["name"]+" "+row["description"]).lower(): continue
            result.append(self._decode(row))
        return result
    def get(self,strategy_id):
        rows=self.database.query("SELECT * FROM strategy_definitions WHERE strategy_id=?",(strategy_id,))
        if not rows: raise ValueError(f"Unknown strategy: {strategy_id}")
        item=self._decode(rows[0]); definition=CatalogStrategy(**item["config"])
        item["explanation_example"]=explain_signal(definition,1,{key:"current value" for key in item["required_columns"][:6]},["configured entry rules"],[])
        item["latest_signal_status"]="not_evaluated; run recalibration or backtest to generate a dated signal"
        return item
    def definition(self,strategy_id): return CatalogStrategy(**self.get(strategy_id)["config"])
    def toggle(self,strategy_id,enabled):
        item=self.get(strategy_id)
        if enabled and item["status"]!="active": raise ValueError(f"Cannot enable strategy with status {item['status']}")
        with self.database.transaction() as connection: connection.execute("UPDATE strategy_definitions SET enabled=?,updated_at=? WHERE strategy_id=?",(int(enabled),datetime.now(timezone.utc).isoformat(),strategy_id))
        return self.get(strategy_id)
    def validate(self,strategy_id,available_columns=None,backtest_mode=None):
        definition=self.definition(strategy_id); result=validate_strategy(definition,set(available_columns or KNOWN_COLUMNS),backtest_mode)
        now=datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as connection: connection.execute("INSERT INTO strategy_validation_results(strategy_id,valid,status,warnings_json,errors_json,checked_at) VALUES(?,?,?,?,?,?)",(strategy_id,int(result.valid),result.status,json.dumps(result.warnings),json.dumps(result.errors),now))
        return result.to_dict()
    def categories(self): return self.database.query("SELECT * FROM strategy_categories ORDER BY category")
    def primitives(self): return [{"name":name,"category":_primitive_category(name)} for name in sorted(PRIMITIVES)]
    def latest_backtest(self,strategy_id):
        rows=self.database.query("SELECT run_id,net_return_pct,max_drawdown_pct,total_trades,created_at FROM backtest_runs WHERE strategy_id=? ORDER BY created_at DESC LIMIT 1",(strategy_id,)); return rows[0] if rows else None
    def _decode(self,row):
        row=dict(row); row["enabled"]=bool(row["enabled"]); row["config"]=json.loads(row["config_json"]); row["parameters"]=json.loads(row["parameters_json"]); row["required_columns"]=json.loads(row["required_columns_json"]); row["tags"]=json.loads(row["tags_json"]); row["last_backtest"]=self.latest_backtest(row["strategy_id"]); return row

def _primitive_category(name):
    for category,terms in {"crossover":["cross"],"trend":["ma_","trend","higher","lower","price_"],"momentum":["rsi","roc","macd"],"volatility":["atr","bollinger","volatility"],"volume":["volume","obv","mfi"],"price_action":["bar","engulfing","hammer","star","doji","range"],"support_resistance":["high_break","low_break","support","resistance","pullback"]}.items():
        if any(term in name for term in terms): return category
    return "comparison"
