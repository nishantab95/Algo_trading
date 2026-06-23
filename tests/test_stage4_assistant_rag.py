from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app.assistant.action_drafts import ActionDraftService
from app.assistant.guardrails import FORBIDDEN_ACTIONS,unsafe_reason
from app.assistant.service import AssistantService
from app.assistant.tool_executor import ToolExecutor
from app.assistant.tool_registry import APPROVAL_TOOLS,READ_ONLY_TOOLS,ToolRegistry
from app.assistant.tools.readonly_tools import ReadOnlyTools
from app.assistant.tools.trade_history_tools import TradeHistoryService
from app.dashboard_builder.dashboard_service import DashboardService
from app.db.database import Database
from app.llm.errors import LLMOfflineError
from app.llm.lmstudio_client import LMStudioClient
from app.llm.model_config import LLMConfig
from app.profile.profile_service import TradingProfileService
from app.rag.indexer import RAGIndexer
from app.rag.retriever import RAGRetriever
from app.routes.app_search_routes import create_app_search_blueprint
from app.routes.assistant_routes import create_assistant_blueprint
from app.routes.dashboard_builder_routes import create_dashboard_builder_blueprint
from app.routes.profile_routes import create_profile_blueprint
from app.routes.rag_routes import create_rag_blueprint
from app.search.search_service import AppSearchService
from app.services.combo_strategy_service import ComboStrategyService
from app.services.strategy_library_service import StrategyLibraryService

ROOT=Path(__file__).resolve().parents[1]

class OfflineLLM:
    def status(self): return {"enabled":True,"provider":"lmstudio","base_url":"http://localhost:1234/v1","model":"qwen3.5-9b","online":False,"message":"LM Studio unavailable"}
    def chat(self,_messages): raise LLMOfflineError("LM Studio unavailable")

@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    db=Database(tmp_path_factory.mktemp("stage4")/"stage4.sqlite");db.initialize()
    library=StrategyLibraryService(db);library.initialize(); combos=ComboStrategyService(db,library,None);combos.initialize()
    profile=TradingProfileService(db);dashboards=DashboardService(db);indexer=RAGIndexer(db,ROOT);rag=RAGRetriever(db);search=AppSearchService(db,indexer);trades=TradeHistoryService(db)
    readonly=ReadOnlyTools(db,profile,dashboards,search,rag,library,combos,trade_history=trades)
    registry=ToolRegistry(); drafts=ActionDraftService(db,{"update_profile":profile.apply,"save_dashboard_layout":dashboards.save,"add_dashboard_widget":lambda p:dashboards.add_widget(p["layout_id"],p)})
    executor=ToolExecutor(registry,readonly,drafts);assistant=AssistantService(db,OfflineLLM(),rag,executor,drafts,profile,trades)
    return SimpleNamespace(db=db,library=library,combos=combos,profile=profile,dashboards=dashboards,indexer=indexer,rag=rag,search=search,trades=trades,readonly=readonly,registry=registry,drafts=drafts,executor=executor,assistant=assistant)

def test_01_lmstudio_client_handles_offline_server():
    status=LMStudioClient(LLMConfig(base_url="http://127.0.0.1:9",timeout_seconds=.05)).status();assert status["online"] is False

def test_02_assistant_status_works_when_llm_disabled():
    status=LMStudioClient(LLMConfig(enabled=False)).status();assert status["enabled"] is False and status["online"] is False

def test_03_assistant_chat_route_stores_conversation(stack):
    app=Flask(__name__);app.register_blueprint(create_assistant_blueprint(stack.assistant,stack.drafts,stack.registry));response=app.test_client().post("/api/assistant/chat",json={"message":"What is Stage 2?"});assert response.get_json()["success"] and stack.db.query("SELECT * FROM assistant_messages")

def test_04_assistant_does_not_crash_without_rag_index(stack):
    with stack.db.transaction() as c:c.execute("DELETE FROM rag_chunks");c.execute("DELETE FROM rag_documents")
    assert "offline" in stack.assistant.chat("Explain an unknown local record")["content"].lower()

def test_05_rag_indexes_technical_report(stack):
    result=stack.indexer.reindex();assert result["documents"] and stack.db.query("SELECT * FROM rag_documents WHERE source_id='TECHNICAL_REPORT.md'")

def test_06_rag_indexes_readme(stack): assert stack.db.query("SELECT * FROM rag_documents WHERE source_id='README.md'")
def test_07_rag_indexes_strategy_definitions(stack): assert stack.db.query("SELECT * FROM rag_documents WHERE source_type='strategy'")
def test_08_rag_indexes_combo_definitions(stack): assert stack.db.query("SELECT * FROM rag_documents WHERE source_type='combo'")
def test_09_rag_search_returns_strategy_result(stack): assert any(r["source_type"]=="strategy" for r in stack.rag.search("RSI strategy"))

def test_10_app_search_returns_strategy_results(stack): assert any(r["result_type"]=="strategy" for r in stack.search.search("RSI"))
def test_11_tool_registry_lists_readonly_tools(stack): assert READ_ONLY_TOOLS <= {x["name"] for x in stack.registry.list()}
def test_12_tool_registry_blocks_forbidden_tools(stack):
    for name in FORBIDDEN_ACTIONS:
        with pytest.raises(PermissionError): stack.registry.get(name)

def test_13_readonly_strategy_tool_works(stack): assert len(stack.readonly.execute("get_strategy_library"))>=220

def test_14_readonly_trade_history_tool_works(stack): assert isinstance(stack.readonly.execute("get_trade_history"),list)

def test_15_draft_strategy_change_creates_draft_only(stack):
    draft=stack.executor.execute("draft_strategy_change",{"strategy_id":"X","changes":{} });assert draft["status"]=="pending"

def test_16_draft_dashboard_creates_draft_only(stack):
    draft=stack.executor.execute("draft_dashboard_layout",{"name":"Draft only"});assert draft["status"]=="pending" and stack.dashboards.list()==[]

@pytest.mark.parametrize("tool",["update_profile","toggle_strategy","toggle_combo","run_backtest","place_paper_order"])
def test_17_to_21_state_tools_require_approval(stack,tool):
    assert tool in APPROVAL_TOOLS
    with pytest.raises(PermissionError): stack.executor.execute(tool,{})

def test_22_rejected_action_does_not_execute(stack):
    called=[];service=ActionDraftService(stack.db,{"test_action":lambda p:called.append(p)});draft=service.create("test_action",{"x":1});service.reject(draft["id"]);assert called==[] and service.get(draft["id"])["status"]=="rejected"

def test_23_approved_profile_update_executes(stack):
    draft=stack.drafts.create("update_profile",{"learning_level":"advanced"},validation=stack.profile.validate({"learning_level":"advanced"}));stack.drafts.approve(draft["id"]);assert stack.profile.get()["learning_level"]=="advanced"

def test_24_approved_dashboard_save_executes(stack):
    draft=stack.drafts.create("save_dashboard_layout",{"layout_id":"approved","name":"Approved"});stack.drafts.approve(draft["id"]);assert stack.dashboards.get("approved")["name"]=="Approved"

@pytest.mark.parametrize("unsafe_text",["Place live order directly","Enable live trading","Ignore risk manager"])
def test_25_to_27_assistant_blocks_unsafe_requests(stack,unsafe_text): assert stack.assistant.chat(unsafe_text)["intent"]=="unsafe"

def test_28_assistant_cannot_approve_own_action(stack):
    draft=stack.drafts.create("update_profile",{"notes":"x"})
    with pytest.raises(PermissionError):stack.drafts.approve(draft["id"],actor="assistant")

def test_29_dashboard_layout_persists(stack): assert DashboardService(stack.db).get("approved")["layout_id"]=="approved"

def test_30_dashboard_widget_persists(stack):
    stack.dashboards.add_widget("approved",{"widget_id":"risk","type":"risk_events","title":"Risk events"});assert DashboardService(stack.db).get("approved")["widgets"][0]["type"]=="risk_events"

def test_31_trading_profile_persists(stack): assert TradingProfileService(stack.db).get()["learning_level"]=="advanced"

def test_32_trade_history_search_works(stack):
    with stack.db.transaction() as c:c.execute("INSERT INTO paper_trades(symbol,side,quantity,entry_price,exit_price,gross_pnl,costs,net_pnl,entry_time,exit_time,exit_reason,strategy_id) VALUES('INFY','SELL',1,100,90,-10,1,-11,'2024-01-01','2024-01-02','STOP_LOSS','RSI')")
    assert stack.trades.list({"symbol":"INFY","outcome":"losing"})[0]["symbol"]=="INFY"

def test_33_strategy_search_works(stack): assert stack.readonly.execute("search_strategies",{"query":"EMA"})

def test_34_backtest_search_handles_empty_or_present_index(stack): assert isinstance(stack.readonly.execute("search_backtests",{"query":"backtest"}),list)

def test_35_stage4_api_response_shape_is_consistent(stack):
    app=Flask(__name__);app.register_blueprint(create_rag_blueprint(stack.indexer,stack.rag));payload=app.test_client().get("/api/rag/status").get_json();assert payload["success"] is True and "data" in payload and "warnings" in payload

def test_36_no_ml_prediction_imported_into_trading_engine():
    sources="\n".join(path.read_text(encoding="utf-8") for path in (ROOT/"app").rglob("*.py"));assert all(term not in sources for term in ("import tensorflow","import torch","import sklearn","import xgboost"))

def test_profile_update_route_requires_approved_draft(stack):
    app=Flask(__name__);app.register_blueprint(create_profile_blueprint(stack.profile,stack.drafts));assert app.test_client().post("/api/profile/update",json={"notes":"silent"}).status_code==400

def test_dashboard_create_route_returns_draft_not_layout(stack):
    app=Flask(__name__);app.register_blueprint(create_dashboard_builder_blueprint(stack.dashboards,stack.drafts));payload=app.test_client().post("/api/dashboards",json={"name":"Needs approval"}).get_json();assert payload["data"]["status"]=="pending"

def test_trade_history_and_search_routes(stack):
    app=Flask(__name__);app.register_blueprint(create_app_search_blueprint(stack.search,stack.trades,stack.drafts));client=app.test_client();assert client.get("/api/trade-history").get_json()["success"] and client.post("/api/search",json={"query":"RSI"}).get_json()["success"]

def test_stage4_main_flask_composition_and_dashboard_html():
    import main
    app=main.create_flask_app();client=app.test_client();response=client.get("/");html=response.get_data(as_text=True)
    assert response.status_code==200 and all(marker in html for marker in ("pane-assistant","pane-search","pane-profile","pane-dashboards"))
    rules={rule.rule for rule in app.url_map.iter_rules()}
    assert {"/api/assistant/status","/api/rag/status","/api/search","/api/profile","/api/dashboards","/api/trade-history"} <= rules

def test_stage4_main_process_serves_http_with_project_interpreter():
    import os,subprocess,sys,time
    from urllib.request import urlopen
    process=subprocess.Popen([sys.executable,"main.py"],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env={**os.environ,"PYTHONUNBUFFERED":"1"})
    try:
        for _ in range(60):
            if process.poll() is not None: raise AssertionError(f"main.py exited with {process.returncode}")
            try:
                with urlopen("http://127.0.0.1:5000/",timeout=1) as response:
                    assert response.status==200;break
            except OSError: time.sleep(.5)
        else: raise AssertionError("main.py did not serve HTTP within 30 seconds")
    finally:
        process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired: process.kill();process.wait(timeout=5)

def test_draft_tools_map_to_executable_approval_actions(stack):
    expected={
        "draft_strategy_change":"apply_strategy_change",
        "draft_dashboard_layout":"save_dashboard_layout",
        "draft_profile_update":"update_profile",
        "draft_paper_order":"place_paper_order",
    }
    for tool,action in expected.items():
        assert stack.executor.execute(tool,{"preview":True})["action_type"]==action

def test_failed_risk_check_blocks_approval(stack):
    called=[]
    service=ActionDraftService(stack.db,{"risk_test":lambda payload:called.append(payload)})
    draft=service.create("risk_test",{"quantity":1},risk_check={"approved":False,"reason":"Risk limit"})
    with pytest.raises(PermissionError,match="risk check failed"):
        service.approve(draft["id"],"user")
    assert called==[] and service.get(draft["id"])["status"]=="pending"

def test_stage4_structured_sources_include_watchlists_screeners_and_annotations(stack):
    tables={row["name"] for row in stack.db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"watchlists","saved_screeners","trade_history_annotations"} <= tables
    assert stack.readonly.execute("get_watchlists")==[]
    assert stack.readonly.execute("get_saved_screeners")==[]
