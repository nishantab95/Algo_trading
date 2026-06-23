from __future__ import annotations

import json,uuid
from datetime import datetime,timezone

from app.assistant.command_router import route_command
from app.assistant.context_builder import build_context
from app.assistant.guardrails import safe_refusal,unsafe_reason
from app.assistant.response_formatter import offline_response
from app.assistant.schemas import AssistantReply
from app.llm.errors import LLMError


MUTATING_INTENTS={"update_profile":"update_profile","strategy_change":"apply_strategy_change","combo_change":"apply_combo_change","run_backtest":"run_backtest","dashboard_create":"save_dashboard_layout","dashboard_modify":"add_dashboard_widget","paper_order_draft":"place_paper_order","paper_exit_draft":"exit_paper_position","paper_strategy_review":"update_strategy_paper_status","build_screener":"save_screener","watchlist_update":"update_watchlist"}

class AssistantService:
    def __init__(self,database,llm,rag,tools,drafts,profile,trade_history): self.database=database; self.llm=llm; self.rag=rag; self.tools=tools; self.drafts=drafts; self.profile=profile; self.trade_history=trade_history
    def status(self): return self.llm.status()
    def conversations(self): return self.database.query("SELECT * FROM assistant_conversations ORDER BY updated_at DESC")
    def conversation(self,conversation_id):
        rows=self.database.query("SELECT * FROM assistant_conversations WHERE id=?",(conversation_id,))
        if not rows: raise ValueError(f"Unknown conversation: {conversation_id}")
        return {**rows[0],"messages":self.database.query("SELECT * FROM assistant_messages WHERE conversation_id=? ORDER BY id",(conversation_id,))}
    def chat(self,message:str,conversation_id:str|None=None,action_payload:dict|None=None):
        conversation_id=conversation_id or self._conversation(message[:80] or "New conversation"); self._message(conversation_id,"user",message)
        intent=route_command(message); reason=unsafe_reason(message); context=self.rag.search(message,limit=8)
        draft=None; warnings=[]
        if reason: content=safe_refusal(reason)
        elif intent=="show_profile": content=json.dumps(self.profile.get(),indent=2)
        elif intent=="show_trade_history": content=json.dumps(self.trade_history.list(action_payload or {},limit=20),indent=2,default=str)
        elif intent in MUTATING_INTENTS:
            action=MUTATING_INTENTS[intent]; validation={"valid":bool(action_payload),"errors":[] if action_payload else ["A structured action payload is required"],"warnings":[]}
            draft=self.drafts.create(action,action_payload or {"request":message},conversation_id,validation); content="I prepared an action draft. Review its validation, risk check, and exact changes before approving it."
        elif intent in {"search_app","search_docs"}: content=json.dumps(context,indent=2,default=str)
        else:
            messages=[{"role":"user","content":f"Question: {message}\n\nRetrieved app context:\n{build_context(context)}"}]
            try: content=self.llm.chat(messages)
            except LLMError as exc: content=offline_response(context); warnings.append(str(exc))
        reply=AssistantReply(conversation_id,content,intent,context,draft,warnings); self._message(conversation_id,"assistant",content,[],context)
        return reply.to_dict()
    def _conversation(self,title):
        conversation_id="conv_"+uuid.uuid4().hex; now=datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as c: c.execute("INSERT INTO assistant_conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)",(conversation_id,title,now,now))
        return conversation_id
    def _message(self,conversation_id,role,content,tools=None,context=None):
        now=datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as c:
            c.execute("INSERT INTO assistant_messages(conversation_id,role,content,tool_calls_json,retrieved_context_json,created_at) VALUES(?,?,?,?,?,?)",(conversation_id,role,content,json.dumps(tools or []),json.dumps(context or [],default=str),now))
            c.execute("UPDATE assistant_conversations SET updated_at=? WHERE id=?",(now,conversation_id))
