from __future__ import annotations


SCENARIOS={"base_case":{},"higher_slippage":{"slippage_multiplier":2},"higher_spread":{"spread_multiplier":2},"higher_fees":{"fee_multiplier":2},"delayed_entry":{"entry_delay_bars":1},"worse_fill":{"slippage_multiplier":3},"reduced_liquidity":{"liquidity_multiplier":.5},"skip_random_trades":{"deterministic_skip_every":5},"market_regime_filter":{"regime_filter":True},"smaller_universe":{"universe_fraction":.5},"larger_universe_if_available":{"universe_fraction":1.5},"stress_drawdown_period":{"stress_period":True}}

def run_robustness(config,data,evaluator):
    rows=[]
    for name,changes in SCENARIOS.items():
        metrics=evaluator(config,data,changes);ret=float(metrics.get("net_return_pct",0));pf=float(metrics.get("profit_factor",0) or 0);expect=float(metrics.get("expectancy",0));warnings=[]
        if name!="base_case" and ret<=0:warnings.append(f"{name} destroys positive performance")
        rows.append({"scenario_name":name,"config":changes,"metrics":metrics,"return_pct":ret,"max_drawdown":float(metrics.get("max_drawdown_pct",0)),"profit_factor":pf,"expectancy":expect,"trades_count":int(metrics.get("total_trades",0)),"pass_fail":"pass" if ret>0 and expect>=0 else "fail","warnings":warnings})
    stressed=[r for r in rows if r["scenario_name"]!="base_case"];score=sum(r["pass_fail"]=="pass" for r in stressed)/len(stressed)*100 if stressed else 0
    return rows,{"robustness_score":score,"passed":score>=60,"warnings":sum((r["warnings"] for r in rows),[])}
