def false_discovery_assessment(tested_strategy_count,selected_rank=1,oos_confirmation=False,trade_count=0):
    risk="low";reasons=[]
    if tested_strategy_count>=100:risk="high";reasons.append("Top result was selected from a very large candidate set")
    elif tested_strategy_count>=20:risk="medium";reasons.append("Multiple-testing selection may overstate performance")
    if trade_count<30:risk="high" if risk=="medium" else max(risk,"medium",key=lambda x:{"low":0,"medium":1,"high":2}[x]);reasons.append("Completed-trade count is low")
    if not oos_confirmation:risk="high" if tested_strategy_count>=20 else "medium";reasons.append("Independent out-of-sample confirmation is required")
    return {"false_discovery_risk":risk,"reason":"; ".join(reasons) or "Candidate count and OOS evidence are acceptable","tested_strategy_count":tested_strategy_count,"selected_rank":selected_rank,"oos_confirmation":oos_confirmation,"warnings":["P-values are unavailable or unreliable for adaptive strategy selection"]+reasons}

def benjamini_hochberg(p_values,alpha=.05):
    indexed=sorted(enumerate(p_values),key=lambda x:x[1]);passed=[]
    for rank,(index,value) in enumerate(indexed,1):
        if value<=alpha*rank/len(indexed):passed.append(index)
    return sorted(passed)
