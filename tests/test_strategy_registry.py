from app.db.database import Database
from app.services.strategy_service import CustomStrategyService
from app.strategies.registry import StrategyRegistry


def test_builtin_registry_loads_fifteen_live_disabled_strategies(tmp_path):
    database = Database(tmp_path / "registry.sqlite3"); database.initialize()
    registry = StrategyRegistry(database); registry.load_builtins()
    rows = registry.list()
    assert len(rows) == 15
    assert {row["status"] for row in rows} == {"live_disabled"}


def test_custom_strategy_saves_and_reloads(tmp_path):
    database = Database(tmp_path / "custom.sqlite3"); database.initialize()
    service = CustomStrategyService(database)
    saved = service.save("Careful RSI", "(RSI_14 < 30) & (Close > EMA_200)")
    assert saved["validation_status"] == "valid"
    reloaded = CustomStrategyService(database).list()
    assert reloaded[0]["name"] == "Careful_RSI"
