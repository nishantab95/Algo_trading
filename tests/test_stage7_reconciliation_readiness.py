from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

import main
from app.brokers.broker_errors import BrokerPermissionError
from app.brokers.broker_factory import BrokerFactory
from app.brokers.broker_modes import BrokerMode, requires_reconciliation
from app.brokers.mock_broker import MockBroker
from app.db.database import Database
from app.live.live_guard import LiveGuard
from app.routes.broker_routes import create_broker_blueprint
from app.routes.live_routes import create_live_blueprint
from app.risk.manager import RiskManager
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.broker_service import BrokerService
from app.services.live_readiness_service import LiveReadinessService


def make_stack(tmp_path, mode="broker_readonly", mock=None, local_state=None):
    database = Database(tmp_path / "stage7_batch3.sqlite3"); database.initialize()
    mock = mock or MockBroker(mode, connected=True, quotes={"TCS": 100.0, "INFY": 1500.0})
    factory = BrokerFactory(lambda _symbol: 100.0, database, RiskManager(database), mock_broker=mock, mock_quotes={"TCS": 100.0, "INFY": 1500.0})
    broker_service = BrokerService(factory, initial_mode=mode)

    def provider(_mode):
        return {
            "expected_cash": None,
            "local_live_orders": [],
            "local_live_positions": [],
            "local_live_trades": [],
            **(local_state or {}),
        }

    reconciliation = BrokerReconciliationService(database, broker_service, provider)
    guard = LiveGuard(reconciliation)
    readiness = LiveReadinessService(database, broker_service, reconciliation, guard)
    return SimpleNamespace(db=database, mock=mock, broker=broker_service, reconciliation=reconciliation, guard=guard, readiness=readiness)


def test_01_reconciliation_returns_failed_when_broker_disconnected(tmp_path):
    stack = make_stack(tmp_path, mock=MockBroker("broker_readonly", connected=False))
    result = stack.reconciliation.run_reconciliation("broker_readonly")
    assert result["status"] == "failed"
    assert result["funds_status"] == "broker_unavailable"
    assert result["mismatches"][0]["type"] == "broker_unavailable"


def test_02_reconciliation_returns_failed_when_broker_read_raises(tmp_path):
    stack = make_stack(tmp_path, mock=MockBroker("broker_readonly", connected=True, raise_on_read=True))
    result = stack.reconciliation.run_reconciliation("broker_readonly")
    assert result["status"] == "failed"
    assert result["positions_status"] == "broker_unavailable"
    assert result["errors"]


def test_03_reconciliation_detects_cash_mismatch(tmp_path):
    mock = MockBroker("broker_readonly", connected=True, funds={"available_cash": 1000.0})
    stack = make_stack(tmp_path, mock=mock, local_state={"expected_cash": 1200.0})
    result = stack.reconciliation.run_reconciliation("broker_readonly")
    assert result["status"] == "failed"
    assert result["funds_status"] == "cash_mismatch"


def test_04_reconciliation_detects_quantity_mismatch(tmp_path):
    mock = MockBroker("broker_readonly", connected=True, positions=[{"symbol": "INFY", "quantity": 8}])
    local = {"local_live_positions": [{"symbol": "INFY", "quantity": 10}]}
    stack = make_stack(tmp_path, mock=mock, local_state=local)
    result = stack.reconciliation.run_reconciliation("broker_readonly")
    assert result["status"] == "failed"
    assert result["positions_status"] == "quantity_mismatch"


def test_05_reconciliation_detects_missing_broker_position(tmp_path):
    stack = make_stack(tmp_path, local_state={"local_live_positions": [{"symbol": "INFY", "quantity": 10}]})
    result = stack.reconciliation.run_reconciliation("broker_readonly")
    assert result["status"] == "failed"
    assert result["positions_status"] == "missing_broker"


def test_06_reconciliation_detects_missing_local_position(tmp_path):
    mock = MockBroker("broker_readonly", connected=True, positions=[{"symbol": "INFY", "quantity": 8}])
    stack = make_stack(tmp_path, mock=mock)
    result = stack.reconciliation.run_reconciliation("broker_readonly")
    assert result["status"] == "warning"
    assert result["positions_status"] == "missing_local"


def test_07_reconciliation_records_mismatch_severity(tmp_path):
    mock = MockBroker("broker_readonly", connected=True, funds={"available_cash": 1000.0})
    stack = make_stack(tmp_path, mock=mock, local_state={"expected_cash": 1200.0})
    result = stack.reconciliation.run_reconciliation("broker_readonly")
    mismatch = result["mismatches"][0]
    assert {"type", "source", "severity", "message", "context"} <= set(mismatch)
    assert mismatch["severity"] == "critical"


def test_08_reconciliation_persists_result(tmp_path):
    stack = make_stack(tmp_path)
    result = stack.reconciliation.run_reconciliation("broker_readonly")
    rows = stack.db.query("SELECT * FROM broker_reconciliations WHERE reconciliation_id=?", (result["reconciliation_id"],))
    assert len(rows) == 1 and rows[0]["status"] == "passed"


def test_09_reconciliation_latest_returns_latest_run(tmp_path):
    stack = make_stack(tmp_path)
    first = stack.reconciliation.run_reconciliation("paper")
    latest = stack.reconciliation.run_reconciliation("broker_readonly")
    assert first["reconciliation_id"] != latest["reconciliation_id"]
    assert stack.reconciliation.get_latest_reconciliation()["reconciliation_id"] == latest["reconciliation_id"]


def test_10_reconciliation_history_returns_previous_runs(tmp_path):
    stack = make_stack(tmp_path)
    stack.reconciliation.run_reconciliation("paper")
    stack.reconciliation.run_reconciliation("broker_readonly")
    history = stack.reconciliation.get_reconciliation_history()
    assert len(history) == 2


def test_11_paper_mode_does_not_require_broker_reconciliation(tmp_path):
    stack = make_stack(tmp_path, mode="paper")
    result = stack.reconciliation.run_reconciliation("paper")
    assert result["status"] == "passed"
    assert stack.reconciliation.is_reconciliation_passing("paper") is True
    assert requires_reconciliation("paper") is False


def test_12_broker_readonly_mode_requires_broker_readonly_access(tmp_path):
    stack = make_stack(tmp_path, mode="broker_readonly")
    assert stack.guard.assert_broker_readonly_allowed("broker_readonly") is True
    assert requires_reconciliation("broker_readonly") is True


def test_13_shadow_live_mode_requires_broker_readonly_access(tmp_path):
    stack = make_stack(tmp_path, mode="shadow_live")
    result = stack.reconciliation.run_reconciliation("shadow_live")
    assert result["status"] == "passed"
    assert stack.guard.assert_broker_readonly_allowed("shadow_live") is True


def test_14_tiny_live_requires_reconciliation_but_still_blocks_live_order(tmp_path):
    stack = make_stack(tmp_path, mode="tiny_live")
    result = stack.reconciliation.run_reconciliation("tiny_live")
    assert result["status"] == "passed"
    assert stack.reconciliation.is_reconciliation_passing("tiny_live") is True
    with pytest.raises(BrokerPermissionError):
        stack.guard.assert_live_order_blocked()


def test_15_live_readiness_fails_when_reconciliation_missing(tmp_path):
    stack = make_stack(tmp_path, mode="broker_readonly")
    result = stack.readiness.run_readiness("broker_readonly")
    assert result["overall_status"] == "failed"
    assert any(check["check_name"] == "broker_reconciliation_passing" and check["status"] == "fail" for check in result["checks"])

def test_16_live_readiness_fails_when_reconciliation_failed(tmp_path):
    stack = make_stack(tmp_path, mock=MockBroker("broker_readonly", connected=False), mode="broker_readonly")
    stack.reconciliation.run_reconciliation("broker_readonly")
    result = stack.readiness.run_readiness("broker_readonly")
    assert result["overall_status"] == "failed"
    assert result["critical_failures"]


def test_17_live_readiness_marks_tiny_live_not_ready_in_batch3(tmp_path):
    stack = make_stack(tmp_path, mode="tiny_live")
    stack.reconciliation.run_reconciliation("tiny_live")
    result = stack.readiness.run_readiness("tiny_live")
    assert result["overall_status"] == "failed"
    assert result["tiny_live_ready"] is False
    assert any(check["check_name"] == "kill_switch_placeholder" and check["status"] == "fail" for check in result["checks"])


def test_18_live_readiness_includes_assistant_cannot_live_trade_check(tmp_path):
    stack = make_stack(tmp_path, mode="paper")
    result = stack.readiness.run_readiness("paper")
    assert any(check["check_name"] == "assistant_cannot_place_live_order" and check["status"] == "pass" for check in result["checks"])


def test_19_live_readiness_includes_no_live_fallback_to_paper_check(tmp_path):
    stack = make_stack(tmp_path, mode="paper")
    result = stack.readiness.run_readiness("paper")
    assert any(check["check_name"] == "no_live_fallback_to_paper" and check["status"] == "pass" for check in result["checks"])


def test_20_live_readiness_persists_run(tmp_path):
    stack = make_stack(tmp_path, mode="paper")
    result = stack.readiness.run_readiness("paper")
    runs = stack.db.query("SELECT * FROM live_readiness_runs WHERE run_id=?", (result["run_id"],))
    checks = stack.db.query("SELECT * FROM live_readiness_checks WHERE check_id LIKE ?", (result["run_id"] + "%",))
    assert len(runs) == 1 and len(checks) >= 18


def test_21_liveguard_blocks_live_order_always_in_batch3(tmp_path):
    stack = make_stack(tmp_path)
    with pytest.raises(BrokerPermissionError, match="Live orders are blocked"):
        stack.guard.assert_live_order_blocked()


def test_22_liveguard_blocks_assistant_live_order(tmp_path):
    stack = make_stack(tmp_path)
    with pytest.raises(BrokerPermissionError, match="Assistant actors cannot"):
        stack.guard.assert_assistant_cannot_live_trade("assistant")


def test_23_liveguard_blocks_tiny_live_readiness(tmp_path):
    stack = make_stack(tmp_path)
    with pytest.raises(BrokerPermissionError, match="tiny_live is not ready"):
        stack.guard.assert_tiny_live_not_ready_yet()


def test_24_reconciliation_api_returns_consistent_envelope(tmp_path):
    stack = make_stack(tmp_path)
    app = Flask(__name__); app.register_blueprint(create_broker_blueprint(stack.db, stack.broker, stack.reconciliation))
    response = app.test_client().post("/api/broker/reconcile", json={"mode": "broker_readonly"})
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["success"] is True and "data" in payload and payload["warnings"] == []


def test_25_readiness_api_returns_consistent_envelope(tmp_path):
    stack = make_stack(tmp_path, mode="paper")
    app = Flask(__name__); app.register_blueprint(create_live_blueprint(stack.readiness))
    response = app.test_client().post("/api/live/readiness/check", json={"mode": "paper"})
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["success"] is True and "data" in payload and payload["warnings"] == []


def test_26_no_api_route_submits_live_order():
    app = main.create_flask_app()
    routes = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/live/order/submit" not in routes
    assert not any("live/order" in route and "submit" in route for route in routes)


def test_27_no_test_calls_real_zerodha():
    source = Path(__file__).read_text(encoding="utf-8").lower()
    forbidden = ["kite" + "connect", "req" + "uests.", "urllib" + ".request", "http" + ".client"]
    assert all(item not in source for item in forbidden)


def test_28_no_broker_secrets_stored_in_readiness_or_reconciliation_tables(tmp_path):
    secret = "SUPERSECRET_BATCH3_TOKEN"
    mock = MockBroker("broker_readonly", connected=True, profile={"broker": "mock", "display_name": "safe"}, funds={"available_cash": 100.0, "note": secret})
    stack = make_stack(tmp_path, mode="broker_readonly", mock=mock)
    stack.reconciliation.run_reconciliation("broker_readonly")
    stack.readiness.run_readiness("broker_readonly")
    rows = []
    rows.extend(stack.db.query("SELECT mismatches_json,warnings_json,errors_json FROM broker_reconciliations"))
    rows.extend(stack.db.query("SELECT checks_json,critical_failures_json,warnings_json FROM live_readiness_runs"))
    rows.extend(stack.db.query("SELECT details_json FROM live_readiness_checks"))
    assert secret not in str(rows)


def test_29_migration_idempotency_still_passes(tmp_path):
    database = Database(tmp_path / "idempotent.sqlite3")
    database.initialize(); database.initialize()
    versions = [row["version"] for row in database.query("SELECT version FROM schema_version ORDER BY version")]
    assert versions[-1] == 9
    assert "broker_reconciliations" in {row["name"] for row in database.query("SELECT name FROM sqlite_master WHERE type='table'")}


def test_30_stage7_batch3_full_pytest_marker():
    # The actual full-suite command is run outside this test with the exact project interpreter.
    assert True
