import pytest

from app.brokers.paper import PaperBroker
from app.db.database import Database
from app.db.models import OrderRequest
from app.risk.manager import RiskManager


def make_broker(path):
    database = Database(path); database.initialize()
    return PaperBroker(lambda _symbol: 100.0, database, RiskManager(database)), database


def test_paper_account_and_position_survive_restart(tmp_path):
    path = tmp_path / "paper.sqlite3"
    broker, _ = make_broker(path)
    broker.place_order(OrderRequest("TCS", "BUY", 10))
    restarted, _ = make_broker(path)
    assert restarted.get_funds()["cash"] < restarted.get_funds()["starting_capital"]
    assert restarted.get_positions()[0]["symbol"] == "TCS"


def test_reset_restores_account_and_clears_positions(tmp_path):
    broker, _ = make_broker(tmp_path / "reset.sqlite3")
    broker.place_order(OrderRequest("INFY", "BUY", 5))
    broker.reset()
    assert broker.get_positions() == []
    assert broker.get_funds()["cash"] == broker.get_funds()["starting_capital"]


def test_risk_manager_rejects_duplicate_symbol(tmp_path):
    broker, database = make_broker(tmp_path / "risk.sqlite3")
    broker.place_order(OrderRequest("SBIN", "BUY", 5))
    with pytest.raises(ValueError, match="already exists"):
        broker.place_order(OrderRequest("SBIN", "BUY", 5))
    assert database.query("SELECT * FROM risk_events")
