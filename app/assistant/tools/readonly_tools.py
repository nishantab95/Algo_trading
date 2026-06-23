from __future__ import annotations


class ReadOnlyTools:
    def __init__(self,database,profile,dashboards,search,rag,strategy_library=None,combo_library=None,backtests=None,paper=None,trade_history=None,state_provider=None):
        self.database=database; self.profile=profile; self.dashboards=dashboards; self.search=search; self.rag=rag; self.strategies=strategy_library; self.combos=combo_library; self.backtests=backtests; self.paper=paper; self.trade_history=trade_history; self.state_provider=state_provider
    def execute(self,name,args=None):
        args=args or {}
        mapping={
            "get_app_state":lambda:self.state_provider() if self.state_provider else {},"get_user_trading_profile":self.profile.get,"get_dashboard_layouts":self.dashboards.list,
            "get_strategy_library":lambda:self.strategies.list(**{k:args[k] for k in ("category","status","direction","search") if k in args}) if self.strategies else [],
            "get_strategy_details":lambda:self.strategies.get(args["strategy_id"]),"get_combo_library":lambda:self.combos.list() if self.combos else [],"get_combo_details":lambda:self.combos.get(args["combo_id"]),
            "get_strategy_validation":lambda:self.strategies.validate(args["strategy_id"]),"get_combo_validation":lambda:self.combos.validate(args["combo_id"]),
            "get_backtest_runs":lambda:self.backtests.list_runs() if self.backtests else [],"get_backtest_summary":lambda:self.backtests.details(args["run_id"]),"get_backtest_trades":lambda:self.backtests.trades(args["run_id"]),
            "get_paper_account":lambda:self.paper.account() if self.paper else {},"get_paper_positions":lambda:self.paper.positions() if self.paper else [],"get_paper_orders":lambda:self.paper.orders() if self.paper else [],
            "get_trade_history":lambda:self.trade_history.list(args) if self.trade_history else [],"get_risk_events":lambda:self.database.query("SELECT * FROM risk_events ORDER BY created_at DESC LIMIT 200"),"get_system_logs":lambda:self.database.query("SELECT * FROM system_logs ORDER BY created_at DESC LIMIT 200"),
            "search_app":lambda:self.search.search(args.get("query",""),args),"search_docs":lambda:self.rag.search(args.get("query",""),"docs"),"search_strategies":lambda:self.search.search(args.get("query",""),{"result_type":"strategy"}),"search_trades":lambda:self.trade_history.list(args),"search_backtests":lambda:self.search.search(args.get("query",""),{"result_type":"backtest"}),
            "get_trade_journal":lambda:{"status":"stage4_annotations_only","entries":self.database.query("SELECT * FROM trade_history_annotations ORDER BY updated_at DESC")},
            "get_watchlists":lambda:self.database.query("SELECT * FROM watchlists ORDER BY updated_at DESC"),
            "get_saved_screeners":lambda:self.database.query("SELECT * FROM saved_screeners ORDER BY updated_at DESC"),"get_latest_signals":lambda:[],
        }
        if name not in mapping: raise ValueError(f"Read-only tool is not implemented: {name}")
        return mapping[name]()
