def open_risk(broker): return sum(float(p["risk_amount"]) for p in broker.positions())
