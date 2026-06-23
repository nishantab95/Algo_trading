from __future__ import annotations
from dataclasses import asdict,dataclass,field
from typing import Any

@dataclass(frozen=True)
class ComboDefinition:
    combo_id:str
    name:str
    category:str
    description:str
    components:tuple[dict[str,Any],...]
    logic:dict[str,Any]
    entry:dict[str,Any]=field(default_factory=lambda:{"direction":"long"})
    exit:dict[str,Any]=field(default_factory=lambda:{"any":[{"stop_loss_pct":5},{"trailing_stop_pct":7}]})
    risk:dict[str,Any]=field(default_factory=lambda:{"max_holding_bars":30,"max_position_value_pct":10})
    explanation_template:str="{name}: {confirmations} confirmations passed."
    status:str="active"
    tags:tuple[str,...]=()
    enabled:bool=False
    unsupported_reason:str|None=None
    def to_dict(self): return asdict(self)
