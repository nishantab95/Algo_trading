
from pathlib import Path
from types import SimpleNamespace

from flask import Flask

import main
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
from app.routes.shadow_live_routes import create_shadow_live_blueprint
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.broker_service import BrokerService
from app.services.live_readiness_service import LiveReadinessService


def phrase() -> str:
    return " ".join(["I", "UNDERSTAND", "THIS", "CAN", "PLACE", "REAL", "ORDERS"])


def make_stack(tmp_path, quotes=None, mode="shadow_live"):
    database = Database(tmp_path / "stage7_batch5.sqlite3")
    database.initialize()
    quotes = {"TCS": 100.0} if quotes is None else quotes
    mock = MockBroker(mode, connected=True, funds={"available_cash": 10000.0}, quotes=quotes)
    factory = BrokerFactory(lambda _symbol: 100.0, database, RiskManager(database), mock_broker=mock, mock_quotes=quotes)
    broker = BrokerService(factory, initial_mode=mode)

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
    return SimpleNamespace(db=database, mock=mock, broker=broker, reconciliation=reconciliation, kill=kill, unlock=unlock, guard=guard, readiness=readiness, risk=risk, tiny=tiny, shadow=shadow)


def order(**overrides):
    payload = {"symbol": "TCS", "side": "BUY", "quantity": 5, "order_type": "market", "strategy_id": "demo_strategy"}
    payload.update(overrides)
    return payload


def test_01_shadow_event_persists_intended_order(tmp_path):
    stack = make_stack(tmp_path)
    event = stack.shadow.run(order())
    rows = stack.db.query("SELECT * FROM shadow_live_events WHERE shadow_id=?", (event["shadow_id"],))
    assert len(rows) == 1
    assert rows[0]["symbol"] == "TCS"
    assert rows[0]["intended_quantity"] == 5
    assert event["live_order_submitted"] is False


def test_02_quote_comparison_and_paper_fill_are_recorded(tmp_path):
    stack = make_stack(tmp_path, quotes={"TCS": 100.0})
    event = stack.shadow.run(order())
    assert event["broker_quote_price"] == 100.0
    assert event["paper_order_id"]
    assert event["paper_fill_price"] is not None
    assert event["spread_estimate"] is not None
    assert event["slippage_estimate"] is not None


def test_03_missing_quote_fails_safely_and_records_warning(tmp_path):
    stack = make_stack(tmp_path, quotes={})
    event = stack.shadow.run(order())
    assert event["broker_quote_price"] is None
    assert event["paper_order_id"] is None
    assert "broker_quote_unavailable" in event["blocked_reason"]
    assert any("broker_quote_unavailable" in warning for warning in event["warnings"])


def test_04_would_pass_live_gate_is_false_when_live_gates_fail(tmp_path):
    stack = make_stack(tmp_path)
    event = stack.shadow.run(order())
    assert event["would_pass_live_gate"] is False
    assert "tiny_live_mode_required" in event["blocked_reason"]
    assert event["live_gate"]["approved"] is False


def test_05_shadow_live_never_calls_live_place_order(tmp_path):
    stack = make_stack(tmp_path)
    stack.shadow.run(order())
    assert stack.mock.place_order_called is False
    assert stack.mock.cancel_order_called is False
    assert stack.mock.modify_order_called is False


def test_06_paper_fill_does_not_become_live_fill(tmp_path):
    stack = make_stack(tmp_path)
    event = stack.shadow.run(order())
    paper_rows = stack.db.query("SELECT * FROM paper_orders WHERE client_order_id=?", (event["paper_order_id"],))
    shadow_rows = stack.db.query("SELECT * FROM shadow_live_events WHERE shadow_id=?", (event["shadow_id"],))
    assert paper_rows and paper_rows[0]["mode"] == "PAPER"
    assert shadow_rows and shadow_rows[0]["would_pass_live_gate"] == 0
    assert stack.mock.place_order_called is False


def test_07_report_aggregates_counts_rejections_and_slippage(tmp_path):
    stack = make_stack(tmp_path)
    stack.shadow.run(order())
    stack_missing = make_stack(tmp_path / "missing", quotes={})
    stack_missing.shadow.run(order(symbol="INFY"))
    report = stack.shadow.report()
    assert report["total_events"] == 1
    assert report["blocked_count"] == 1
    assert report["paper_simulated_count"] == 1
    assert report["average_slippage_estimate"] is not None

    missing_report = stack_missing.shadow.report()
    assert missing_report["blocked_count"] == 1
    assert any("broker_quote_unavailable" in reason for reason in missing_report["blocked_reasons"])


def test_08_shadow_live_api_envelope_consistent(tmp_path):
    stack = make_stack(tmp_path)
    app = Flask(__name__)
    app.register_blueprint(create_shadow_live_blueprint(stack.shadow))
    client = app.test_client()
    run = client.post("/api/shadow-live/run", json=order()).get_json()
    assert run["success"] is True
    assert run["data"]["live_order_submitted"] is False
    assert client.get("/api/shadow-live").get_json()["success"] is True
    report = client.get("/api/shadow-live/report").get_json()
    assert report["success"] is True
    assert report["data"]["total_events"] == 1


def test_09_shadow_live_migration_is_idempotent(tmp_path):
    database = Database(tmp_path / "shadow_migration.sqlite3")
    database.initialize(); database.initialize()
    tables = {row["name"] for row in database.query("SELECT name FROM sqlite_master WHERE type='table'")}
    versions = [row["version"] for row in database.query("SELECT version FROM schema_version ORDER BY version")]
    assert versions[-1] == 11
    assert "shadow_live_events" in tables


def test_10_composed_app_exposes_shadow_routes_and_no_live_submit_route():
    app = main.create_flask_app()
    routes = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/shadow-live" in routes
    assert "/api/shadow-live/run" in routes
    assert "/api/shadow-live/report" in routes
    assert "/api/live/order/submit" not in routes
    assert not any("live/order" in route and "submit" in route for route in routes)


def test_11_no_test_calls_real_zerodha_or_internet():
    source = Path(__file__).read_text(encoding="utf-8").lower()
    forbidden = ["kite" + "connect", "req" + "uests.", "urllib" + ".request", "http" + ".client"]
    assert all(item not in source for item in forbidden)
