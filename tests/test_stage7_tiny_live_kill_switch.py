
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

import main
from app.brokers.broker_errors import BrokerPermissionError
from app.brokers.broker_factory import BrokerFactory
from app.brokers.mock_broker import MockBroker
from app.db.database import Database
from app.live.kill_switch import KILL_SWITCH_ARMED, KILL_SWITCH_DISABLED_FOR_LIVE_USE, KILL_SWITCH_TRIGGERED, KillSwitchService
from app.live.live_guard import LiveGuard
from app.live.live_risk import DEFAULT_TINY_LIVE_LIMITS, REQUIRED_RISK_CHECKS, LiveRiskManager
from app.live.tiny_live_service import TinyLiveService
from app.live.unlock import TinyLiveUnlockService
from app.risk.manager import RiskManager
from app.routes.live_routes import create_live_blueprint
from app.routes.tiny_live_routes import create_tiny_live_blueprint
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.broker_service import BrokerService
from app.services.live_readiness_service import LiveReadinessService


def exact_phrase() -> str:
    return " ".join(["I", "UNDERSTAND", "THIS", "CAN", "PLACE", "REAL", "ORDERS"])


def make_stack(tmp_path, mode="tiny_live", mock=None, funds=None, timeout_seconds=600):
    database = Database(tmp_path / "stage7_batch4.sqlite3")
    database.initialize()
    mock = mock or MockBroker(
        mode,
        connected=True,
        funds=funds or {"available_cash": 10000.0, "currency": "INR"},
        quotes={"TCS": 100.0},
    )
    factory = BrokerFactory(lambda _symbol: 100.0, database, RiskManager(database), mock_broker=mock, mock_quotes={"TCS": 100.0})
    broker = BrokerService(factory, initial_mode=mode)

    def provider(_mode):
        return {"expected_cash": None, "local_live_orders": [], "local_live_positions": [], "local_live_trades": []}

    reconciliation = BrokerReconciliationService(database, broker, provider)
    kill_switch = KillSwitchService(database)
    unlock = TinyLiveUnlockService(database, expected_phrase=exact_phrase(), timeout_seconds=timeout_seconds)
    guard = LiveGuard(reconciliation, kill_switch)
    readiness = LiveReadinessService(database, broker, reconciliation, guard, kill_switch, None, unlock)
    risk = LiveRiskManager(database, broker, reconciliation, readiness, unlock, kill_switch)
    readiness.live_risk_manager = risk
    tiny_live = TinyLiveService(broker, unlock, risk, kill_switch)
    return SimpleNamespace(db=database, mock=mock, broker=broker, reconciliation=reconciliation, kill=kill_switch, unlock=unlock, guard=guard, readiness=readiness, risk=risk, tiny=tiny_live)


def valid_order(**overrides):
    payload = {
        "symbol": "TCS",
        "side": "BUY",
        "quantity": 5,
        "price": 100.0,
        "order_type": "market",
        "product_type": "CNC",
        "exchange": "NSE",
        "approved_by_user": True,
        "approved_by_actor": "user",
    }
    payload.update(overrides)
    return payload


def prepare_ready(stack):
    reconciliation = stack.reconciliation.run_reconciliation("tiny_live")
    readiness = stack.readiness.run_readiness("tiny_live")
    unlock = stack.unlock.unlock(exact_phrase(), actor="user")
    assert reconciliation["status"] == "passed"
    assert readiness["critical_failures"] == []
    assert unlock["unlocked"] is True


def rejected_checks(result):
    return {check["check"] for check in result["checks"] if check["status"] == "fail"}


def test_01_tiny_live_locked_by_default_and_limits_created(tmp_path):
    stack = make_stack(tmp_path)
    status = stack.tiny.status()
    assert status["unlock"]["locked"] is True
    assert status["live_orders_allowed"] is False
    assert status["can_submit_live_order"] is False
    assert status["limits"]["max_order_value"] == DEFAULT_TINY_LIVE_LIMITS["max_order_value"]
    assert stack.kill.status()["state"] == KILL_SWITCH_ARMED


def test_02_exact_phrase_works_wrong_and_case_different_fail_and_raw_phrase_not_stored(tmp_path):
    stack = make_stack(tmp_path)
    with pytest.raises(BrokerPermissionError, match="did not match exactly"):
        stack.unlock.unlock(exact_phrase().lower(), actor="user")
    result = stack.unlock.unlock(exact_phrase(), actor="user")
    assert result["unlocked"] is True
    rows = stack.db.query("SELECT * FROM tiny_live_unlocks ORDER BY id")
    assert any(row["failure_reason"] == "phrase_mismatch" for row in rows)
    assert exact_phrase() not in str(rows)
    assert all(row.get("phrase_hash") != exact_phrase() for row in rows)


def test_03_unlock_expires_and_preflight_fails_closed(tmp_path):
    stack = make_stack(tmp_path, timeout_seconds=-1)
    stack.reconciliation.run_reconciliation("tiny_live")
    stack.readiness.run_readiness("tiny_live")
    result = stack.unlock.unlock(exact_phrase(), actor="user")
    assert result["locked"] is True
    preflight = stack.risk.preflight_order(valid_order())
    assert preflight["approved"] is False
    assert {"unlock_required", "unlock_not_expired"} <= rejected_checks(preflight)
    assert stack.mock.place_order_called is False


def test_04_assistant_cannot_unlock_approve_or_deactivate_kill_switch(tmp_path):
    stack = make_stack(tmp_path)
    with pytest.raises(BrokerPermissionError, match="Assistant cannot unlock"):
        stack.unlock.unlock(exact_phrase(), actor="assistant")
    with pytest.raises(BrokerPermissionError, match="Assistant cannot deactivate"):
        stack.kill.deactivate(confirm=True, actor="assistant")
    prepare_ready(stack)
    result = stack.risk.preflight_order(valid_order(actor="assistant", approved_by_actor="assistant"), actor="assistant")
    assert result["approved"] is False
    assert "assistant_cannot_approve" in rejected_checks(result)
    assert stack.mock.place_order_called is False


def test_05_manual_lock_relocks_tiny_live(tmp_path):
    stack = make_stack(tmp_path)
    stack.unlock.unlock(exact_phrase(), actor="user")
    result = stack.unlock.lock(actor="user")
    assert result["locked"] is True
    rows = stack.db.query("SELECT status FROM tiny_live_unlocks ORDER BY id DESC LIMIT 1")
    assert rows[0]["status"] == "locked"


def test_06_locked_preflight_rejects_without_calling_broker_place_order(tmp_path):
    stack = make_stack(tmp_path)
    stack.reconciliation.run_reconciliation("tiny_live")
    stack.readiness.run_readiness("tiny_live")
    result = stack.risk.preflight_order(valid_order())
    assert result["status"] == "rejected"
    assert "unlock_required" in rejected_checks(result)
    assert result["live_order_submitted"] is False
    assert result["broker_place_order_called"] is False
    assert stack.mock.place_order_called is False


def test_07_reconciliation_or_readiness_failure_blocks_preflight(tmp_path):
    stack = make_stack(tmp_path)
    stack.readiness.run_readiness("tiny_live")
    stack.unlock.unlock(exact_phrase(), actor="user")
    result = stack.risk.preflight_order(valid_order())
    failures = rejected_checks(result)
    assert "reconciliation_passing" in failures
    assert "readiness_not_critical_fail" in failures
    assert stack.mock.place_order_called is False


def test_08_kill_switch_trigger_blocks_and_persists(tmp_path):
    stack = make_stack(tmp_path)
    prepare_ready(stack)
    status = stack.kill.trigger("test_trigger", actor="user")
    assert status["state"] == KILL_SWITCH_TRIGGERED
    result = stack.risk.preflight_order(valid_order())
    assert result["approved"] is False
    assert "kill_switch_armed_not_triggered" in rejected_checks(result)
    rows = stack.db.query("SELECT state, reason FROM live_kill_switch ORDER BY id DESC LIMIT 1")
    assert rows[0]["state"] == KILL_SWITCH_TRIGGERED and rows[0]["reason"] == "test_trigger"


def test_09_kill_switch_deactivation_requires_confirmation_and_still_blocks_live_use(tmp_path):
    stack = make_stack(tmp_path)
    with pytest.raises(BrokerPermissionError, match="explicit confirmation"):
        stack.kill.deactivate(confirm=False, actor="user")
    status = stack.kill.deactivate(confirm=True, actor="user")
    assert status["state"] == KILL_SWITCH_DISABLED_FOR_LIVE_USE
    assert status["blocks_live_actions"] is True


def test_10_limits_reject_oversized_and_invalid_orders(tmp_path):
    stack = make_stack(tmp_path)
    prepare_ready(stack)
    oversized = stack.risk.preflight_order(valid_order(quantity=11, price=100.0))
    assert oversized["approved"] is False
    assert "max_order_value" in rejected_checks(oversized)

    invalid = stack.risk.preflight_order(
        valid_order(exchange="BSE", product_type="MIS", order_type="stop", side="SELL", asset_class="FUT", leverage=True)
    )
    failures = rejected_checks(invalid)
    assert {"allowed_exchange", "allowed_product_type", "allowed_order_type", "no_intraday", "no_short_selling", "no_derivatives", "no_leverage"} <= failures
    assert stack.mock.place_order_called is False


def test_11_daily_limits_block_third_tiny_live_preflight(tmp_path):
    stack = make_stack(tmp_path)
    prepare_ready(stack)
    first = stack.risk.preflight_order(valid_order(quantity=9, price=100.0))
    second = stack.risk.preflight_order(valid_order(quantity=9, price=100.0))
    third = stack.risk.preflight_order(valid_order(quantity=9, price=100.0))
    assert first["approved"] is True
    assert second["approved"] is True
    assert third["approved"] is False
    assert {"max_daily_order_value", "max_orders_per_day"} <= rejected_checks(third)
    assert len(stack.db.query("SELECT * FROM live_risk_events WHERE status='approved'")) == 2


def test_12_low_cash_blocks_preflight(tmp_path):
    stack = make_stack(tmp_path, funds={"available_cash": 50.0, "currency": "INR"})
    prepare_ready(stack)
    result = stack.risk.preflight_order(valid_order(quantity=5, price=100.0))
    assert result["approved"] is False
    assert "cash_available" in rejected_checks(result)


def test_13_preflight_includes_all_required_checks_and_never_submits_live_order(tmp_path):
    stack = make_stack(tmp_path)
    prepare_ready(stack)
    result = stack.risk.preflight_order(valid_order())
    check_names = {check["check"] for check in result["checks"]}
    assert set(REQUIRED_RISK_CHECKS) <= check_names
    assert result["approved"] is True
    assert result["live_order_submitted"] is False
    assert result["broker_place_order_called"] is False
    assert stack.mock.place_order_called is False


def test_14_api_envelopes_for_tiny_live_and_kill_switch(tmp_path):
    stack = make_stack(tmp_path)
    app = Flask(__name__)
    app.register_blueprint(create_tiny_live_blueprint(stack.tiny))
    app.register_blueprint(create_live_blueprint(stack.readiness, stack.kill))
    client = app.test_client()

    assert client.get("/api/tiny-live/status").get_json()["success"] is True
    assert client.get("/api/tiny-live/limits").get_json()["data"]["max_orders_per_day"] == 2
    assert client.get("/api/live/kill-switch").get_json()["data"]["state"] == KILL_SWITCH_ARMED

    unlock = client.post("/api/tiny-live/unlock", json={"phrase": exact_phrase(), "actor": "user"}).get_json()
    assert unlock["success"] is True
    preflight = client.post("/api/tiny-live/order/preflight", json=valid_order()).get_json()
    assert preflight["success"] is True
    assert preflight["data"]["live_order_submitted"] is False

    response = client.post("/api/live/kill-switch/deactivate", json={"confirm": False, "actor": "user"})
    assert response.status_code == 403
    assert response.get_json()["success"] is False


def test_15_database_migration_batch4_tables_are_idempotent(tmp_path):
    database = Database(tmp_path / "batch4_migration.sqlite3")
    database.initialize(); database.initialize()
    tables = {row["name"] for row in database.query("SELECT name FROM sqlite_master WHERE type='table'")}
    versions = [row["version"] for row in database.query("SELECT version FROM schema_version ORDER BY version")]
    assert versions[-1] == 11
    assert {"tiny_live_unlocks", "live_kill_switch", "live_risk_events", "tiny_live_limits"} <= tables


def test_16_composed_app_exposes_batch4_routes_but_no_live_submit_route():
    app = main.create_flask_app()
    routes = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/tiny-live/status" in routes
    assert "/api/tiny-live/order/preflight" in routes
    assert "/api/live/kill-switch" in routes
    assert "/api/live/order/submit" not in routes
    assert not any("live/order" in route and "submit" in route for route in routes)


def test_17_no_test_calls_real_zerodha_or_internet():
    source = Path(__file__).read_text(encoding="utf-8").lower()
    forbidden = ["kite" + "connect", "req" + "uests.", "urllib" + ".request", "http" + ".client"]
    assert all(item not in source for item in forbidden)
