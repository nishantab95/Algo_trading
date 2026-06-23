from __future__ import annotations
from app.strategies.primitives.conditions import PRIMITIVES

MODES={"all","any","weighted_vote","min_confirmations","score_threshold"}
def validate_combo(combo:dict,base_ids:set[str]|None=None):
    errors=[]; warnings=[]; components=combo.get("components",[]); mode=combo.get("logic",{}).get("mode","all")
    if not components: errors.append("Combo requires at least one component")
    if mode not in MODES: errors.append(f"Unsupported combo logic: {mode}")
    for item in components:
        kind=item.get("type"); ref=item.get("ref")
        if kind=="primitive" and ref not in PRIMITIVES: errors.append(f"Unknown primitive: {ref}")
        elif kind=="base_strategy" and base_ids is not None and ref not in base_ids: errors.append(f"Missing base strategy component: {ref}")
        elif kind not in {"primitive","base_strategy","market_filter","sector_filter","volatility_filter","risk_filter"}: errors.append(f"Unsupported component type: {kind}")
        elif kind in {"market_filter","sector_filter"}: warnings.append(f"{kind} requires contextual dataset: {ref}")
    status="active" if not errors and not warnings else "needs_data" if warnings and not errors else "disabled"
    return {"valid":not errors and not warnings,"status":status,"warnings":warnings,"errors":errors}
