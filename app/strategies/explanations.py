from __future__ import annotations

from app.strategies.schemas import CatalogStrategy


def explain_signal(strategy:CatalogStrategy,signal_value:int,indicator_values:dict,passed_rules:list[str]|None=None,failed_rules:list[str]|None=None,*,symbol:str|None=None,signal_time:str|None=None,passed_filters:list[str]|None=None,data_freshness_warning:str|None=None) -> dict:
    passed=passed_rules or []; failed=failed_rules or []
    values=", ".join(f"{key}={value:.3f}" if isinstance(value,(int,float)) else f"{key}={value}" for key,value in indicator_values.items()) or "no indicator snapshot"
    direction="long" if signal_value>0 else "short" if signal_value<0 else "neutral"
    filters=passed_filters or []
    explanation=(f"{strategy.name} produced a {direction} signal"
                 f" for {symbol or 'unspecified symbol'} at {signal_time or 'unspecified time'}. "
                 f"Passed rules: {', '.join(passed) or 'none recorded'}. "
                 f"Passed filters: {', '.join(filters) or 'none recorded'}. "
                 f"Failed filters: {', '.join(failed) or 'none'}. Indicator values: {values}. "
                 f"Exit plan: {strategy.exit}. Risk plan: {strategy.risk}.")
    return {"strategy_name":strategy.name,"category":strategy.category,"symbol":symbol,"signal_time":signal_time,"signal_direction":direction,"rules_passed":passed,"filters_passed":filters,"filters_failed":failed,"indicator_values":indicator_values,"entry_reason":strategy.description,"exit_plan":strategy.exit,"risk_warning":"Historical signal only; validate costs, liquidity, and regime stability.","data_freshness_warning":data_freshness_warning,"explanation":explanation}
