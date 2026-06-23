from __future__ import annotations
import numpy as np
import pandas as pd
from app.strategies.primitives.conditions import evaluate_primitive
from app.strategies.loader import generate_strategy_signals

def _combine(results:list[pd.Series],components:list[dict],logic:dict):
    frame=pd.concat(results,axis=1).fillna(False); mode=logic.get("mode","all")
    if mode=="all": return frame.all(axis=1)
    if mode=="any": return frame.any(axis=1)
    weights=np.array([float(item.get("weight",1)) for item in components]); scores=frame.astype(float).mul(weights,axis=1).sum(axis=1)
    if mode=="weighted_vote": return scores>=float(logic.get("threshold",weights.sum()/2))
    if mode=="min_confirmations": return frame.sum(axis=1)>=int(logic.get("threshold",logic.get("minimum",1)))
    if mode=="score_threshold": return scores>=float(logic.get("threshold",1))
    raise ValueError(f"Unsupported combo mode: {mode}")

def generate_combo_signals(data:pd.DataFrame,combo:dict,base_definitions:dict):
    frames=[]; combo_id=combo.get("combo_id") or combo.get("id")
    for symbol,group in data.groupby("Ticker",sort=False):
        frame=group.sort_values("Date").copy(); results=[]
        for component in combo["components"]:
            if component["type"]=="primitive": results.append(evaluate_primitive(frame,component["ref"],component.get("args",[])))
            elif component["type"]=="base_strategy":
                definition=base_definitions.get(component["ref"])
                if not definition: raise ValueError(f"Missing base strategy: {component['ref']}")
                generated=generate_strategy_signals(frame.assign(Ticker=symbol),definition); results.append(generated[definition.strategy_id].astype(bool).set_axis(frame.index))
            else: raise ValueError(f"Component requires unavailable contextual data: {component['type']}:{component['ref']}")
        accepted=_combine(results,combo["components"],combo["logic"]); direction=combo.get("entry",{}).get("direction","long")
        frame[combo_id]=np.where(accepted,-1 if direction=="short" else 1,0).astype(int); frames.append(frame)
    return pd.concat(frames,ignore_index=True).sort_values(["Date","Ticker"])
