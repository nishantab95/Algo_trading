def portfolio_summary(broker):
    account=broker.account();positions=broker.positions()
    return {**account,"position_value":sum(p["market_value"] for p in positions),"positions":positions,"pending_orders":sum(o["status"] in {"pending_approval","submitted","partially_filled"} for o in broker.orders())}
