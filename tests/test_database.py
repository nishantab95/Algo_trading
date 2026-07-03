from app.db.database import Database


EXPECTED_TABLES = {
    "paper_account", "paper_positions", "paper_orders", "paper_trades", "strategy_registry",
    "custom_strategies", "system_logs", "risk_events", "pipeline_manifests", "schema_version",
}


def test_database_initializes_all_stage1_tables(tmp_path):
    database = Database(tmp_path / "state.sqlite3")
    database.initialize()
    names = {row["name"] for row in database.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED_TABLES <= names


def test_database_migrations_are_idempotent(tmp_path):
    database = Database(tmp_path / "idempotent.sqlite3")
    database.initialize()
    first = database.query("SELECT version, applied_at FROM schema_version ORDER BY version")
    database.initialize()
    second = database.query("SELECT version, applied_at FROM schema_version ORDER BY version")
    assert first == second and [row["version"] for row in second] == list(range(1, 12))
