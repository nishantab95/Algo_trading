from __future__ import annotations

import inspect,json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from flask import Flask

from app.db.database import Database
from app.research_lab.correlation import compare_strategies
from app.research_lab.data_manifest import build_manifest
from app.research_lab.experiment import ResearchDecisionService,ResearchExperimentService
from app.research_lab.experiment_runner import ResearchExperimentRunner
from app.research_lab.exports import ResearchExportService
from app.research_lab.false_discovery import false_discovery_assessment
from app.research_lab.parameter_sweep import run_parameter_sweep
from app.research_lab.regime_analysis import analyze_regimes
from app.research_lab.robustness import run_robustness
from app.research_lab.scoring import evidence_score
from app.research_lab.symbol_analysis import analyze_symbols
from app.research_lab.validation import split_data,validate_market_data
from app.research_lab.walk_forward import generate_walk_forward_folds,run_walk_forward_validation
from app.routes.research_lab_routes import create_research_lab_blueprint


def market_data(days=1000,symbols=("INFY","TCS","RELIANCE")):
    rows=[]
    for s_index,symbol in enumerate(symbols):
        for i,date in enumerate(pd.date_range("2020-01-01",periods=days,freq="D")):
            price=100+s_index*20+i*.02;rows.append({"Date":date,"Ticker":symbol,"Open":price,"High":price+1,"Low":price-1,"Close":price+.2,"Volume":100000+i,"TEST":1 if i%20==0 else 0})
    return pd.DataFrame(rows)

class FakeBacktests:
    def __init__(self,data):self.data=data;self.calls=[]
    def load_data(self,config):self.calls.append(("load",config));return self.data.copy()
    def run(self,config,data=None,persist=False):
        self.calls.append(("run",config,persist));frame=self.data if data is None else data;days=max(pd.to_datetime(frame["Date"]).nunique(),1);ret=days/100-config.slippage_bps*.08-config.spread_bps*.03-(config.stop_loss_pct-.05)**2*100;trades=[]
        for i,symbol in enumerate(config.symbols[:3]):trades.append({"symbol":symbol,"net_pnl":1000 if i==0 else 100,"return_pct":2 if i==0 else .2})
        metrics={"net_return_pct":ret,"max_drawdown_pct":max(1,12-ret),"sharpe":ret/5,"sortino":ret/4,"profit_factor":max(.5,1+ret/20),"expectancy":ret*10,"win_rate":55,"total_trades":max(1,days//20),"total_costs":config.slippage_bps*10}
        return SimpleNamespace(metrics=metrics,trades=trades,warnings=[])

@pytest.fixture
def stack(tmp_path):
    db=Database(tmp_path/"stage6.sqlite");db.initialize();experiments=ResearchExperimentService(db);data=market_data();backtests=FakeBacktests(data);runner=ResearchExperimentRunner(db,experiments,backtests);decisions=ResearchDecisionService(db);exports=ResearchExportService(db,tmp_path)
    return SimpleNamespace(db=db,experiments=experiments,data=data,backtests=backtests,runner=runner,decisions=decisions,exports=exports)

def create_exp(stack,**overrides):
    payload={"name":"Validation","strategy_id":"TEST","symbols":["INFY","TCS","RELIANCE"],"start_date":"2020-01-01","end_date":"2022-09-26","parameter_grid":{"stop_loss_pct":[.04,.05,.06]},"validation_config":{"split_mode":"percentage_split","train_pct":70,"train_window_months":12,"test_window_months":3,"step_months":3,"min_train_rows":20,"min_test_rows":5},**overrides}
    return stack.experiments.create(payload)

def test_01_experiment_config_saves_correctly(stack):
    exp=create_exp(stack);assert exp["strategy_id"]=="TEST" and exp["symbols"]==["INFY","TCS","RELIANCE"] and exp["status"]=="draft"

def test_02_data_manifest_stores_symbol_counts_and_range(stack):
    exp=create_exp(stack);m=build_manifest(exp["id"],stack.data,exp);assert m["symbol_count"]==3 and m["date_start"]=="2020-01-01" and m["date_end"]=="2022-09-26" and m["data_hash"]

def test_03_missing_data_warning_is_generated():
    result=validate_market_data(pd.DataFrame({"Date":pd.date_range("2020-01-01",periods=5),"Ticker":["X"]*5,"Close":[1]*5}),["X"]);assert any("Missing OHLCV" in w for w in result["warnings"])

def test_04_fixed_train_test_split_works(stack):
    train,test,meta=split_data(stack.data,"fixed_date_split",{"split_date":"2021-12-31"});assert pd.to_datetime(train.Date).max()<pd.to_datetime(test.Date).min() and meta["mode"]=="fixed_date_split"

def test_05_percentage_train_test_split_works(stack):
    train,test,_=split_data(stack.data,"percentage_split",{"train_pct":80});assert len(train)>len(test)>0

def test_06_walk_forward_folds_generated_correctly():
    folds=generate_walk_forward_folds("2020-01-01","2022-12-31",12,3,3);assert len(folds)>=5 and folds[0]["fold_number"]==1

def test_07_walk_forward_never_uses_future_data():
    for fold in generate_walk_forward_folds("2020-01-01","2022-12-31"):assert fold["train_end"]<fold["test_start"]<=fold["test_end"]

def test_08_failed_fold_is_recorded(stack):
    config={"start_date":"2020-01-01","end_date":"2022-09-26","validation_config":{"train_window_months":12,"test_window_months":3,"step_months":3,"min_train_rows":1,"min_test_rows":1}}
    rows,summary=run_walk_forward_validation("x",config,stack.data,lambda *_:(_ for _ in ()).throw(ValueError("synthetic failure")));assert rows and all(r["status"]=="failed" for r in rows) and summary["folds_failed"]==len(rows)

def test_09_parameter_sweep_stores_ranked_results():
    config={"parameter_grid":{"x":[1,2,10]}};ev=lambda _c,_d,p:{"net_return_pct":p["x"],"max_drawdown_pct":1}
    rows,_=run_parameter_sweep(config,None,None,ev);assert len(rows)==3 and rows[0]["rank"]==1 and rows[0]["parameters"]["x"]==10

def test_10_parameter_stability_detects_isolated_best():
    config={"parameter_grid":{"x":[1,2,20]}};ev=lambda _c,_d,p:{"net_return_pct":p["x"],"max_drawdown_pct":0}
    rows,summary=run_parameter_sweep(config,None,None,ev);assert summary["isolated_best"] and rows[0]["overfit_warning"]

def robustness_evaluator(_config,_data,changes):
    penalty=changes.get("slippage_multiplier",1)+changes.get("fee_multiplier",1)+changes.get("entry_delay_bars",0);return {"net_return_pct":10-penalty,"max_drawdown_pct":5,"profit_factor":1.5,"expectancy":20,"total_trades":40}

def test_11_robustness_higher_slippage_runs():assert any(r["scenario_name"]=="higher_slippage" for r in run_robustness({},None,robustness_evaluator)[0])
def test_12_robustness_higher_cost_runs():assert any(r["scenario_name"]=="higher_fees" for r in run_robustness({},None,robustness_evaluator)[0])
def test_13_delayed_entry_scenario_runs():assert any(r["scenario_name"]=="delayed_entry" for r in run_robustness({},None,robustness_evaluator)[0])

def test_14_symbol_contribution_analysis_works():
    rows,summary=analyze_symbols([{"symbol":"INFY","net_pnl":100,"return_pct":2},{"symbol":"TCS","net_pnl":50,"return_pct":1}],["INFY","TCS"]);assert len(rows)==2 and summary["symbol_coverage_pct"]==100

def test_15_one_symbol_concentration_warning_works():
    rows,summary=analyze_symbols([{"symbol":"INFY","net_pnl":1000},{"symbol":"TCS","net_pnl":1}],["INFY","TCS"]);assert any("concentration" in w.lower() for w in summary["warnings"])

def test_16_regime_analysis_handles_missing_benchmark():
    rows,summary=analyze_regimes([],None);assert rows==[] and summary["available"] is False and "not fabricated" in summary["warnings"][0]

def test_17_false_discovery_high_risk_warning():assert false_discovery_assessment(353,1,False,10)["false_discovery_risk"]=="high"

def test_18_evidence_score_penalizes_bad_oos():
    bad=evidence_score({"oos_return":-5,"walk_forward_stability":80,"parameter_stability":80,"robustness_score":80});good=evidence_score({"oos_return":5,"walk_forward_stability":80,"parameter_stability":80,"robustness_score":80});assert bad["evidence_score"]<good["evidence_score"] and bad["penalties"]

def test_19_evidence_score_penalizes_unstable_parameters():assert evidence_score({"oos_return":2,"parameter_stability":10})["evidence_score"]<evidence_score({"oos_return":2,"parameter_stability":90})["evidence_score"]

def test_20_promotion_decision_requires_approval(stack):
    exp=create_exp(stack);d=stack.decisions.draft(exp,{"decision":"paper_test_candidate","reason":"Evidence","warnings":[]},80);assert d["status"]=="pending" and not d["approved_by_user"]

def test_21_assistant_cannot_approve_promotion_itself(stack):
    exp=create_exp(stack);d=stack.decisions.draft(exp,{"decision":"paper_test_candidate","reason":"Evidence","warnings":[]},80)
    with pytest.raises(PermissionError):stack.decisions.approve(d["id"],"assistant")

def test_22_tiny_live_label_cannot_be_approved_implicitly(stack):
    exp=create_exp(stack);d=stack.decisions.draft(exp,{"decision":"tiny_live_candidate_later","reason":"Research label only","warnings":[]},95);assert d["status"]=="pending" and d["approved_at"] is None

def test_23_correlation_detects_duplicate_signals():
    r=compare_strategies("A","B",[0,1,0,1],[0,1,0,1],[100,101,102],[100,101,102]);assert r["redundancy_score"]>=85 and r["recommendation"]=="disable duplicate"

def test_24_research_report_export_works(stack):
    exp=create_exp(stack);summary={"evidence":{"evidence_score":20},"recommendation":{"decision":"reject"},"warnings":["Synthetic"]};stamp="2026-01-01T00:00:00+00:00"
    with stack.db.transaction() as c:c.execute("INSERT INTO research_validation_summaries(experiment_id,summary_json,evidence_score,recommendation,warnings_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(exp["id"],json.dumps(summary),20,"reject",json.dumps(summary["warnings"]),stamp,stamp))
    path=Path(stack.exports.export_experiment(stack.experiments.get(exp["id"])));assert path.exists() and "Evidence and recommendation" in path.read_text(encoding="utf-8")

def test_25_api_response_format_is_consistent(stack):
    app=Flask(__name__);app.register_blueprint(create_research_lab_blueprint(stack.experiments,stack.runner,stack.decisions,stack.exports,stack.db));payload=app.test_client().get("/api/research/experiments").get_json();assert payload["success"] is True and "data" in payload and "warnings" in payload

def test_26_stage6_uses_stage2_backtester():
    from app.services.backtest_service import BacktestService
    import main
    assert isinstance(main._RESEARCH_RUNNER.backtests,BacktestService) and ".backtests.run" in inspect.getsource(ResearchExperimentRunner._metrics)

def test_27_stage6_does_not_create_live_orders():
    sources="\n".join(p.read_text(encoding="utf-8") for p in (Path(__file__).parents[1]/"app"/"research_lab").glob("*.py"));assert "place_order" not in sources and "kite" not in sources.lower()

def test_28_stage6_does_not_enable_live_trading():
    sources="\n".join(p.read_text(encoding="utf-8") for p in (Path(__file__).parents[1]/"app"/"research_lab").glob("*.py"));assert "enable_live_trading" not in sources

def test_29_no_ml_prediction_model_imported_into_trading_engine():
    sources="\n".join(p.read_text(encoding="utf-8") for p in (Path(__file__).parents[1]/"app").rglob("*.py"));assert all(x not in sources for x in ("import tensorflow","import torch","import sklearn","import xgboost"))

def test_30_full_runner_persists_reproducible_evidence(stack):
    exp=create_exp(stack);summary=stack.runner.run(exp["id"]);assert stack.experiments.get(exp["id"])["status"]=="completed" and summary["data_manifest"]["config_hash"] and stack.db.query("SELECT * FROM walk_forward_folds WHERE experiment_id=?",(exp["id"],)) and stack.db.query("SELECT * FROM robustness_results WHERE experiment_id=?",(exp["id"],))
