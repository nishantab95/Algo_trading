from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from app.backtesting.benchmark import apply_benchmark
from app.backtesting.cost_model import CostModel
from app.backtesting.engine import BacktestEngine
from app.backtesting.metrics import calculate_metrics
from app.backtesting.models import BacktestConfig
from app.backtesting.portfolio import Portfolio
from app.backtesting.validators import validate_config
from app.db.database import Database
from app.services.backtest_service import BacktestService
from app.strategies.registry import StrategyRegistry


def bars(signals=(1,0,0,0,0), highs=None, lows=None, opens=None, closes=None, symbol="TEST"):
    n=len(signals); opens=opens or [100]*n; closes=closes or [100]*n; highs=highs or [102]*n; lows=lows or [98]*n
    return pd.DataFrame({"Date":pd.date_range("2024-01-01",periods=n),"Ticker":symbol,"Open":opens,"High":highs,"Low":lows,"Close":closes,"Volume":[1_000_000]*n,"Volume_SMA_20":[1_000_000]*n,"ATR_14":[2.0]*n,"TEST_STRAT":signals})


def config(**changes):
    base=BacktestConfig("TEST_STRAT",["TEST"],initial_capital=100_000,position_sizing_method="fixed_quantity",fixed_quantity=10,liquidity_filter_enabled=False,cost_model_name="zero_cost_research",slippage_bps=0,spread_bps=0,stop_loss_pct=.05,target_pct=.15,trailing_stop_pct=.50,max_holding_bars=3,benchmark_symbol=None)
    return replace(base,**changes)


def test_backtest_config_validation(): assert validate_config(replace(config(),initial_capital=0))


def test_next_open_executes_after_signal():
    result=BacktestEngine(config()).run(bars(opens=[90,101,102,103,104]))
    assert str(result.trades[0].entry_time).startswith("2024-01-02") and result.trades[0].entry_price==101


def test_next_close_executes_at_next_close():
    result=BacktestEngine(config(execution_price_model="next_close")).run(bars(closes=[90,105,106,107,108]))
    assert result.trades[0].entry_price==105


def test_no_lookahead_signal_handling():
    result=BacktestEngine(config()).run(bars(opens=[50,110,100,100,100]))
    assert result.trades[0].entry_price==110


def test_long_only_ignores_short_signals(): assert BacktestEngine(config()).run(bars(signals=(-1,0,0))).trades==[]


def test_trade_opens_and_forced_exit_completes(): assert len(BacktestEngine(config(max_holding_bars=99)).run(bars()).trades)==1


def test_stop_loss_exit():
    result=BacktestEngine(config()).run(bars(lows=[99,90,99,99,99]))
    assert result.trades[0].exit_reason=="STOP_LOSS"


def test_target_exit():
    result=BacktestEngine(config()).run(bars(highs=[101,120,101,101,101]))
    assert result.trades[0].exit_reason=="TARGET"


def test_trailing_stop_exit():
    result=BacktestEngine(config(target_pct=1,trailing_stop_pct=.05)).run(bars(highs=[101,110,102,102,102],lows=[99,100,99,99,99]))
    assert result.trades[0].exit_reason=="TRAILING_STOP"


def test_max_holding_exit(): assert BacktestEngine(config(max_holding_bars=2)).run(bars()).trades[0].exit_reason=="MAX_HOLDING_PERIOD"


def test_max_positions_enforced():
    data=pd.concat([bars(symbol="A"),bars(symbol="B")]); cfg=replace(config(),symbols=["A","B"],max_positions=1)
    result=BacktestEngine(cfg).run(data); assert any("maximum positions" in (o.rejection_reason or "") for o in result.orders)


def test_duplicate_symbol_rule_enforced():
    result=BacktestEngine(config(max_holding_bars=99)).run(bars(signals=(1,1,1,0,0)))
    assert len(result.trades)==1


def test_cash_cannot_go_negative():
    result=BacktestEngine(config(fixed_quantity=999999)).run(bars()); assert min(row["cash"] for row in result.equity_curve)>=0


def test_fixed_value_position_sizing():
    qty,error=Portfolio(config(position_sizing_method="fixed_value",fixed_position_value=10_000)).size_position(100,95); assert qty==100 and error is None


def test_risk_percent_position_sizing():
    qty,_=Portfolio(config(position_sizing_method="risk_percent",risk_per_trade_pct=.01)).size_position(100,95); assert qty==200


def test_atr_risk_uses_atr14_value():
    qty,_=Portfolio(config(position_sizing_method="atr_risk",risk_per_trade_pct=.01,max_position_value_pct=1)).size_position(100,95,2); assert qty==250


def test_missing_atr_rejects():
    qty,error=Portfolio(config(position_sizing_method="atr_risk")).size_position(100,95,None); assert qty==0 and "ATR_14" in error


def test_cost_model_nonzero(): assert CostModel.named("india_equity_delivery_approx").calculate("BUY",10,100,100).total_costs>0


def test_slippage_changes_fill_price(): assert BacktestEngine(config(cost_model_name="india_equity_delivery_approx",slippage_bps=10)).execution.fill_price(100,"BUY")>100


def test_equity_curve_updates(): assert len(BacktestEngine(config()).run(bars()).equity_curve)==5


def test_drawdown_calculation():
    metrics=calculate_metrics([], [{"timestamp":"2024-01-01","total_equity":100,"drawdown_pct":0},{"timestamp":"2024-01-02","total_equity":80,"drawdown_pct":-20}],100,0,[]); assert metrics["max_drawdown_pct"]==20


def test_profit_factor_calculation():
    win=BacktestEngine(config()).run(bars(highs=[101,120,101,101,101])).trades[0]
    loss=BacktestEngine(config()).run(bars(lows=[99,90,99,99,99])).trades[0]
    metrics=calculate_metrics([win,loss],[],100_000,0,[]); assert metrics["profit_factor"]>0


def test_no_trade_backtest_does_not_crash(): assert BacktestEngine(config()).run(bars(signals=(0,0,0))).metrics["total_trades"]==0


def test_all_loss_backtest_does_not_crash(): assert BacktestEngine(config()).run(bars(lows=[99,90,99,99,99])).metrics["profit_factor"]==0


def test_benchmark_missing_fallback():
    metrics,warnings=apply_benchmark([],bars(),"MISSING",100_000); assert metrics=={} and warnings


def test_database_persists_backtest_run(tmp_path):
    db=Database(tmp_path/"bt.sqlite3"); db.initialize(); StrategyRegistry(db).load_builtins()
    data=bars().rename(columns={"TEST_STRAT":"RSI_Oversold"}); cfg=replace(config(strategy_id="RSI_Oversold"))
    result=BacktestService(db).run(cfg,data,persist=True); assert db.query("SELECT run_id FROM backtest_runs")[0]["run_id"]==result.run_id


def test_api_contract_for_backtest_blueprint(tmp_path):
    from flask import Flask
    from app.routes.backtest_routes import create_backtest_blueprint
    class Fake:
        def list_runs(self): return []
    app=Flask(__name__); app.register_blueprint(create_backtest_blueprint(Fake())); response=app.test_client().get('/api/backtests')
    assert response.get_json()=={"success":True,"data":[],"error":None,"warnings":[]}


def test_robustness_produces_multiple_scenarios(tmp_path):
    db=Database(tmp_path/"robust.sqlite3"); db.initialize(); StrategyRegistry(db).load_builtins()
    data=bars().rename(columns={"TEST_STRAT":"RSI_Oversold"}); cfg=replace(config(strategy_id="RSI_Oversold"))
    result=BacktestService(db).robustness(cfg,data); assert {"normal","slippage_2x","slippage_3x","delayed_entry_1_bar","delayed_exit_1_bar","half_position_size"} <= set(result["scenarios"])
