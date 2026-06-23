def validate_risk_profile(payload:dict)->list[str]:
    errors=[]
    if float(payload.get("risk_per_trade_pct",1))<=0 or float(payload.get("risk_per_trade_pct",1))>5: errors.append("risk_per_trade_pct must be in (0, 5]")
    if int(payload.get("max_open_positions",10))<1: errors.append("max_open_positions must be positive")
    if float(payload.get("max_daily_loss",0))<0: errors.append("max_daily_loss cannot be negative")
    return errors
