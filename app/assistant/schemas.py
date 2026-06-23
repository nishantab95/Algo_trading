from __future__ import annotations

from dataclasses import asdict,dataclass,field
from typing import Any


@dataclass
class AssistantReply:
    conversation_id:str
    content:str
    intent:str
    retrieved_context:list[dict]=field(default_factory=list)
    action_draft:dict|None=None
    warnings:list[str]=field(default_factory=list)
    def to_dict(self): return asdict(self)

@dataclass
class ToolDefinition:
    name:str
    permission:str
    description:str=""
    def to_dict(self): return asdict(self)
