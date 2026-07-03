from pathlib import Path

import pytest
from flask import Flask

import main
from app.brokers.broker_errors import (
    BrokerModeError,
    BrokerPermissionError,
    BrokerReadOnlyError,
    BrokerUnavailableError,
)
from app.brokers.broker_factory import BrokerFactory
from app.brokers.broker_modes import (
    BrokerMode,
    allows_live_order,
    allows_paper_order,
    allows_readonly_broker,
    default_mode,
    normalize_mode,
    requires_reconciliation,
)
from app.brokers.mock_broker import MockBroker
from app.brokers.paper import PaperBroker
from app.brokers.zerodha import ZerodhaBroker
from app.db.database import Database
from app.db.models import OrderRequest
from app.risk.manager import RiskManager
from app.routes.broker_routes import create_broker_blueprint
from app.services.broker_service import BrokerService


def service_for(tmp_path, mode=None, mock_broker=None, mock_quotes=None, live_broker=None):
    database = Database(tmp_path / "stage7_broker.sqlite3"); database.initialize()
    factory = BrokerFactory(
        lambda _symbol: 100.0,
        database,
        RiskManager(database),
        mock_quotes=mock_quotes or {"TCS": 101.5, "INFY": 1500.0},
        mock_broker=mock_broker,
        live_broker=live_broker,
    )
    return BrokerService(factory, initial_mode=mode), database


def test_01_default_broker_mode_is_live_disabled(tmp_path):
    service, _database = service_for(tmp_path)
    status = service.get_status()
    assert default_mode() is BrokerMode.LIVE_DISABLED
    assert service.get_mode() == "live_disabled"
    assert status["mode"] == "live_disabled"
    assert status["live_orders_allowed"] is False
    assert status["paper_orders_allowed"] is False


def test_02_normalize_mode_accepts_all_valid_modes():
    for mode in BrokerMode:
        assert normalize_mode(mode.value) is mode
        assert normalize_mode(mode) is mode


def test_03_normalize_mode_rejects_invalid_mode():
    with pytest.raises(BrokerModeError, match="Unsupported broker mode"):
        normalize_mode("full_live")


def test_04_live_disabled_rejects_place_order(tmp_path):
    service, _database = service_for(tmp_path)
    with pytest.raises(BrokerReadOnlyError, match="fail-closed"):
        service.place_order(OrderRequest("TCS", "BUY", 1), actor="user")


def test_05_live_disabled_rejects_broker_readonly_access(tmp_path):
    service, _database = service_for(tmp_path)
    with pytest.raises(BrokerModeError, match="live_disabled"):
        service.get_readonly_state()
    with pytest.raises(BrokerModeError, match="live_disabled"):
        service.funds()


def test_06_paper_mode_allows_paper_order_path_only(tmp_path):
    service, database = service_for(tmp_path, "paper")
    assert service.assert_can_place_paper_order() is True
    with pytest.raises(BrokerPermissionError, match="Live order placement is disabled"):
        service.assert_can_place_live_order()
    result = service.place_order(OrderRequest("INFY", "BUY", 1), actor="user")
    assert result["status"] == "PAPER_FILLED"
    assert database.query("SELECT * FROM paper_orders WHERE symbol='INFY'")


def test_07_paper_mode_never_calls_mock_live_broker(tmp_path):
    mock = MockBroker(BrokerMode.BROKER_READONLY, connected=True, raise_on_place=True)
    service, _database = service_for(tmp_path, "paper", mock_broker=mock)
    service.place_order(OrderRequest("TCS", "BUY", 1), actor="user")
    assert mock.place_order_called is False


def test_08_broker_readonly_allows_read_methods_when_mock_connected(tmp_path):
    mock = MockBroker(
        BrokerMode.BROKER_READONLY,
        connected=True,
        funds={"available_cash": 12345.0},
        holdings=[{"symbol": "TCS", "quantity": 2}],
        positions=[{"symbol": "INFY", "quantity": 1}],
        orders=[{"order_id": "ro-1", "status": "COMPLETE"}],
        trades=[{"trade_id": "tr-1", "symbol": "TCS"}],
        quotes={"TCS": 101.5},
    )
    service, _database = service_for(tmp_path, "broker_readonly", mock_broker=mock)
    assert service.profile()["source"] == "mock_broker"
    assert service.funds()["available_cash"] == 12345.0
    assert service.holdings()[0]["symbol"] == "TCS"
    assert service.positions()[0]["symbol"] == "INFY"
    assert service.orders()[0]["order_id"] == "ro-1"
    assert service.trades()[0]["trade_id"] == "tr-1"
    assert service.quote("TCS")["last_price"] == 101.5


def test_09_broker_readonly_rejects_place_order(tmp_path):
    service, _database = service_for(tmp_path, "broker_readonly")
    with pytest.raises(BrokerReadOnlyError, match="read-only"):
        service.place_order(OrderRequest("TCS", "BUY", 1), actor="user")


def test_10_broker_readonly_rejects_cancel_order(tmp_path):
    service, _database = service_for(tmp_path, "broker_readonly")
    with pytest.raises(BrokerReadOnlyError, match="cancellation"):
        service.cancel_order("order-1", actor="user")


def test_11_broker_readonly_rejects_modify_order(tmp_path):
    service, _database = service_for(tmp_path, "broker_readonly")
    with pytest.raises(BrokerReadOnlyError, match="modification"):
        service.modify_order("order-1", {"quantity": 2}, actor="user")


def test_12_shadow_live_allows_readonly_methods(tmp_path):
    service, _database = service_for(tmp_path, "shadow_live")
    state = service.get_readonly_state()
    assert state["mode"] == "shadow_live"
    assert service.quote("TCS")["source"] == "mock_broker"
    assert allows_readonly_broker("shadow_live") is True


def test_13_shadow_live_rejects_live_place_order(tmp_path):
    service, _database = service_for(tmp_path, "shadow_live")
    with pytest.raises(BrokerReadOnlyError, match="fail-closed"):
        service.place_order(OrderRequest("TCS", "BUY", 1), actor="user")

def test_14_shadow_live_can_reference_paper_broker_without_live_order_call(tmp_path):
    mock = MockBroker(BrokerMode.SHADOW_LIVE, connected=True)
    service, database = service_for(tmp_path, "shadow_live", mock_broker=mock)
    assert allows_paper_order("shadow_live") is True
    assert service.assert_can_place_paper_order() is True
    assert isinstance(service.get_paper_broker(), PaperBroker)
    assert mock.place_order_called is False
    assert database.query("SELECT * FROM paper_orders") == []


def test_15_tiny_live_rejects_place_order_in_batch2(tmp_path):
    service, _database = service_for(tmp_path, "tiny_live")
    assert service.get_status()["tiny_live_locked"] is True
    with pytest.raises(BrokerReadOnlyError, match="fail-closed"):
        service.place_order(OrderRequest("TCS", "BUY", 1), actor="user")


def test_16_broker_factory_does_not_expose_raw_zerodha_directly(tmp_path):
    database = Database(tmp_path / "factory.sqlite3"); database.initialize()
    factory = BrokerFactory(lambda _symbol: 100.0, database, live_broker=ZerodhaBroker(object()))
    for mode in ["live_disabled", "broker_readonly", "shadow_live", "tiny_live"]:
        broker = factory.create(mode)
        assert not isinstance(broker, ZerodhaBroker)
        assert broker.capabilities()["real_broker"] is False


def test_17_broker_service_works_without_credentials():
    service = BrokerService(BrokerFactory())
    status = service.get_status()
    assert status["mode"] == "live_disabled"
    assert status["broker_connected"] is False
    assert status["live_orders_allowed"] is False
    assert "disabled" in status["message"].lower()


def test_18_broker_status_api_returns_consistent_envelope(tmp_path):
    service, database = service_for(tmp_path)
    app = Flask(__name__); app.register_blueprint(create_broker_blueprint(database, service))
    payload = app.test_client().get("/api/broker/status").get_json()
    assert payload["success"] is True
    assert payload["data"]["mode"] == "live_disabled"
    assert payload["warnings"] == []


def test_19_broker_mode_api_rejects_invalid_mode(tmp_path):
    service, database = service_for(tmp_path)
    app = Flask(__name__); app.register_blueprint(create_broker_blueprint(database, service))
    response = app.test_client().post("/api/broker/mode", json={"mode": "live"})
    payload = response.get_json()
    assert response.status_code == 400
    assert payload["success"] is False
    assert "Unsupported broker mode" in payload["error"]


def test_20_assistant_actor_cannot_switch_to_tiny_live(tmp_path):
    service, _database = service_for(tmp_path)
    with pytest.raises(BrokerPermissionError, match="Assistant cannot switch"):
        service.set_mode("tiny_live", actor="assistant")
    assert service.get_mode() == "live_disabled"


def test_21_assistant_cannot_approve_or_execute_broker_live_action(tmp_path):
    service, _database = service_for(tmp_path, "tiny_live")
    with pytest.raises(BrokerPermissionError, match="Live order placement is disabled"):
        service.assert_can_place_live_order(actor="assistant")
    with pytest.raises(BrokerPermissionError, match="Assistant cannot execute broker actions"):
        service.place_order(OrderRequest("TCS", "BUY", 1), actor="assistant")


def test_22_mock_broker_records_if_place_order_was_attempted():
    mock = MockBroker(BrokerMode.BROKER_READONLY, connected=True)
    with pytest.raises(BrokerReadOnlyError):
        mock.place_order(OrderRequest("TCS", "BUY", 1))
    assert mock.place_order_called is True


def test_23_broker_rejection_returns_clear_error():
    mock = MockBroker(BrokerMode.BROKER_READONLY, connected=True, raise_on_place=True)
    with pytest.raises(BrokerUnavailableError, match="Mock broker rejected order submission"):
        mock.place_order(OrderRequest("TCS", "BUY", 1))
    assert mock.place_order_called is True


def test_24_no_live_order_becomes_paper_fill(tmp_path):
    mock = MockBroker(BrokerMode.SHADOW_LIVE, connected=True)
    service, database = service_for(tmp_path, "shadow_live", mock_broker=mock)
    with pytest.raises(BrokerReadOnlyError):
        service.place_order(OrderRequest("TCS", "BUY", 1), actor="user")
    assert mock.place_order_called is False
    assert database.query("SELECT * FROM paper_orders") == []


def test_25_no_test_imports_real_zerodha_session_or_calls_internet():
    source = Path(__file__).read_text(encoding="utf-8").lower()
    forbidden = ["kite" + "connect", "req" + "uests.", "urllib" + ".request", "http" + ".client"]
    assert all(item not in source for item in forbidden)


def test_26_no_live_submit_route_exists_and_mode_helpers_fail_closed():
    app = main.create_flask_app()
    routes = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/live/order/submit" not in routes
    assert all(allows_live_order(mode) is False for mode in BrokerMode)
    assert requires_reconciliation("paper") is False
    assert requires_reconciliation("tiny_live") is True
