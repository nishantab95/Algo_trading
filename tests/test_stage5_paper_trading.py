from __future__ import annotations

from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app.assistant.action_drafts import ActionDraftService
from app.assistant.command_router import route_command
from app.db.database import Database
from app.paper.analytics import PaperAnalytics
from app.paper.broker import PaperOperationsBroker
from app.routes.paper_trading_routes import create_stage5_paper_blueprint
from app.services.paper_portfolio_service import PaperPortfolioService


@pytest.fixture
def stack(tmp_path):
    prices={"INFY":100.0,"TCS":200.0,"RELIANCE":250.0}
    db=Database(tmp_path/"stage5.sqlite");db.initialize()
    broker=PaperOperationsBroker(db,lambda symbol:prices[symbol],100_000)
    return SimpleNamespace(db=db,broker=broker,prices=prices,analytics=PaperAnalytics(broker))

def buy(stack,symbol="INFY",quantity=10,**extra):
    return stack.broker.create_order({"symbol":symbol,"side":"BUY","quantity":quantity,"order_type":"market",**extra},approved_by_user=True)

def close(stack,symbol="INFY",quantity=None,reason="manual_exit"):
    p=next(p for p in stack.broker.positions() if p["symbol"]==symbol)
    return stack.broker.exit_position(p["id"],quantity,reason,True)

def test_01_account_initializes_correctly(stack):
    a=stack.broker.account();assert a["cash"]==100_000 and a["total_equity"]==100_000 and a["status"]=="active"

def test_02_account_persists_after_restart_simulation(stack):
    buy(stack);cash=stack.broker.account()["cash"]
    restarted=PaperOperationsBroker(Database(stack.db.path),lambda _s:100.0,999)
    assert restarted.account()["cash"]==cash and restarted.positions()[0]["symbol"]=="INFY"

def test_03_market_order_creates_order_fill_position_and_account_update(stack):
    order=buy(stack);assert order["status"]=="filled" and len(stack.broker.fills())==1 and stack.broker.positions()[0]["quantity"]==10 and stack.broker.account()["cash"]<100_000

def test_04_insufficient_cash_rejects_order(stack):
    order=stack.broker.create_order({"symbol":"INFY","side":"BUY","quantity":2000,"order_type":"market"},True)
    assert order["status"]=="rejected" and "cash" in order["rejection_reason"].lower()

def test_05_duplicate_position_rejected_if_not_allowed(stack):
    buy(stack);order=stack.broker.create_order({"symbol":"INFY","side":"BUY","quantity":1,"order_type":"market"},True)
    assert order["status"]=="rejected" and "duplicate" in order["rejection_reason"].lower()

def test_06_risk_manager_blocks_order_above_max_value(stack):
    stack.broker.update_risk_settings({"max_order_value":500})
    order=stack.broker.create_order({"symbol":"INFY","side":"BUY","quantity":10,"order_type":"market"},True)
    assert order["status"]=="rejected" and "maximum" in order["rejection_reason"].lower()

def test_07_limit_order_fills_only_when_price_condition_met(stack):
    order=stack.broker.create_order({"symbol":"INFY","side":"BUY","quantity":2,"order_type":"limit","limit_price":95})
    assert stack.broker.approve_order(order["id"])["status"]=="submitted"
    stack.prices["INFY"]=94;assert stack.broker.process_open_orders()[0]["status"]=="filled"

def test_08_stop_order_triggers_correctly(stack):
    order=stack.broker.create_order({"symbol":"INFY","side":"BUY","quantity":2,"order_type":"stop","stop_price":105})
    assert stack.broker.approve_order(order["id"])["status"]=="submitted"
    stack.prices["INFY"]=106;assert stack.broker.process_open_orders()[0]["status"]=="filled"

def test_09_cancel_pending_order_works(stack):
    order=stack.broker.create_order({"symbol":"INFY","side":"BUY","quantity":1,"order_type":"limit","limit_price":90})
    assert stack.broker.cancel_order(order["id"])["status"]=="cancelled"

def test_10_buy_updates_average_price_correctly(stack):
    stack.broker.update_risk_settings({"allow_duplicate_position":True})
    buy(stack,quantity=10);stack.prices["INFY"]=110;buy(stack,quantity=10)
    p=stack.broker.positions()[0];assert p["quantity"]==20 and 104<p["avg_price"]<106

def test_11_partial_exit_calculates_realized_pnl_correctly(stack):
    buy(stack,quantity=10);stack.prices["INFY"]=110;close(stack,quantity=4,reason="partial_exit")
    assert stack.broker.positions()[0]["quantity"]==6 and stack.broker.account()["realized_pnl"]>0 and stack.broker.journal()[0]["quantity"]==4

def test_12_full_exit_closes_position(stack):
    buy(stack);stack.prices["INFY"]=110;close(stack)
    assert stack.broker.positions()==[] and stack.broker.positions(False)[0]["status"]=="CLOSED"

def test_13_stop_loss_exit_creates_sell_order(stack):
    buy(stack,stop_price=95);stack.prices["INFY"]=94;result=stack.broker.exit_sweep()
    assert result["exits_created"]==1 and result["orders"][0]["side"]=="SELL" and stack.broker.journal()[0]["exit_reason"]=="stop_loss_exit"

def test_14_target_exit_creates_sell_order(stack):
    buy(stack,metadata={"target":110});stack.prices["INFY"]=111
    assert stack.broker.exit_sweep()["orders"][0]["side"]=="SELL" and stack.broker.journal()[0]["exit_reason"]=="target_exit"

def test_15_trailing_stop_updates_highest_price(stack):
    buy(stack,metadata={"trailing_stop":5});stack.prices["INFY"]=120;stack.broker.mark_to_market()
    assert stack.broker.positions()[0]["highest_price"]==120

def test_16_trailing_stop_exit_works(stack):
    buy(stack,metadata={"trailing_stop":5});stack.prices["INFY"]=120;stack.broker.mark_to_market();stack.prices["INFY"]=113
    assert stack.broker.exit_sweep()["exits_created"]==1 and stack.broker.journal()[0]["exit_reason"]=="trailing_stop_exit"

def test_17_exit_sweep_does_not_create_entries(stack):
    before=len(stack.broker.orders());result=stack.broker.exit_sweep()
    assert result["entries_created"]==0 and len(stack.broker.orders())==before

def test_18_cash_never_goes_negative(stack):
    buy(stack,quantity=10);assert stack.broker.account()["cash"]>=0
    rejected=stack.broker.create_order({"symbol":"TCS","side":"BUY","quantity":1000,"order_type":"market"},True);assert rejected["status"]=="rejected" and stack.broker.account()["cash"]>=0

def test_19_unrealized_pnl_updates_with_price(stack):
    buy(stack);stack.prices["INFY"]=110;stack.broker.mark_to_market();assert stack.broker.account()["unrealized_pnl"]>0

def test_20_daily_snapshot_stores_equity(stack):
    buy(stack);snap=stack.broker.snapshots(1)[0];assert snap["total_equity"]>0 and snap["orders_count"]==1

def test_21_drawdown_calculation_works(stack):
    buy(stack);stack.prices["INFY"]=80;stack.broker.mark_to_market();assert stack.broker.account()["max_drawdown"]>0

def test_22_journal_entry_created_on_completed_trade(stack):
    buy(stack,strategy_id="EMA");close(stack);trade=stack.broker.journal()[0];assert trade["strategy_id"]=="EMA" and trade["entry_order_id"] and trade["exit_order_id"]

def test_23_journal_notes_update_works(stack):
    buy(stack);close(stack);trade=stack.broker.journal()[0];assert stack.broker.update_journal(trade["id"],{"notes":"Followed plan"})["notes"]=="Followed plan"

def test_24_mistake_tags_update_works(stack):
    buy(stack);close(stack);trade=stack.broker.journal()[0];updated=stack.broker.update_journal(trade["id"],{"mistake_tags_json":["late_entry"]});assert "late_entry" in updated["mistake_tags_json"]

def seeded_trades(stack):
    buy(stack,strategy_id="EMA");stack.prices["INFY"]=110;close(stack);buy(stack,"TCS",1,strategy_id="EMA");stack.prices["TCS"]=190;close(stack,"TCS")

def test_25_analytics_calculate_win_rate(stack):
    seeded_trades(stack);assert stack.analytics.summary()["win_rate"]==50

def test_26_analytics_calculate_profit_factor(stack):
    seeded_trades(stack);assert stack.analytics.summary()["profit_factor"]>0

def test_27_analytics_calculate_expectancy(stack):
    seeded_trades(stack);assert isinstance(stack.analytics.summary()["expectancy"],float)

def test_28_strategy_promotion_rejects_low_sample_size(stack):
    review=stack.analytics.promotion_review("EMA",persist=False);assert review["promotion_status"]=="needs_more_data" and review["warnings"]

def test_29_assistant_draft_paper_order_requires_approval(stack):
    order=stack.broker.create_order({"symbol":"INFY","side":"BUY","quantity":1,"order_type":"market","source":"assistant"});assert order["status"]=="pending_approval" and stack.broker.positions()==[]

def test_30_rejected_assistant_action_does_not_execute(stack):
    drafts=ActionDraftService(stack.db,{"place_paper_order":lambda p:stack.broker.create_order(p,True)});draft=drafts.create("place_paper_order",{"symbol":"INFY","quantity":1})
    drafts.reject(draft["id"]);assert stack.broker.positions()==[]

def test_31_api_response_format_is_consistent(stack,tmp_path):
    class Reports:
        def export_journal(self):return str(tmp_path/"journal.csv")
        def export_all(self):return {}
    app=Flask(__name__);app.register_blueprint(create_stage5_paper_blueprint(stack.broker,PaperPortfolioService(stack.broker),stack.analytics,Reports()));client=app.test_client()
    payload=client.get("/api/paper/portfolio/summary").get_json();assert payload["success"] is True and "data" in payload and "warnings" in payload

def test_32_reset_account_requires_confirmation(stack):
    with pytest.raises(PermissionError):stack.broker.reset(False)

def test_33_reset_archives_and_clears_safely(stack):
    buy(stack);result=stack.broker.reset(True);assert result["reset"] and stack.broker.positions()==[] and stack.db.query("SELECT * FROM paper_reset_archives")

def test_34_data_stale_order_rejection_works(tmp_path):
    db=Database(tmp_path/"stale.sqlite");db.initialize();stamp=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat();broker=PaperOperationsBroker(db,lambda _s:{"price":100,"timestamp":stamp,"liquidity":1},100000)
    assert broker.create_order({"symbol":"INFY","side":"BUY","quantity":1},True)["status"]=="rejected"

def test_35_quantity_validation_works(stack):
    order=stack.broker.create_order({"symbol":"INFY","side":"BUY","quantity":0});assert order["status"]=="rejected" and "quantity" in order["rejection_reason"].lower()

def test_36_paper_order_never_calls_live_broker(stack):
    assert not hasattr(stack.broker,"kite") and buy(stack)["mode"]=="PAPER"

def test_37_llm_cannot_place_order_without_approval(stack):
    order=stack.broker.create_order({"symbol":"INFY","side":"BUY","quantity":1,"source":"assistant"});assert order["status"]=="pending_approval" and len(stack.broker.fills())==0

def test_38_main_app_composes_stage5_routes_and_terminal():
    import main
    app=main.create_flask_app();client=app.test_client();html=client.get("/").get_data(as_text=True)
    assert "pane-paper-ops" in html and "Paper Trading &amp; Portfolio Operations" in html
    account=client.get("/api/paper/account").get_json();assert account["success"] and "account_name" in account["data"]
    rules={rule.rule for rule in app.url_map.iter_rules()}
    assert {"/api/paper/account/snapshots","/api/paper/orders/<int:order_id>/approve","/api/paper/portfolio/summary","/api/paper/analytics/summary"} <= rules

def test_39_assistant_routes_paper_exit_and_strategy_review_to_drafts():
    assert route_command("Draft exit for my paper position") == "paper_exit_draft"
    assert route_command("Prepare a paper strategy review") == "paper_strategy_review"

def test_40_pending_buy_reserves_and_cancel_releases_cash(stack):
    order=stack.broker.create_order({"symbol":"INFY","side":"BUY","quantity":2,"order_type":"limit","limit_price":90})
    submitted=stack.broker.approve_order(order["id"]);assert submitted["status"]=="submitted" and stack.broker.account()["blocked_cash"]>0
    stack.broker.cancel_order(order["id"]);assert stack.broker.account()["blocked_cash"]==pytest.approx(0) and stack.broker.account()["buying_power"]==pytest.approx(stack.broker.account()["cash"])


def test_41_cost_inclusive_reservation_rejects_before_cash_invariant(stack):
    stack.broker.update_risk_settings({"max_position_value_pct":100,"max_per_symbol_exposure_pct":100,"max_order_value":1_000_000})
    order=stack.broker.create_order({"symbol":"INFY","side":"BUY","quantity":999})
    result=stack.broker.approve_order(order["id"])
    assert result["status"]=="rejected" and "including estimated fill costs" in result["rejection_reason"]
    assert stack.broker.account()["blocked_cash"]==0 and stack.broker.account()["cash"]==100_000
