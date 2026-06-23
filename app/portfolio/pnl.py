def pnl(broker):
    a=broker.account();return {key:a[key] for key in ("realized_pnl","unrealized_pnl","daily_pnl","weekly_pnl","monthly_pnl")}
