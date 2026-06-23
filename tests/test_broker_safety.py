import pytest

import app.brokers.zerodha as zerodha_module
from app.brokers.zerodha import ZerodhaBroker
from app.core.config import Stage1Config
from app.core.errors import BrokerError
from app.db.database import Database
from app.db.models import OrderRequest


class FailingKite:
    def place_order(self, **_kwargs):
        raise RuntimeError("exchange rejected")


def test_live_is_disabled_by_default():
    with pytest.raises(BrokerError, match="disabled"):
        ZerodhaBroker(FailingKite()).place_order(OrderRequest("TCS", "BUY", 1))


def test_live_failure_does_not_create_paper_order(tmp_path, monkeypatch):
    database = Database(tmp_path / "safety.sqlite3"); database.initialize()
    monkeypatch.setattr(zerodha_module, "SETTINGS", Stage1Config(live_trading_enabled=True))
    with pytest.raises(BrokerError, match="Live order failed"):
        ZerodhaBroker(FailingKite()).place_order(OrderRequest("TCS", "BUY", 1))
    assert database.query("SELECT * FROM paper_orders") == []
