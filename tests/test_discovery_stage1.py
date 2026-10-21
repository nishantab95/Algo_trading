"""Regression coverage for the read-only Stock Discovery foundation."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.db.database import Database
from app.paper.broker import PaperOperationsBroker


ROOT = Path(__file__).resolve().parents[1]


def test_discovery_home_is_read_only_and_preserves_paper_records(tmp_path):
    """Exercise the active app in a fresh process with an isolated SQLite file."""
    database_path = tmp_path / "discovery.sqlite3"
    database = Database(database_path)
    database.initialize()
    broker = PaperOperationsBroker(database, lambda _symbol: 100.0, 10_000)
    broker.create_order(
        {"symbol": "INFY", "side": "BUY", "quantity": 1, "order_type": "market"},
        approved_by_user=True,
    )
    assert len(database.query("SELECT * FROM paper_orders")) == 1

    script = """
from app.llm.lmstudio_client import LMStudioClient

def unavailable_llm(*args, **kwargs):
    raise AssertionError('The Discovery runtime must not initialize an LLM client')

LMStudioClient.__init__ = unavailable_llm
import main
from app.db.database import Database

app = main.create_flask_app()
client = app.test_client()
page = client.get('/')
html = page.get_data(as_text=True)
assert page.status_code == 200
assert 'Stock Discovery' in html
assert 'Trade &amp; Manage' in html and 'Coming later' in html
assert 'Fundamental Health' in html and 'UNKNOWN' in html
assert 'Analyse Stocks' in html and 'id="analyse-stocks"' in html

state = client.get('/api/state').get_json()['data']
assert state['mode'] == 'DISCOVERY'
assert state['trading_enabled'] is False
assert state['analysis_available'] is False
assert state['fundamental_health'] == 'UNKNOWN'

database = Database(__import__('os').environ['ALGO_DATABASE_PATH'])
before = len(database.query('SELECT * FROM paper_orders'))
for path in ('/api/paper/orders', '/api/place_order', '/api/run_scan'):
    response = client.post(path, json={'symbol': 'TCS', 'side': 'BUY', 'quantity': 1})
    assert response.status_code == 403
    assert response.get_json()['success'] is False
assert len(database.query('SELECT * FROM paper_orders')) == before == 1
"""
    env = {
        **os.environ,
        "ALGO_DATABASE_PATH": str(database_path),
        "ALGO_DATA_ROOT": str(tmp_path / "data"),
        "ALGO_RAW_DATA_ROOT": str(tmp_path / "raw"),
        "ALGO_REPORTS_ROOT": str(tmp_path / "reports"),
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
