from __future__ import annotations
import json,sqlite3
import numpy as np
import pandas as pd
import pytest
from flask import Flask

from app.backtesting.models import BacktestConfig
from app.db.database import Database
from app.services.backtest_service import BacktestService
from app.services.strategy_library_service import StrategyLibraryService,KNOWN_COLUMNS
from app.services.combo_strategy_service import ComboStrategyService
from app.strategies.catalog import BASE_STRATEGY_CATALOG,load_base_strategy_catalog
from app.strategies.combos.combo_registry import COMBO_CATALOG,ComboRegistry,load_combo_strategy_catalog
from app.strategies.combos.combo_explanations import explain_combo
from app.strategies.combos.combo_validator import validate_combo
from app.strategies.combos.combo_engine import generate_combo_signals
from app.strategies.explanations import explain_signal
from app.strategies.loader import generate_strategy_signals
from app.strategies.primitives.conditions import evaluate_logic,evaluate_primitive
from app.strategies.schemas import CatalogStrategy
from app.strategies.validator import validate_strategy

def frame(n=30):
    close=pd.Series(np.linspace(90,120,n)); return pd.DataFrame({"Date":pd.date_range("2024-01-01",periods=n),"Ticker":"TEST","Open":close-1,"High":close+2,"Low":close-2,"Close":close,"Volume":np.linspace(100000,300000,n),"EMA_9":close.ewm(span=9).mean(),"EMA_21":close.ewm(span=21).mean(),"EMA_50":close.ewm(span=50).mean(),"EMA_200":close.ewm(span=200).mean(),"RSI_14":60,"MACD":1,"MACD_Signal":.5,"MACD_Hist":.5,"ATR_14":2,"Bollinger_Upper":close+5,"Bollinger_Lower":close-5,"Bollinger_Width":10,"Volume_SMA_20":150000,"Volume_Z_Score":2})

def test_registry_has_220_plus_strategies(): assert len(BASE_STRATEGY_CATALOG)>=220
def test_combo_registry_has_100_plus_combos(): assert len(COMBO_CATALOG)>=100
def test_every_strategy_has_required_metadata():
    for x in BASE_STRATEGY_CATALOG: assert all((x.strategy_id,x.name,x.category,x.subcategory,x.direction,x.timeframe,x.asset_class,x.status,x.description,x.learning_note,x.data_requirements,x.entry,x.exit,x.risk,x.explanation_template))
def test_strategy_ids_unique(): assert len({x.strategy_id for x in BASE_STRATEGY_CATALOG})==len(BASE_STRATEGY_CATALOG)
def test_combo_ids_unique(): assert len({x.combo_id for x in COMBO_CATALOG})==len(COMBO_CATALOG)
def test_invalid_strategy_config_rejected():
    bad=CatalogStrategy("BAD","Bad","trend","bad","long",entry={"primitive":"does_not_exist"}); assert not validate_strategy(bad,KNOWN_COLUMNS).valid
def test_missing_required_column_needs_data():
    x=CatalogStrategy("MISS","Missing","factor","test","long",data_requirements={"required_columns":["PE_RATIO"],"optional_columns":[]},entry={"primitive":"greater_than","args":["Close",0]}); assert validate_strategy(x,{"Close"}).status=="needs_data"
def test_intraday_strategy_marked_needs_intraday(): assert validate_strategy(next(x for x in BASE_STRATEGY_CATALOG if x.timeframe=="intraday"),KNOWN_COLUMNS).status=="needs_intraday_data"
def test_options_strategy_simulation_only(): assert validate_strategy(next(x for x in BASE_STRATEGY_CATALOG if x.asset_class=="options_simulation"),KNOWN_COLUMNS).status=="simulation_only"
def test_ema_crossover_primitive():
    df=frame(); df.loc[:10,"EMA_9"]=90; df.loc[:10,"EMA_21"]=100; df.loc[11:,"EMA_9"]=110; assert evaluate_primitive(df,"crossover_above",["EMA_9","EMA_21"]).iloc[11]
def test_rsi_condition_primitive(): assert evaluate_primitive(frame(),"rsi_above",[50]).all()
def test_bollinger_condition_primitive(): assert len(evaluate_primitive(frame(),"bollinger_squeeze"))==30
def test_volume_condition_primitive(): assert evaluate_primitive(frame(),"relative_volume_above",[1]).iloc[-1]
def test_breakout_primitive():
    df=frame(); df.loc[df.index[-1],"Close"]=200; assert evaluate_primitive(df,"rolling_high_break",[20]).iloc[-1]
def test_pullback_condition():
    df=frame(); df["EMA_21"]=df["Close"]; assert evaluate_primitive(df,"pullback_to",["EMA_21",.01,"long"]).all()
def test_support_bounce_primitive(): assert len(evaluate_primitive(frame(60),"support_bounce"))==60
def test_all_logic(): assert evaluate_logic(frame(),{"all":[{"primitive":"rsi_above","args":[50]},{"primitive":"greater_than","args":["Close",0]}]}).all()
def test_any_logic(): assert evaluate_logic(frame(),{"any":[{"primitive":"rsi_below","args":[20]},{"primitive":"rsi_above","args":[50]}]}).all()
def test_not_logic(): assert evaluate_logic(frame(),{"not":{"primitive":"rsi_below","args":[20]}}).all()
def test_weighted_vote_logic(): assert evaluate_logic(frame(),{"weighted_vote":{"rules":[{"rule":{"primitive":"rsi_above","args":[50]},"weight":2}],"threshold":1}}).all()
def test_min_confirmations_logic(): assert evaluate_logic(frame(),{"min_confirmations":{"rules":[{"primitive":"rsi_above","args":[50]},{"primitive":"greater_than","args":["Close",0]}],"minimum":2}}).all()
def test_score_threshold_logic(): assert evaluate_logic(frame(),{"score_threshold":{"rules":[{"rule":{"primitive":"rsi_above","args":[50]},"weight":1}],"threshold":1}}).all()
def test_base_strategy_generates_signal():
    strategy=next(x for x in BASE_STRATEGY_CATALOG if x.name=="Close above EMA 9"); assert generate_strategy_signals(frame(),strategy)[strategy.strategy_id].sum()>0
def test_combo_strategy_generates_signal():
    combo=next(x for x in COMBO_CATALOG if x.status=="active").to_dict(); assert combo["combo_id"] in generate_combo_signals(frame(),combo,{})

def test_combo_not_logic_negates_single_component():
    combo={"combo_id":"NOT_RSI","name":"Not RSI","components":[{"type":"primitive","ref":"rsi_below","args":[20]}],"logic":{"mode":"not"},"entry":{"direction":"long"}}
    result=generate_combo_signals(frame(),combo,{})
    assert result["NOT_RSI"].eq(1).all() and validate_combo(combo)["valid"]
def test_combo_validation_catches_missing_component(): assert validate_combo({"components":[{"type":"base_strategy","ref":"MISSING"}],"logic":{"mode":"all"}},{"KNOWN"})["errors"]
def test_explanation_includes_values():
    strategy=next(x for x in BASE_STRATEGY_CATALOG if x.status=="active"); assert "RSI_14=55.000" in explain_signal(strategy,1,{"RSI_14":55},["rsi"],[])["explanation"]
def test_strategy_api_returns_list(tmp_path):
    from app.routes.strategy_library_routes import create_strategy_library_blueprint
    db=Database(tmp_path/"api.sqlite");db.initialize();service=StrategyLibraryService(db);service.initialize();app=Flask(__name__);app.register_blueprint(create_strategy_library_blueprint(service,None));assert len(app.test_client().get('/api/strategy-library').get_json()["data"])>=220
def test_combo_api_creates_and_validates(tmp_path):
    from app.routes.combo_strategy_routes import create_combo_strategy_blueprint
    db=Database(tmp_path/"combo.sqlite");db.initialize();lib=StrategyLibraryService(db);lib.initialize();svc=ComboStrategyService(db,lib,None);svc.initialize();app=Flask(__name__);app.register_blueprint(create_combo_strategy_blueprint(svc,None));client=app.test_client();payload={"name":"API Combo","components":[{"type":"primitive","ref":"rsi_above","args":[50]}],"logic":{"mode":"all"}};created=client.post('/api/combo-strategies',json=payload).get_json()["data"];assert client.post(f'/api/combo-strategies/{created["combo_id"]}/validate').get_json()["data"]["valid"]
def test_active_combo_catalog_validates():
    combo=next(x for x in COMBO_CATALOG if x.status=="active"); assert validate_combo(combo.to_dict())["valid"]
def test_combo_api_routes_backtest_to_stage2_mock(tmp_path):
    from app.routes.combo_strategy_routes import create_combo_strategy_blueprint
    db=Database(tmp_path/"combo_bt.sqlite");db.initialize();lib=StrategyLibraryService(db);lib.initialize();svc=ComboStrategyService(db,lib,None);svc.initialize();combo=next(x for x in svc.list() if x["status"]=="active")
    class Result:
        warnings=[]
        def summary(self): return {"run_id":"mock-run"}
    class Backtests:
        def run(self,config): assert config.strategy_id==combo["combo_id"]; return Result()
    app=Flask(__name__);app.register_blueprint(create_combo_strategy_blueprint(svc,Backtests()));response=app.test_client().post(f'/api/combo-strategies/{combo["combo_id"]}/backtest',json={"symbols":["TEST"]});assert response.get_json()["data"]["run_id"]=="mock-run"
def test_combo_runs_stage2_on_synthetic_data(tmp_path):
    db=Database(tmp_path/"bt.sqlite");db.initialize();lib=StrategyLibraryService(db);lib.initialize();combos=ComboStrategyService(db,lib,None);combos.initialize();combo=next(x for x in combos.list() if x["status"]=="active");result=BacktestService(db).run(BacktestConfig(combo["combo_id"],["TEST"],benchmark_symbol=None,liquidity_filter_enabled=False,cost_model_name="zero_cost_research"),frame(),persist=False);assert result.config.strategy_id==combo["combo_id"]
def test_disabled_strategy_not_in_enabled_set(tmp_path):
    db=Database(tmp_path/"disabled.sqlite");db.initialize();svc=StrategyLibraryService(db);svc.initialize();item=next(x for x in svc.list(status="active"));svc.toggle(item["strategy_id"],False);assert item["strategy_id"] not in {x["strategy_id"] for x in svc.list() if x["enabled"]}
def test_strategy_status_persists(tmp_path):
    db=Database(tmp_path/"persist.sqlite");db.initialize();svc=StrategyLibraryService(db);svc.initialize();item=next(x for x in svc.list(status="active"));svc.toggle(item["strategy_id"],True);assert StrategyLibraryService(db).get(item["strategy_id"])["enabled"]
def test_custom_combo_persists(tmp_path):
    db=Database(tmp_path/"custom.sqlite");db.initialize();lib=StrategyLibraryService(db);lib.initialize();svc=ComboStrategyService(db,lib,None);saved=svc.save({"name":"Persisted","components":[{"type":"primitive","ref":"rsi_above","args":[50]}],"logic":{"mode":"all"}});assert ComboStrategyService(db,lib,None).get(saved["combo_id"])["name"]=="Persisted"
def test_duplicate_strategy_id_rejected(tmp_path):
    db=Database(tmp_path/"duplicate.sqlite");db.initialize()
    with db.transaction() as connection:
        values=("DUP","A","x","x","long","daily","equity","active","d","l","{}","{}","[]","[]",0,"now","now");connection.execute("INSERT INTO strategy_definitions(strategy_id,name,category,subcategory,direction,timeframe,asset_class,status,description,learning_note,config_json,parameters_json,required_columns_json,tags_json,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",values)
        with pytest.raises(sqlite3.IntegrityError): connection.execute("INSERT INTO strategy_definitions(strategy_id,name,category,subcategory,direction,timeframe,asset_class,status,description,learning_note,config_json,parameters_json,required_columns_json,tags_json,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",values)
def test_bad_primitive_name_rejected(): assert validate_combo({"components":[{"type":"primitive","ref":"bad_name"}],"logic":{"mode":"all"}})["errors"]

def test_catalog_loader_contracts_return_complete_copies():
    assert len(load_base_strategy_catalog())>=220 and load_base_strategy_catalog() is not BASE_STRATEGY_CATALOG
    assert len(load_combo_strategy_catalog())>=100 and load_combo_strategy_catalog() is not COMBO_CATALOG

def test_every_combo_has_required_metadata():
    for combo in COMBO_CATALOG:
        assert all((combo.combo_id,combo.name,combo.category,combo.description,combo.components,combo.logic,combo.entry,combo.exit,combo.risk,combo.status))

def test_required_stage3_primitive_vocabulary_registered():
    from app.strategies.primitives.conditions import PRIMITIVES
    expected={"macd_histogram_positive","macd_histogram_rising","relative_strength_rank_if_available","high_volume_breakout","low_volume_pullback","obv_breakout_if_available","mfi_signal_if_available","narrow_range_7","wide_range_candle","pullback_to_ema","pullback_to_sma","pullback_to_support","pullback_after_breakout","rsi_reset_in_uptrend"}
    assert expected <= set(PRIMITIVES)

def test_optional_data_primitive_fails_clearly():
    with pytest.raises(KeyError,match="Relative_Strength_Rank"):
        evaluate_primitive(frame(),"relative_strength_rank_if_available")

def test_momentum_volume_and_pullback_aliases_are_deterministic():
    df=frame(60); df["SMA_20"]=df["Close"]; df["Relative_Strength_Rank"]=90; df["OBV"]=np.arange(60); df["MFI"]=10
    names_args=[("macd_histogram_positive",[]),("macd_histogram_rising",[]),("relative_strength_rank_if_available",[]),("high_volume_breakout",[20,1]),("low_volume_pullback",["EMA_21",2,.01]),("obv_breakout_if_available",[20]),("mfi_signal_if_available",[]),("narrow_range_7",[]),("wide_range_candle",[]),("pullback_to_ema",[21,.01]),("pullback_to_sma",[20,.01]),("pullback_to_support",[20,.01]),("pullback_after_breakout",[20,.02]),("rsi_reset_in_uptrend",[40,70])]
    for name,args in names_args:
        first=evaluate_primitive(df,name,args); second=evaluate_primitive(df.copy(),name,args)
        pd.testing.assert_series_equal(first,second)

def test_every_registered_primitive_returns_boolean_series():
    from app.strategies.primitives.conditions import PRIMITIVES
    df=frame(120); df["SMA_20"]=df["Close"]; df["Relative_Strength_Rank"]=90; df["OBV"]=np.arange(120); df["MFI"]=10
    args={
        "greater_than":["Close",0],"less_than":["Close",999],"greater_equal":["Close",0],"less_equal":["Close",999],"equal":["Close","Close"],"between":["Close",0,999],"outside_range":["Close",-1,0],
        "crossover_above":["EMA_9","EMA_21"],"crossover_below":["EMA_9","EMA_21"],"crossunder":["EMA_9","EMA_21"],"cross_above_level":["RSI_14",50],"cross_below_level":["RSI_14",70],
        "price_above_ma":["EMA_21"],"price_below_ma":["EMA_21"],"ma_slope_positive":["EMA_21"],"ma_slope_negative":["EMA_21"],"trend_alignment":["EMA_9","EMA_21"],
        "roc_above":[20,0],"roc_below":[20,0],"rsi_above":[50],"rsi_below":[70],"pullback_to":["EMA_21",.01,"long"]}
    for name in sorted(PRIMITIVES):
        result=evaluate_primitive(df,name,args.get(name,[]))
        assert result.index.equals(df.index) and result.dtype==bool, name

def test_strategy_explanation_has_auditable_context():
    strategy=next(x for x in BASE_STRATEGY_CATALOG if x.status=="active")
    result=explain_signal(strategy,1,{"RSI_14":55},["entry"],["filter-b"],symbol="INFY",signal_time="2026-06-23",passed_filters=["filter-a"],data_freshness_warning="one bar old")
    assert result["symbol"]=="INFY" and result["signal_time"]=="2026-06-23" and result["filters_passed"]==["filter-a"] and result["data_freshness_warning"]

def test_combo_explanation_has_auditable_context():
    result=explain_combo(COMBO_CATALOG[0].to_dict(),["ema"],["rsi"],{"RSI_14":45},symbol="INFY",signal_time="2026-06-23")
    assert result["combo"] and result["symbol"]=="INFY" and "exit_plan" in result and "risk_notes" in result

def test_strategy_validate_api_works(tmp_path):
    from app.routes.strategy_library_routes import create_strategy_library_blueprint
    db=Database(tmp_path/"validate.sqlite");db.initialize();service=StrategyLibraryService(db);service.initialize();strategy=next(x for x in service.list(status="active"));app=Flask(__name__);app.register_blueprint(create_strategy_library_blueprint(service,None))
    payload=app.test_client().post(f'/api/strategy-library/{strategy["strategy_id"]}/validate',json={"available_columns":list(KNOWN_COLUMNS)}).get_json()
    assert payload["success"] and payload["data"]["valid"]

def test_strategy_backtest_api_routes_to_stage2_mock(tmp_path):
    from app.routes.strategy_library_routes import create_strategy_library_blueprint
    db=Database(tmp_path/"strategy_bt.sqlite");db.initialize();service=StrategyLibraryService(db);service.initialize();strategy=next(x for x in service.list(status="active"))
    class Result:
        warnings=[]
        def summary(self): return {"run_id":"strategy-mock-run"}
    class Backtests:
        def run(self,config): assert config.strategy_id==strategy["strategy_id"]; return Result()
    app=Flask(__name__);app.register_blueprint(create_strategy_library_blueprint(service,Backtests()));payload=app.test_client().post(f'/api/strategy-library/{strategy["strategy_id"]}/backtest',json={"symbols":["TEST"]}).get_json()
    assert payload["success"] and payload["data"]["run_id"]=="strategy-mock-run"

def test_duplicate_combo_id_rejected_by_service(tmp_path):
    db=Database(tmp_path/"duplicate_combo.sqlite");db.initialize();lib=StrategyLibraryService(db);lib.initialize();svc=ComboStrategyService(db,lib,None);svc.initialize();existing=svc.list()[0]
    with pytest.raises(ValueError,match="Duplicate combo ID"):
        svc.save({"combo_id":existing["combo_id"],"name":"Duplicate","components":[{"type":"primitive","ref":"rsi_above","args":[50]}],"logic":{"mode":"all"}})

def test_bad_primitive_parameters_are_rejected():
    result=validate_combo({"name":"Bad args","components":[{"type":"primitive","ref":"rsi_above","args":[]}],"logic":{"mode":"all"}})
    assert any("Bad parameters" in error for error in result["errors"])

def test_possible_future_data_usage_is_rejected():
    bad=CatalogStrategy("FUTURE","Future","trend","test","long",entry={"primitive":"greater_than","args":["Close","shift(-1)"]})
    assert any("future-data" in error for error in validate_strategy(bad,KNOWN_COLUMNS).errors)

def test_unsupported_strategy_remains_visible(tmp_path):
    db=Database(tmp_path/"visible.sqlite");db.initialize();svc=StrategyLibraryService(db);svc.initialize()
    assert any(item["status"]!="active" for item in svc.list())
