from __future__ import annotations

from dataclasses import dataclass,field,asdict

EXPERIMENT_STATUSES={"draft","queued","running","completed","failed","cancelled","archived"}
DECISIONS={"reject","needs_more_data","continue_research","paper_test_candidate","tiny_live_candidate_later"}

@dataclass
class ExperimentConfig:
    name:str
    strategy_id:str|None=None
    combo_id:str|None=None
    description:str=""
    universe:str="custom"
    symbols:list[str]=field(default_factory=list)
    start_date:str|None=None
    end_date:str|None=None
    train_start:str|None=None
    train_end:str|None=None
    test_start:str|None=None
    test_end:str|None=None
    execution_model:str="next_open"
    cost_model:str="india_equity_delivery_approx"
    slippage_bps:float=7
    spread_bps:float=5
    fees_enabled:bool=True
    initial_capital:float=1_000_000
    max_positions:int=10
    sizing_model:str="risk_percent"
    risk_settings:dict=field(default_factory=dict)
    parameter_grid:dict|list=field(default_factory=dict)
    validation_config:dict=field(default_factory=dict)
    def to_dict(self):return asdict(self)
