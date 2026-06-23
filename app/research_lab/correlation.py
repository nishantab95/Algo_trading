from __future__ import annotations

import math

def pearson(a,b):
    n=min(len(a),len(b));a=list(a)[:n];b=list(b)[:n]
    if n<2:return 0.0
    ma=sum(a)/n;mb=sum(b)/n;num=sum((x-ma)*(y-mb) for x,y in zip(a,b));da=math.sqrt(sum((x-ma)**2 for x in a));db=math.sqrt(sum((y-mb)**2 for y in b));return num/(da*db) if da and db else (1.0 if a==b else 0.0)

def compare_strategies(strategy_a,strategy_b,signals_a,signals_b,equity_a=None,equity_b=None):
    signal=pearson(signals_a,signals_b);equity=pearson(equity_a or [],equity_b or []);overlap=sum(bool(x) and bool(y) for x,y in zip(signals_a,signals_b))/max(sum(bool(x) or bool(y) for x,y in zip(signals_a,signals_b)),1)*100;redundancy=max(0,min(100,(abs(signal)*50+abs(equity)*30+overlap*.2)));recommendation="disable duplicate" if redundancy>=85 else "merge" if redundancy>=70 else "test separately" if redundancy>=40 else "keep both"
    return {"strategy_a":strategy_a,"strategy_b":strategy_b,"signal_correlation":signal,"equity_correlation":equity,"trade_overlap_pct":overlap,"drawdown_overlap_pct":0,"redundancy_score":redundancy,"recommendation":recommendation}
