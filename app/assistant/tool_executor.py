from __future__ import annotations

from app.assistant.permissions import APPROVAL_REQUIRED,DRAFT_ONLY,READ_ONLY


class ToolExecutor:
    def __init__(self,registry,readonly,drafts): self.registry=registry; self.readonly=readonly; self.drafts=drafts
    def execute(self,name,args=None,conversation_id=None):
        tool=self.registry.require(name); args=args or {}
        if tool.permission==READ_ONLY: return self.readonly.execute(name,args)
        if tool.permission==DRAFT_ONLY:
            action=name.removeprefix("draft_")
            return self.drafts.create(action,args,conversation_id)
        if tool.permission==APPROVAL_REQUIRED: raise PermissionError(f"{name} requires an approved persisted action draft")
        raise PermissionError(f"Tool permission denied: {name}")
