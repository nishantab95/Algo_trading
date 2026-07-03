from __future__ import annotations

from app.assistant.permissions import APPROVAL_REQUIRED,DRAFT_ONLY,READ_ONLY

DRAFT_ACTIONS={
    "draft_strategy_change":"apply_strategy_change",
    "draft_combo_change":"apply_combo_change",
    "draft_strategy_enable_disable":"toggle_strategy",
    "draft_screener_config":"save_screener",
    "draft_watchlist_update":"update_watchlist",
    "draft_backtest_request":"run_backtest",
    "draft_dashboard_layout":"save_dashboard_layout",
    "draft_dashboard_widget":"add_dashboard_widget",
    "draft_profile_update":"update_profile",
    "draft_trade_journal_note":"add_trade_journal_note",
    "draft_paper_order":"place_paper_order",
    "draft_exit_order":"exit_paper_position",
    "draft_strategy_paper_review":"update_strategy_paper_status",
    "draft_research_experiment":"save_research_experiment",
    "draft_research_decision":"approve_research_decision",
    "draft_risk_setting_change":"update_risk_setting",
    "draft_tiny_live_order_request":"tiny_live_order_request",
    "draft_shadow_live_report":"shadow_live_report_note",
    "draft_live_readiness_note":"live_readiness_note",
}

NON_EXECUTABLE_LIVE_DRAFTS={"draft_tiny_live_order_request","draft_shadow_live_report","draft_live_readiness_note"}


class ToolExecutor:
    def __init__(self,registry,readonly,drafts): self.registry=registry; self.readonly=readonly; self.drafts=drafts
    def execute(self,name,args=None,conversation_id=None):
        tool=self.registry.require(name); args=args or {}
        if tool.permission==READ_ONLY: return self.readonly.execute(name,args)
        if tool.permission==DRAFT_ONLY:
            action=DRAFT_ACTIONS[name]
            if name in NON_EXECUTABLE_LIVE_DRAFTS:
                risk={"approved":False,"reason":"Live-safety drafts are informational only and cannot be approved for execution by the assistant."}
                validation={"valid":True,"errors":[],"warnings":["Draft only; run the relevant user-controlled API/preflight outside assistant approval."]}
                return self.drafts.create(action,args,conversation_id,validation,risk)
            return self.drafts.create(action,args,conversation_id)
        if tool.permission==APPROVAL_REQUIRED: raise PermissionError(f"{name} requires an approved persisted action draft")
        raise PermissionError(f"Tool permission denied: {name}")
