from pathlib import Path

from types import SimpleNamespace

import pytest

import main
from app.assistant.action_drafts import ActionDraftService
from app.assistant.guardrails import unsafe_reason
from app.assistant.tool_executor import ToolExecutor
from app.assistant.tool_registry import READ_ONLY_TOOLS, DRAFT_TOOLS, ToolRegistry
from app.assistant.tools.broker_safety_tools import BrokerSafetyTools
from app.assistant.tools.readonly_tools import ReadOnlyTools
from app.brokers.broker_errors import BrokerPermissionError
from app.brokers.broker_factory import BrokerFactory
from app.brokers.mock_broker import MockBroker
from app.db.database import Database
from app.live.kill_switch import KillSwitchService
from app.live.live_guard import LiveGuard
from app.live.live_risk import LiveRiskManager
from app.live.shadow_live_service import ShadowLiveService
from app.live.tiny_live_service import TinyLiveService
from app.live.unlock import TinyLiveUnlockService
from app.risk.manager import RiskManager
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.broker_service import BrokerService
from app.services.live_readiness_service import LiveReadinessService


class DummyProfile:
    def get(self): return {}


class DummyDashboards:
    def list(self): return []


class DummySearch:
    def search(self, *_args, **_kwargs): return []


class DummyRag:
    def search(self, *_args, **_kwargs): return []


def phrase() -> str:
    return " ".join(["I", "UNDERSTAND", "THIS", "CAN", "PLACE", "REAL", "ORDERS"])


def make_stack(tmp_path):
    database = Database(tmp_path / "stage7_batch6.sqlite3")
    database.initialize()
    mock = MockBroker("tiny_live", connected=True, funds={"available_cash": 10000.0}, quotes={"TCS": 100.0})
    factory = BrokerFactory(lambda _symbol: 100.0, database, RiskManager(database), mock_broker=mock, mock_quotes={"TCS": 100.0})
    broker = BrokerService(factory, initial_mode="tiny_live")

    def provider(_mode):
        return {"expected_cash": None, "local_live_orders": [], "local_live_positions": [], "local_live_trades": []}

    reconciliation = BrokerReconciliationService(database, broker, provider)
    kill = KillSwitchService(database)
    unlock = TinyLiveUnlockService(database, expected_phrase=phrase())
    guard = LiveGuard(reconciliation, kill)
    readiness = LiveReadinessService(database, broker, reconciliation, guard, kill, None, unlock)
    risk = LiveRiskManager(database, broker, reconciliation, readiness, unlock, kill)
    readiness.live_risk_manager = risk
    tiny = TinyLiveService(broker, unlock, risk, kill)
    shadow = ShadowLiveService(database, broker, risk)
    broker_safety = BrokerSafetyTools(broker, reconciliation, readiness, tiny, shadow, kill)
    readonly = ReadOnlyTools(database, DummyProfile(), DummyDashboards(), DummySearch(), DummyRag(), broker_safety=broker_safety)
    registry = ToolRegistry()
    drafts = ActionDraftService(database, {})
    executor = ToolExecutor(registry, readonly, drafts)
    return SimpleNamespace(db=database, mock=mock, broker=broker, reconciliation=reconciliation, kill=kill, unlock=unlock, readiness=readiness, risk=risk, tiny=tiny, shadow=shadow, broker_safety=broker_safety, readonly=readonly, registry=registry, drafts=drafts, executor=executor)


def test_01_assistant_can_read_broker_status(tmp_path):
    stack = make_stack(tmp_path)
    status = stack.executor.execute("get_broker_status")
    assert status["mode"] == "tiny_live"
    assert status["live_orders_allowed"] is False
    assert "get_broker_status" in READ_ONLY_TOOLS


def test_02_assistant_can_read_reconciliation_and_readiness(tmp_path):
    stack = make_stack(tmp_path)
    rec = stack.reconciliation.run_reconciliation("tiny_live")
    ready = stack.readiness.run_readiness("tiny_live")
    assert rec["status"] == "passed"
    assert stack.executor.execute("get_broker_reconciliation_latest")["reconciliation_id"] == rec["reconciliation_id"]
    assert stack.executor.execute("get_live_readiness")["run_id"] == ready["run_id"]


def test_03_assistant_can_explain_why_tiny_live_is_blocked(tmp_path):
    stack = make_stack(tmp_path)
    blockers = stack.executor.execute("explain_tiny_live_blockers")
    assert blockers["blocked"] is True
    assert "tiny_live_locked" in blockers["blockers"]
    assert "live_order_submission_disabled_by_policy" in blockers["blockers"]


def test_04_assistant_can_read_shadow_live_report(tmp_path):
    stack = make_stack(tmp_path)
    stack.shadow.run({"symbol": "TCS", "side": "BUY", "quantity": 1, "order_type": "market"})
    report = stack.executor.execute("get_shadow_live_report")
    assert report["total_events"] == 1
    assert report["live_order_submitted"] is False


def test_05_assistant_can_draft_tiny_live_order_request_but_not_execute_it(tmp_path):
    stack = make_stack(tmp_path)
    draft = stack.executor.execute("draft_tiny_live_order_request", {"symbol": "TCS", "side": "BUY", "quantity": 1})
    assert draft["action_type"] == "tiny_live_order_request"
    assert draft["status"] == "pending"
    assert draft["risk_check"]["approved"] is False
    with pytest.raises(PermissionError, match="risk check failed"):
        stack.drafts.approve(draft["id"], actor="user")
    assert stack.mock.place_order_called is False


def test_06_assistant_can_draft_shadow_report_and_readiness_note_only(tmp_path):
    stack = make_stack(tmp_path)
    shadow = stack.executor.execute("draft_shadow_live_report", {"summary": "prepare shadow report"})
    readiness = stack.executor.execute("draft_live_readiness_note", {"summary": "prepare readiness note"})
    assert shadow["action_type"] == "shadow_live_report_note"
    assert readiness["action_type"] == "live_readiness_note"
    assert shadow["risk_check"]["approved"] is False
    assert readiness["risk_check"]["approved"] is False
    assert {"draft_shadow_live_report", "draft_live_readiness_note"} <= DRAFT_TOOLS


def test_07_forbidden_live_safety_tools_are_blocked_by_registry(tmp_path):
    stack = make_stack(tmp_path)
    for tool in ["place_live_order", "approve_live_order", "unlock_tiny_live", "deactivate_kill_switch", "modify_broker_credentials", "bypass_reconciliation", "bypass_live_risk"]:
        with pytest.raises(PermissionError):
            stack.registry.get(tool)


def test_08_assistant_cannot_unlock_or_deactivate_direct_services(tmp_path):
    stack = make_stack(tmp_path)
    with pytest.raises(BrokerPermissionError):
        stack.unlock.unlock(phrase(), actor="assistant")
    with pytest.raises(BrokerPermissionError):
        stack.kill.deactivate(confirm=True, actor="assistant")


def test_09_assistant_cannot_approve_own_action(tmp_path):
    stack = make_stack(tmp_path)
    draft = stack.drafts.create("tiny_live_order_request", {"symbol": "TCS"})
    with pytest.raises(PermissionError, match="Only the user can approve"):
        stack.drafts.approve(draft["id"], actor="assistant")


def test_10_unsafe_live_phrases_are_blocked():
    phrases = [
        "please place a live order for TCS",
        "approve live order now",
        "unlock tiny-live for me",
        "deactivate kill switch",
        "modify broker credentials",
        "bypass reconciliation",
        "bypass risk check",
    ]
    for text in phrases:
        assert unsafe_reason(text) is not None


def test_11_assistant_tool_calls_do_not_call_broker_place_order(tmp_path):
    stack = make_stack(tmp_path)
    stack.executor.execute("get_broker_status")
    stack.executor.execute("get_tiny_live_status")
    stack.executor.execute("explain_tiny_live_blockers")
    stack.executor.execute("draft_tiny_live_order_request", {"symbol": "TCS", "side": "BUY", "quantity": 1})
    stack.executor.execute("draft_shadow_live_report", {"request": "summarize"})
    assert stack.mock.place_order_called is False


def test_12_assistant_tools_route_exposes_broker_safety_tools():
    app = main.create_flask_app()
    payload = app.test_client().get("/api/assistant/tools").get_json()
    names = {tool["name"] for tool in payload["data"]}
    assert {"get_broker_status", "get_live_readiness", "get_tiny_live_status", "get_shadow_live_report", "explain_tiny_live_blockers", "draft_tiny_live_order_request"} <= names
    assert {"place_live_order", "unlock_tiny_live", "deactivate_kill_switch"}.isdisjoint(names)


def test_13_no_assistant_tool_calls_real_zerodha_or_internet():
    source = Path(__file__).read_text(encoding="utf-8").lower()
    forbidden = ["kite" + "connect", "req" + "uests.", "urllib" + ".request", "http" + ".client"]
    assert all(item not in source for item in forbidden)
