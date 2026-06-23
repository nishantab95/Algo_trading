from __future__ import annotations

from app.strategies.primitives.conditions import PRIMITIVES
from app.strategies.schemas import CatalogStrategy, ValidationResult

DERIVABLE_PREFIXES=("SMA_","EMA_","ROC_","ROLLING_HIGH_","ROLLING_LOW_")
DERIVABLE_NAMES={"PRICE_ZSCORE_20","RANGE_PCT","BODY_PCT","GAP_PCT"}


def _primitive_names(node) -> list[str]:
    if not node: return []
    if isinstance(node,list): return sum((_primitive_names(x) for x in node),[])
    if "primitive" in node: return [node["primitive"]]
    names=[]
    for value in node.values():
        if isinstance(value,(dict,list)): names.extend(_primitive_names(value))
    if len(node)==1:
        key=next(iter(node));
        if key not in {"all","any","not","weighted_vote","min_confirmations","score_threshold","rules","rule"}: names.append(key)
    return names


def validate_strategy(strategy:CatalogStrategy,available_columns:set[str]|None=None,backtest_mode:str|None=None) -> ValidationResult:
    errors=[]; warnings=[]; available=available_columns or set()
    if not strategy.strategy_id or not strategy.entry: errors.append("strategy_id and entry rules are required")
    if strategy.direction not in {"long","short","long_short","portfolio","simulation_only"}: errors.append(f"Unsupported direction: {strategy.direction}")
    if not strategy.exit: warnings.append("No explicit exit configuration; Stage 2 defaults will be used")
    unknown=sorted(set(_primitive_names(strategy.entry)+_primitive_names(strategy.filters))-set(PRIMITIVES))
    if unknown: errors.append(f"Unknown primitives: {', '.join(unknown)}")
    if strategy.timeframe != "daily": errors.append(f"{strategy.name} requires {strategy.timeframe} data; only daily data is available")
    if strategy.asset_class == "options_simulation": warnings.append("Options strategy is simulation-only until F&O data is available")
    missing=[]
    for column in strategy.data_requirements.get("required_columns",[]):
        if available and column not in available and not column.startswith(DERIVABLE_PREFIXES) and column not in DERIVABLE_NAMES: missing.append(column)
    if missing: errors.append(f"Missing required columns: {', '.join(missing)}")
    if backtest_mode=="long_only" and strategy.direction=="short": errors.append("Short-only strategy cannot run in long-only mode")
    status=strategy.status
    if strategy.asset_class=="options_simulation": status="simulation_only"
    elif strategy.timeframe!="daily": status="needs_intraday_data"
    elif errors and any("Missing required columns" in e for e in errors): status="needs_data"
    elif errors and status=="active": status="disabled"
    if not errors: warnings.append("Referenced primitives are causal/audited; execution delay is owned by Stage 2")
    return ValidationResult(not errors and status=="active",status,tuple(warnings),tuple(errors or ([strategy.unsupported_reason] if strategy.unsupported_reason and status!="active" else [])))
