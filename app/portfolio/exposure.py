from collections import defaultdict

def exposure(broker):
    symbol={};strategy=defaultdict(float)
    for p in broker.positions():symbol[p["symbol"]]=p["market_value"];strategy[p.get("strategy_id") or "unassigned"]+=p["market_value"]
    total=sum(symbol.values());return {"gross":total,"net":total,"by_symbol":symbol,"by_strategy":dict(strategy)}
