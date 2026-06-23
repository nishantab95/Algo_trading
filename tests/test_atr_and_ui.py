from pathlib import Path

import bot


ROOT = Path(__file__).resolve().parents[1]


def test_atr_position_sizing_uses_supplied_atr():
    engine = bot.TradingStateMachine(initial_capital=100_000)
    quantity = engine._atr_position_size("TCS", price=100, atr=10)
    assert quantity == 50


def test_scanner_uses_atr_14_and_ui_uses_safe_endpoints():
    bot_source = (ROOT / "bot.py").read_text(encoding="utf-8")
    main_source = (ROOT / "main.py").read_text(encoding="utf-8")
    ui_source = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'latest.get("ATR_14"' in bot_source
    assert 'latest.get("ATR_14")' in main_source
    assert "fetch('/api/reset_session'" in ui_source
    assert "fetch('/api/run_exit_sweep'" in ui_source
    assert "fetch('/api/recalibrate'" in ui_source
