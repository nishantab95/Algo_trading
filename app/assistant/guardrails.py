from __future__ import annotations

FORBIDDEN_ACTIONS={"direct_live_order","enable_live_trading","disable_risk_manager","delete_database","modify_broker_credentials","bypass_order_preview","bypass_risk_check","execute_without_approval","approve_own_action"}
UNSAFE_PHRASES=("buy this now without asking","use full capital","ignore risk manager","enable live trading","place live order","disable stop loss","delete all bad trades","change strategy silently","average down automatically","sure-shot","guaranteed profit")

def unsafe_reason(text:str)->str|None:
    lowered=text.lower()
    for phrase in UNSAFE_PHRASES:
        if phrase in lowered: return f"Unsafe request blocked: {phrase}"
    return None

def safe_refusal(reason:str)->str:
    return f"I cannot perform that action. {reason}. I can instead prepare a validation, backtest, dashboard draft, or risk-checked paper-order draft for your explicit approval."

def assert_tool_allowed(name:str):
    if name in FORBIDDEN_ACTIONS: raise PermissionError(f"Forbidden assistant tool: {name}")
