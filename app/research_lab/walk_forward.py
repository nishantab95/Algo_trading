from __future__ import annotations

import statistics
from datetime import datetime,timezone
import pandas as pd


def generate_walk_forward_folds(start,end,train_window_months=12,test_window_months=3,step_months=3,mode="anchored_walk_forward"):
    start,end=pd.Timestamp(start),pd.Timestamp(end);folds=[];number=1;train_start=start;train_end=start+pd.DateOffset(months=train_window_months)-pd.Timedelta(days=1)
    while train_end<end:
        test_start=train_end+pd.Timedelta(days=1);test_end=min(test_start+pd.DateOffset(months=test_window_months)-pd.Timedelta(days=1),end)
        folds.append({"fold_number":number,"train_start":str(train_start.date()),"train_end":str(train_end.date()),"test_start":str(test_start.date()),"test_end":str(test_end.date())});number+=1
        if test_end>=end:break
        if mode=="rolling_walk_forward":train_start+=pd.DateOffset(months=step_months)
        train_end+=pd.DateOffset(months=step_months)
    return folds

def metric_value(metrics,*names,default=0):
    for name in names:
        if name in metrics and metrics[name] is not None:return float(metrics[name])
    return float(default)

def run_walk_forward_validation(experiment_id,config,data,evaluator,selector=None):
    vc=config.get("validation_config",{});folds=generate_walk_forward_folds(config["start_date"],config["end_date"],int(vc.get("train_window_months",12)),int(vc.get("test_window_months",3)),int(vc.get("step_months",3)),vc.get("walk_forward_mode","anchored_walk_forward"));rows=[]
    for fold in folds:
        try:
            train=data[(pd.to_datetime(data["Date"])>=fold["train_start"])&(pd.to_datetime(data["Date"])<=fold["train_end"])];test=data[(pd.to_datetime(data["Date"])>=fold["test_start"])&(pd.to_datetime(data["Date"])<=fold["test_end"])]
            if len(train)<int(vc.get("min_train_rows",20)) or len(test)<int(vc.get("min_test_rows",5)):raise ValueError("Fold has insufficient rows")
            params=selector(train,config) if selector else {};train_metrics=evaluator(config,train,params);test_metrics=evaluator(config,test,params);warnings=[]
            if metric_value(train_metrics,"net_return_pct")>0>=metric_value(test_metrics,"net_return_pct"):warnings.append("Positive in-sample result failed out-of-sample")
            rows.append({**fold,"selected_parameters":params,"train_metrics":train_metrics,"test_metrics":test_metrics,"trades_count":int(metric_value(test_metrics,"total_trades")),"test_return_pct":metric_value(test_metrics,"net_return_pct"),"test_sharpe":metric_value(test_metrics,"sharpe"),"test_sortino":metric_value(test_metrics,"sortino"),"test_max_drawdown":metric_value(test_metrics,"max_drawdown_pct"),"test_profit_factor":metric_value(test_metrics,"profit_factor"),"test_expectancy":metric_value(test_metrics,"expectancy"),"test_win_rate":metric_value(test_metrics,"win_rate"),"test_costs":metric_value(test_metrics,"total_costs"),"status":"completed","warnings":warnings})
        except Exception as exc:rows.append({**fold,"selected_parameters":{},"train_metrics":{},"test_metrics":{},"trades_count":0,"test_return_pct":0,"test_sharpe":0,"test_sortino":0,"test_max_drawdown":0,"test_profit_factor":0,"test_expectancy":0,"test_win_rate":0,"test_costs":0,"status":"failed","warnings":[str(exc)]})
    completed=[r for r in rows if r["status"]=="completed"];returns=[r["test_return_pct"] for r in completed];pfs=[r["test_profit_factor"] for r in completed];exps=[r["test_expectancy"] for r in completed];positive=sum(x>0 for x in returns)/len(returns)*100 if returns else 0;stability=max(0,100-(statistics.pstdev(returns)*5 if len(returns)>1 else 50))
    summary={"folds_completed":len(completed),"folds_failed":len(rows)-len(completed),"average_oos_return":statistics.mean(returns) if returns else 0,"median_oos_return":statistics.median(returns) if returns else 0,"positive_fold_rate":positive,"worst_fold_drawdown":max([r["test_max_drawdown"] for r in completed] or [0]),"average_profit_factor":statistics.mean(pfs) if pfs else 0,"average_expectancy":statistics.mean(exps) if exps else 0,"oos_stability_score":stability,"parameter_stability_score":0,"walk_forward_pass":bool(completed and positive>=60 and (statistics.mean(returns) if returns else 0)>0),"warnings":sum((r["warnings"] for r in rows),[])}
    return rows,summary
