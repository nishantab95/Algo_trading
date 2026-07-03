import pytest
from flask import Flask

from app.brokers.broker_factory import BrokerFactory
from app.brokers.broker_modes import BrokerMode, broker_mode_specs
from app.brokers.broker_service import BrokerService
from app.brokers.mock_broker import MockBroker
from app.brokers.paper import PaperBroker
from app.brokers.zerodha import ZerodhaBroker
from app.core.errors import BrokerError
from app.db.database import Database
from app.db.models import OrderRequest
from app.routes.broker_routes import create_broker_blueprint
from app.risk.manager import RiskManager


def service_for(tmp_path, mode=None):
    database = Database(tmp_path / "stage7_broker.sqlite3"); database.initialize()
    factory = BrokerFactory(lambda _symbol: 100.0, database, RiskManager(database), mock_quotes={"TCS": 101.5})
    return BrokerService(factory, initial_mode=mode), database


def test_01_stage7_batch2_defaults_to_live_disabled(tmp_path):
    service, _database = service_for(tmp_path)
    status = service.status()
    assert status["mode"] == "live_disabled"
    assert status["default_mode"] == "live_disabled"
    assert status["live_orders_allowed"] is False
    assert status["broker"]["read_only"] is True
    assert status["broker"]["real_broker"] is False


def test_02_required_broker_modes_are_listed():
    values = {item["value"] for item in broker_mode_specs()}
    assert values == {"live_disabled", "paper", "broker_readonly", "shadow_live", "tiny_live"}
    assert all(item["live_order_allowed"] is False for item in broker_mode_specs())


def test_03_factory_never_returns_zerodha_for_stage7_modes(tmp_path):
    service, _database = service_for(tmp_path)
    for mode in BrokerMode:
        service.set_mode(mode.value, actor="user")
        broker = service.broker()
        assert not isinstance(broker, ZerodhaBroker)
        assert broker.capabilities()["real_broker"] is False
        if mode is BrokerMode.PAPER:
            assert isinstance(broker, PaperBroker)
        else:
            assert isinstance(broker, MockBroker)


def test_04_non_paper_modes_reject_order_submission(tmp_path):
    service, _database = service_for(tmp_path)
    request = OrderRequest("TCS", "BUY", 1)
    for mode in [BrokerMode.LIVE_DISABLED, BrokerMode.BROKER_READONLY, BrokerMode.SHADOW_LIVE, BrokerMode.TINY_LIVE]:
        service.set_mode(mode.value, actor="user")
        with pytest.raises(BrokerError, match="fail-closed"):
            service.place_order(request, actor="user")


def test_05_paper_mode_uses_only_paper_implementation(tmp_path):
    service, database = service_for(tmp_path)
    service.set_mode("paper", actor="user")
    result = service.place_order(OrderRequest("INFY", "BUY", 1), actor="user")
    assert result["status"] == "PAPER_FILLED"
    assert isinstance(service.broker(), PaperBroker)
    assert not hasattr(service.broker(), "kite")
    assert database.query("SELECT * FROM paper_orders WHERE symbol='INFY'")


def test_06_broker_readonly_and_shadow_live_reject_mutation(tmp_path):
    service, _database = service_for(tmp_path)
    for mode in ["broker_readonly", "shadow_live"]:
        service.set_mode(mode, actor="user")
        with pytest.raises(BrokerError, match="fail-closed"):
            service.place_order(OrderRequest("TCS", "BUY", 1), actor="user")
        with pytest.raises(BrokerError, match="fail-closed"):
            service.cancel_order("order-1", actor="user")


def test_07_tiny_live_is_present_but_still_rejects_live_orders(tmp_path):
    service, _database = service_for(tmp_path)
    service.set_mode("tiny_live", actor="user")
    status = service.status()
    assert status["tiny_live_locked"] is True
    assert status["live_orders_allowed"] is False
    with pytest.raises(BrokerError, match="fail-closed"):
        service.place_order(OrderRequest("TCS", "BUY", 1), actor="user")


def test_08_assistant_cannot_switch_to_tiny_live(tmp_path):
    service, _database = service_for(tmp_path)
    with pytest.raises(PermissionError, match="assistants cannot switch"):
        service.set_mode("tiny_live", actor="assistant")
    assert service.current_mode is BrokerMode.LIVE_DISABLED


def test_09_assistant_cannot_execute_broker_action(tmp_path):
    service, _database = service_for(tmp_path)
    service.set_mode("tiny_live", actor="user")
    with pytest.raises(PermissionError, match="Assistant cannot execute broker actions"):
        service.place_order(OrderRequest("TCS", "BUY", 1), actor="assistant")


def test_10_read_only_calls_work_without_credentials(tmp_path):
    service, _database = service_for(tmp_path, "broker_readonly")
    assert service.quotes(["TCS"])["TCS"] == 101.5
    assert service.funds()["source"] == "mock_broker"
    assert service.positions() == []
    assert service.holdings() == []


def test_11_broker_routes_expose_safe_mode_api_and_block_assistant(tmp_path):
    service, database = service_for(tmp_path)
    app = Flask(__name__); app.register_blueprint(create_broker_blueprint(database, service))
    client = app.test_client()
    status = client.get("/api/broker/status").get_json()
    assert status["success"] is True and status["data"]["mode"] == "live_disabled"
    blocked = client.post("/api/broker/mode", json={"mode": "tiny_live", "actor": "assistant"})
    assert blocked.status_code == 403 and blocked.get_json()["success"] is False
    changed = client.post("/api/broker/mode", json={"mode": "paper", "actor": "user"}).get_json()
    assert changed["success"] is True and changed["data"]["value"] == "paper"
    assert client.get("/api/broker/funds").get_json()["success"] is True
    assert client.post("/api/connect_zerodha", json={}).status_code == 403


def test_12_safe_status_payload_does_not_expose_secret_fields(tmp_path):
    service, _database = service_for(tmp_path)
    text = str(service.status()).lower()
    assert "api_secret" not in text
    assert "access_token" not in text
    assert "request_token" not in text
    assert "zerodha" not in text
