from __future__ import annotations

from app.assistant.guardrails import unsafe_reason

INTENTS=("question_answer","search_app","search_docs","show_profile","update_profile","explain_strategy","explain_combo","explain_signal","explain_backtest","show_trade_history","explain_trade","strategy_change","combo_change","build_combo","run_backtest","build_screener","watchlist_update","dashboard_create","dashboard_modify","paper_order_draft","paper_exit_draft","paper_strategy_review","risk_review","unsafe","unknown")

def route_command(text:str)->str:
    lower=text.lower()
    if unsafe_reason(text): return "unsafe"
    if any(x in lower for x in ("show my trading profile","risk settings am i using","favorite strategies")): return "show_profile"
    if "update" in lower and any(x in lower for x in ("profile","backtest period")): return "update_profile"
    if any(x in lower for x in ("trade history","losing trades","winning trades","trades for")): return "show_trade_history"
    if "explain" in lower and "backtest" in lower: return "explain_backtest"
    if "explain" in lower and "combo" in lower: return "explain_combo"
    if "explain" in lower and "strategy" in lower: return "explain_strategy"
    if "dashboard" in lower and any(x in lower for x in ("create","build")): return "dashboard_create"
    if "dashboard" in lower and any(x in lower for x in ("add","remove","modify")): return "dashboard_modify"
    if "draft" in lower and "strategy" in lower: return "strategy_change"
    if "draft" in lower and "combo" in lower: return "combo_change"
    if "backtest" in lower and any(x in lower for x in ("run","draft")): return "run_backtest"
    if "paper" in lower and "order" in lower: return "paper_order_draft"
    if any(x in lower for x in ("draft exit","exit paper position","close paper position")): return "paper_exit_draft"
    if "paper" in lower and any(x in lower for x in ("strategy review","promotion review","review strategy")): return "paper_strategy_review"
    if any(x in lower for x in ("search","find","show all")): return "search_app"
    if any(x in lower for x in ("readme","technical report","documentation")): return "search_docs"
    if text.strip(): return "question_answer"
    return "unknown"
