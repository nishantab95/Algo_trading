from __future__ import annotations

from app.assistant.guardrails import FORBIDDEN_ACTIONS,assert_tool_allowed
from app.assistant.permissions import APPROVAL_REQUIRED,DRAFT_ONLY,READ_ONLY
from app.assistant.schemas import ToolDefinition

READ_ONLY_TOOLS={"get_app_state","get_user_trading_profile","get_dashboard_layouts","get_strategy_library","get_strategy_details","get_combo_library","get_combo_details","get_strategy_validation","get_combo_validation","get_latest_signals","get_backtest_runs","get_backtest_summary","get_backtest_trades","get_paper_account","get_paper_positions","get_paper_orders","get_paper_fills","get_paper_snapshots","get_paper_analytics","get_strategy_paper_reviews","get_research_experiments","get_research_experiment","get_walk_forward_results","get_robustness_results","get_research_decisions","get_trade_history","get_trade_journal","get_risk_events","get_system_logs","get_watchlists","get_saved_screeners","search_app","search_docs","search_strategies","search_trades","search_backtests","get_broker_status","get_broker_reconciliation_latest","get_live_readiness","get_tiny_live_status","get_shadow_live_report","explain_tiny_live_blockers"}
DRAFT_TOOLS={"draft_strategy_change","draft_combo_change","draft_strategy_enable_disable","draft_screener_config","draft_watchlist_update","draft_backtest_request","draft_dashboard_layout","draft_dashboard_widget","draft_profile_update","draft_trade_journal_note","draft_paper_order","draft_exit_order","draft_strategy_paper_review","draft_research_experiment","draft_research_decision","draft_risk_setting_change","draft_tiny_live_order_request","draft_shadow_live_report","draft_live_readiness_note"}
APPROVAL_TOOLS={"apply_strategy_change","apply_combo_change","toggle_strategy","toggle_combo","save_screener","update_watchlist","run_backtest","save_dashboard_layout","add_dashboard_widget","remove_dashboard_widget","update_profile","add_trade_journal_note","place_paper_order","exit_paper_position","edit_paper_journal","update_strategy_paper_status","cancel_paper_order","update_risk_setting","update_paper_risk_setting","reset_paper_account","save_research_experiment","approve_research_decision","reject_research_decision"}

class ToolRegistry:
    def __init__(self):
        self._tools={**{n:ToolDefinition(n,READ_ONLY) for n in READ_ONLY_TOOLS},**{n:ToolDefinition(n,DRAFT_ONLY) for n in DRAFT_TOOLS},**{n:ToolDefinition(n,APPROVAL_REQUIRED) for n in APPROVAL_TOOLS}}
    def get(self,name): assert_tool_allowed(name); return self._tools.get(name)
    def require(self,name):
        tool=self.get(name)
        if tool is None: raise ValueError(f"Unknown assistant tool: {name}")
        return tool
    def list(self): return [tool.to_dict() for tool in sorted(self._tools.values(),key=lambda item:item.name)]
    def is_forbidden(self,name): return name in FORBIDDEN_ACTIONS
