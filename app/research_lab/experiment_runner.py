from __future__ import annotations

import json,uuid
from dataclasses import replace
from datetime import datetime,timezone

from app.backtesting.models import BacktestConfig
from app.research_lab.data_manifest import build_manifest
from app.research_lab.false_discovery import false_discovery_assessment
from app.research_lab.parameter_sweep import run_parameter_sweep
from app.research_lab.promotion import recommend
from app.research_lab.regime_analysis import analyze_regimes
from app.research_lab.robustness import run_robustness
from app.research_lab.scoring import evidence_score
from app.research_lab.symbol_analysis import analyze_symbols
from app.research_lab.validation import split_data
from app.research_lab.walk_forward import run_walk_forward_validation
from app.research_lab.experiment import now


class ResearchExperimentRunner:
    """Stage 6 orchestration. All trade simulation delegates to Stage 2 BacktestService.run."""
    def __init__(self,database,experiments,backtest_service):self.database,self.experiments,self.backtests=database,experiments,backtest_service
    def _config(self,exp,**changes):
        risk=exp.get("risk_settings",{});values={"strategy_id":exp.get("strategy_id") or exp.get("combo_id"),"symbols":exp["symbols"],"start_date":exp.get("start_date"),"end_date":exp.get("end_date"),"initial_capital":exp["initial_capital"],"execution_price_model":exp["execution_model"],"max_positions":exp["max_positions"],"position_sizing_method":exp["sizing_model"],"cost_model_name":exp["cost_model"],"slippage_bps":exp["slippage_bps"],"spread_bps":exp["spread_bps"],**{k:v for k,v in risk.items() if k in BacktestConfig.__dataclass_fields__}}
        values.update({k:v for k,v in changes.items() if k in BacktestConfig.__dataclass_fields__});return BacktestConfig(**values)
    def _metrics(self,exp,data=None,changes=None):
        changes=changes or {};config_changes=dict(changes)
        if "slippage_multiplier" in config_changes:config_changes["slippage_bps"]=exp["slippage_bps"]*config_changes.pop("slippage_multiplier")
        if "spread_multiplier" in config_changes:config_changes["spread_bps"]=exp["spread_bps"]*config_changes.pop("spread_multiplier")
        if "fee_multiplier" in config_changes:
            factor=config_changes.pop("fee_multiplier");config_changes["cost_model_name"]="custom";config_changes["custom_cost_settings"]={"brokerage_bps":3*factor,"stt_bps_buy":10*factor,"stt_bps_sell":10*factor,"exchange_txn_bps":.0297*factor,"sebi_bps":.001*factor,"stamp_duty_bps_buy":1.5*factor}
        if "liquidity_multiplier" in config_changes:config_changes["min_avg_volume"]=100000/max(float(config_changes.pop("liquidity_multiplier")),.01)
        if "universe_fraction" in config_changes:
            fraction=float(config_changes.pop("universe_fraction"));config_changes["symbols"]=exp["symbols"][:max(1,min(len(exp["symbols"]),round(len(exp["symbols"])*fraction)))]
        config=self._config(exp,**config_changes);result=self.backtests.run(config,data,persist=False);return result.metrics if hasattr(result,"metrics") else result
    def run(self,experiment_id):
        exp=self.experiments.get(experiment_id);self.experiments.set_status(experiment_id,"running")
        try:
            config=self._config(exp);data=self.backtests.load_data(config);manifest=build_manifest(experiment_id,data,exp);self._persist_manifest(manifest)
            train,test,split=split_data(data,exp.get("validation_config",{}).get("split_mode","percentage_split"),exp.get("validation_config",{}));baseline=self._metrics(exp,data);train_metrics=self._metrics(exp,train);test_metrics=self._metrics(exp,test)
            evaluator=lambda cfg,frame,changes:self._metrics(exp,data if frame is None else frame,changes)
            folds,wf=run_walk_forward_validation(experiment_id,exp,data,evaluator);self._persist_folds(experiment_id,folds)
            sweep,stability=run_parameter_sweep(exp,train,test,evaluator);self._persist_sweep(experiment_id,sweep)
            scenarios,robust=run_robustness(exp,data,evaluator);self._persist_robustness(experiment_id,scenarios)
            baseline_result=self.backtests.run(config,data,persist=False);trades=baseline_result.trades if hasattr(baseline_result,"trades") else []
            symbols,symbol_summary=analyze_symbols(trades,exp["symbols"]);self._persist_symbols(experiment_id,symbols)
            regimes,regime_summary=analyze_regimes(trades,None);self._persist_regimes(experiment_id,regimes)
            tested=self.database.query("SELECT COUNT(*) count FROM strategy_definitions")[0]["count"]+self.database.query("SELECT COUNT(*) count FROM combo_strategy_definitions")[0]["count"]
            false_discovery=false_discovery_assessment(tested,1,float(test_metrics.get("net_return_pct",0))>0,int(test_metrics.get("total_trades",0)))
            evidence={"oos_return":test_metrics.get("net_return_pct",0),"walk_forward_stability":wf["oos_stability_score"],"parameter_stability":stability["parameter_stability_score"],"robustness_score":robust["robustness_score"],"max_drawdown":test_metrics.get("max_drawdown_pct",100),"trade_count":test_metrics.get("total_trades",0),"symbol_coverage":symbol_summary["traded_symbols"],"regime_score":0 if not regime_summary["available"] else 50,"cost_score":robust["robustness_score"],"false_discovery_risk":false_discovery["false_discovery_risk"],"paper_alignment":0};score=evidence_score(evidence)
            warnings=manifest["warnings"]+wf["warnings"]+robust["warnings"]+symbol_summary["warnings"]+regime_summary["warnings"]+false_discovery["warnings"]+score["penalties"]
            recommendation=recommend(score["evidence_score"],warnings);summary={"experiment_id":experiment_id,"split":split,"data_manifest":manifest,"in_sample_metrics":train_metrics,"out_of_sample_metrics":test_metrics,"full_period_metrics":baseline,"walk_forward":wf,"parameter_stability":stability,"robustness":robust,"regime_analysis":regime_summary,"symbol_analysis":symbol_summary,"false_discovery":false_discovery,"evidence":score,"recommendation":recommendation,"warnings":warnings};self._persist_summary(experiment_id,summary);self.experiments.set_status(experiment_id,"completed");return summary
        except Exception as exc:self.experiments.set_status(experiment_id,"failed");raise
    def _persist_manifest(self,m):
        with self.database.transaction() as c:c.execute("INSERT INTO research_data_manifests(id,experiment_id,data_source,symbols_json,symbol_count,date_start,date_end,rows_per_symbol_json,missing_dates_json,skipped_symbols_json,stale_symbols_json,data_hash,code_version,config_hash,warnings_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(m["id"],m["experiment_id"],m["data_source"],json.dumps(m["symbols"]),m["symbol_count"],m["date_start"],m["date_end"],json.dumps(m["rows_per_symbol"]),json.dumps(m["missing_dates"]),json.dumps(m["skipped_symbols"]),json.dumps(m["stale_symbols"]),m["data_hash"],m["code_version"],m["config_hash"],json.dumps(m["warnings"]),m["created_at"]))
    def _persist_folds(self,eid,rows):
        with self.database.transaction() as c:
            for r in rows:c.execute("INSERT INTO walk_forward_folds(id,experiment_id,fold_number,train_start,train_end,test_start,test_end,selected_parameters_json,train_metrics_json,test_metrics_json,trades_count,test_return_pct,test_sharpe,test_sortino,test_max_drawdown,test_profit_factor,test_expectancy,test_win_rate,test_costs,status,warnings_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",("fold_"+uuid.uuid4().hex,eid,r["fold_number"],r["train_start"],r["train_end"],r["test_start"],r["test_end"],json.dumps(r["selected_parameters"]),json.dumps(r["train_metrics"]),json.dumps(r["test_metrics"]),r["trades_count"],r["test_return_pct"],r["test_sharpe"],r["test_sortino"],r["test_max_drawdown"],r["test_profit_factor"],r["test_expectancy"],r["test_win_rate"],r["test_costs"],r["status"],json.dumps(r["warnings"]),now()))
    def _persist_sweep(self,eid,rows):
        with self.database.transaction() as c:
            for r in rows:c.execute("INSERT INTO parameter_sweep_results(experiment_id,parameter_set_id,parameters_json,full_metrics_json,train_metrics_json,test_metrics_json,walk_forward_metrics_json,rank,stability_score,overfit_warning,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(eid,r["parameter_set_id"],json.dumps(r["parameters"]),json.dumps(r["full_metrics"]),json.dumps(r["train_metrics"]),json.dumps(r["test_metrics"]),json.dumps(r["walk_forward_metrics"]),r["rank"],r["stability_score"],r["overfit_warning"],now()))
    def _persist_robustness(self,eid,rows):
        with self.database.transaction() as c:
            for r in rows:c.execute("INSERT INTO robustness_results(experiment_id,scenario_name,config_json,metrics_json,return_pct,max_drawdown,profit_factor,expectancy,trades_count,pass_fail,warnings_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(eid,r["scenario_name"],json.dumps(r["config"]),json.dumps(r["metrics"]),r["return_pct"],r["max_drawdown"],r["profit_factor"],r["expectancy"],r["trades_count"],r["pass_fail"],json.dumps(r["warnings"]),now()))
    def _persist_symbols(self,eid,rows):
        with self.database.transaction() as c:
            for r in rows:c.execute("INSERT INTO symbol_analysis_results(experiment_id,symbol,trades_count,net_pnl,return_pct,win_rate,profit_factor,expectancy,max_drawdown,contribution_pct,warnings_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(eid,r["symbol"],r["trades_count"],r["net_pnl"],r["return_pct"],r["win_rate"],r["profit_factor"],r["expectancy"],r["max_drawdown"],r["contribution_pct"],json.dumps(r["warnings"]),now()))
    def _persist_regimes(self,eid,rows):
        with self.database.transaction() as c:
            for r in rows:c.execute("INSERT INTO regime_results(experiment_id,regime_name,date_start,date_end,trades_count,return_pct,win_rate,profit_factor,expectancy,max_drawdown,warnings_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(eid,r["regime_name"],r.get("date_start"),r.get("date_end"),r["trades_count"],r["return_pct"],r["win_rate"],r["profit_factor"],r["expectancy"],r["max_drawdown"],json.dumps(r.get("warnings",[])),now()))
    def _persist_summary(self,eid,summary):
        stamp=now()
        with self.database.transaction() as c:c.execute("INSERT INTO research_validation_summaries(experiment_id,summary_json,evidence_score,recommendation,warnings_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(experiment_id) DO UPDATE SET summary_json=excluded.summary_json,evidence_score=excluded.evidence_score,recommendation=excluded.recommendation,warnings_json=excluded.warnings_json,updated_at=excluded.updated_at",(eid,json.dumps(summary,default=str),summary["evidence"]["evidence_score"],summary["recommendation"]["decision"],json.dumps(summary["warnings"]),stamp,stamp))
