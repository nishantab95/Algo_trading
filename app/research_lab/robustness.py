from __future__ import annotations

import pandas as pd


SCENARIOS={"base_case":{},"higher_slippage":{"slippage_multiplier":2},"higher_spread":{"spread_multiplier":2},"higher_fees":{"fee_multiplier":2},"delayed_entry":{"entry_delay_bars":1},"worse_fill":{"slippage_multiplier":3},"reduced_liquidity":{"liquidity_multiplier":.5},"skip_random_trades":{"deterministic_skip_every":5},"market_regime_filter":{"regime_filter":True},"smaller_universe":{"universe_fraction":.5},"larger_universe_if_available":{"universe_fraction":1.5},"stress_drawdown_period":{"stress_period":True}}


def skip_signals_reproducibly(data,signal_column,every=5):
    """Remove every Nth signal after stable date/symbol ordering.

    A deterministic stress is used instead of process-global randomness so the
    experiment manifest remains reproducible.
    """
    frame=data.copy().reset_index(drop=True)
    if signal_column not in frame or every<1:return frame,0
    order=frame.assign(_audit_order=range(len(frame)))
    order=order.sort_values([c for c in ("Date","Ticker","_audit_order") if c in order],kind="mergesort")
    values=pd.to_numeric(order[signal_column],errors="coerce").fillna(0)
    candidates=list(order.loc[values.ne(0),"_audit_order"])
    skipped=candidates[every-1::every]
    frame.loc[skipped,signal_column]=0
    return frame,len(skipped)


def stress_drawdown_slice(data):
    """Return the observed peak-to-trough market window from supplied closes."""
    if data is None or data.empty or not {"Date","Close"}<=set(data.columns):return data,False
    frame=data.copy();frame["Date"]=pd.to_datetime(frame["Date"],errors="coerce")
    market=frame.dropna(subset=["Date","Close"]).groupby("Date")["Close"].mean().sort_index()
    if len(market)<2:return data,False
    drawdown=market/market.cummax()-1;trough=drawdown.idxmin()
    history=market.loc[:trough];peak=history.idxmax()
    if peak>=trough:return data,False
    stressed=frame[(frame["Date"]>=peak)&(frame["Date"]<=trough)].copy()
    return (stressed,True) if stressed["Date"].nunique()>=2 else (data,False)


def run_robustness(config,data,evaluator):
    rows=[]
    for name,changes in SCENARIOS.items():
        metrics=evaluator(config,data,changes);available=bool(metrics.get("_scenario_available",True));ret=float(metrics.get("net_return_pct",0));pf=float(metrics.get("profit_factor",0) or 0);expect=float(metrics.get("expectancy",0));warnings=[]
        if metrics.get("_scenario_warning"):warnings.append(str(metrics["_scenario_warning"]))
        if name!="base_case" and ret<=0:warnings.append(f"{name} destroys positive performance")
        status="unavailable" if not available else ("pass" if ret>0 and expect>=0 else "fail")
        rows.append({"scenario_name":name,"config":changes,"metrics":metrics,"return_pct":ret,"max_drawdown":float(metrics.get("max_drawdown_pct",0)),"profit_factor":pf,"expectancy":expect,"trades_count":int(metrics.get("total_trades",0)),"pass_fail":status,"warnings":warnings})
    stressed=[r for r in rows if r["scenario_name"]!="base_case" and r["pass_fail"]!="unavailable"];score=sum(r["pass_fail"]=="pass" for r in stressed)/len(stressed)*100 if stressed else 0
    return rows,{"robustness_score":score,"passed":score>=60,"warnings":sum((r["warnings"] for r in rows),[])}
