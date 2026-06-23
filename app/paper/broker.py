from __future__ import annotations

import json, uuid
from datetime import datetime, timezone
from typing import Callable

from app.paper.schemas import ORDER_TYPES, PaperRiskSettings


def _now() -> str: return datetime.now(timezone.utc).isoformat()


class PaperOperationsBroker:
    """Approval-gated, long-only paper broker. It has no live-broker dependency."""

    def __init__(self,database,price_provider:Callable[[str],float|dict],starting_capital:float=1_000_000,account_id:str="default"):
        self.database,self.price_provider,self.account_id=database,price_provider,account_id
        self._ensure_account(float(starting_capital))

    def _ensure_account(self,capital):
        now=_now(); settings=PaperRiskSettings()
        with self.database.transaction() as c:
            c.execute("""INSERT OR IGNORE INTO paper_accounts(id,account_name,starting_capital,cash,total_equity,buying_power,peak_equity,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",(self.account_id,"Default Paper Account",capital,capital,capital,capital,capital,"active",now,now))
            c.execute("INSERT OR IGNORE INTO paper_risk_settings(account_id,config_json,updated_at) VALUES(?,?,?)",(self.account_id,json.dumps(settings.to_dict()),now))
        if not self.snapshots(): self.snapshot()

    def risk_settings(self):
        row=self.database.query("SELECT config_json FROM paper_risk_settings WHERE account_id=?",(self.account_id,))[0]
        return PaperRiskSettings(**json.loads(row["config_json"]))

    def update_risk_settings(self,changes):
        merged={**self.risk_settings().to_dict(),**changes}; settings=PaperRiskSettings(**merged)
        if settings.max_open_positions<1 or settings.max_order_value<=0: raise ValueError("Invalid paper risk settings")
        with self.database.transaction() as c:c.execute("UPDATE paper_risk_settings SET config_json=?,updated_at=? WHERE account_id=?",(json.dumps(settings.to_dict()),_now(),self.account_id))
        return settings.to_dict()

    def account(self): return self.database.query("SELECT * FROM paper_accounts WHERE id=?",(self.account_id,))[0]
    def orders(self,limit=500): return self.database.query("SELECT * FROM paper_orders WHERE account_id=? ORDER BY id DESC LIMIT ?",(self.account_id,limit))
    def order(self,order_id):
        rows=self.database.query("SELECT * FROM paper_orders WHERE id=? AND account_id=?",(int(order_id),self.account_id))
        if not rows: raise ValueError("Unknown paper order")
        return rows[0]
    def fills(self,limit=500): return self.database.query("SELECT * FROM paper_fills ORDER BY id DESC LIMIT ?",(limit,))
    def positions(self,open_only=True):
        sql="SELECT * FROM paper_positions WHERE account_id=?"+(" AND status='OPEN'" if open_only else "")+" ORDER BY id"
        return self.database.query(sql,(self.account_id,))
    def position(self,position_id):
        rows=self.database.query("SELECT * FROM paper_positions WHERE id=? AND account_id=?",(int(position_id),self.account_id))
        if not rows: raise ValueError("Unknown paper position")
        return rows[0]
    def snapshots(self,limit=500): return self.database.query("SELECT * FROM paper_account_snapshots WHERE account_id=? ORDER BY id DESC LIMIT ?",(self.account_id,limit))

    def _quote(self,symbol):
        raw=self.price_provider(symbol)
        if isinstance(raw,dict):
            price=float(raw.get("price",raw.get("close",0))); stamp=raw.get("timestamp"); liquidity=float(raw.get("liquidity",raw.get("volume",1)))
        else: price=float(raw); stamp=None; liquidity=1.0
        return {"price":price,"timestamp":stamp,"liquidity":liquidity}

    def create_order(self,payload,approved_by_user=False):
        symbol=str(payload.get("symbol","")).strip().upper(); side=str(payload.get("side","BUY")).upper(); quantity=int(payload.get("quantity",0) or 0)
        order_type=str(payload.get("order_type","market")).lower(); now=_now()
        if not symbol: raise ValueError("Symbol is required")
        if side not in {"BUY","SELL"}: raise ValueError("Side must be BUY or SELL")
        if order_type not in ORDER_TYPES: raise ValueError("Unsupported paper order type")
        requested=payload.get("requested_price"); quote=None
        try: quote=self._quote(symbol); requested=float(requested if requested is not None else quote["price"])
        except Exception: requested=0.0
        client_id=str(payload.get("client_order_id") or uuid.uuid4())
        existing=self.database.query("SELECT * FROM paper_orders WHERE client_order_id=?",(client_id,))
        if existing:return existing[0]
        status="pending_approval" if quantity>0 else "rejected"; rejection=None if quantity>0 else "Quantity must be positive"
        estimated=max(requested,0)*max(quantity,0)
        settings=self.risk_settings(); costs=estimated*(settings.fee_bps+settings.spread_bps)/10000
        with self.database.transaction() as c:
            cur=c.execute("""INSERT INTO paper_orders(client_order_id,broker_order_id,mode,account_id,strategy_id,combo_id,assistant_action_id,source,symbol,side,quantity,order_type,product_type,requested_price,limit_price,stop_price,estimated_value,estimated_costs,status,rejection_reason,approval_required,approved_by_user,metadata_json,created_at,updated_at)
                VALUES(?,NULL,'PAPER',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0,?,?,?)""",(client_id,self.account_id,payload.get("strategy_id"),payload.get("combo_id"),payload.get("assistant_action_id"),payload.get("source","manual"),symbol,side,quantity,order_type,payload.get("product_type","delivery"),requested,payload.get("limit_price"),payload.get("stop_price"),estimated,costs,status,rejection,json.dumps(payload.get("metadata",{})),now,now))
            order_id=cur.lastrowid; self._event(c,order_id,None,status,rejection)
            if payload.get("expires_at"):c.execute("UPDATE paper_orders SET expires_at=? WHERE id=?",(payload["expires_at"],order_id))
        if status=="rejected": self._risk_event("INVALID_QUANTITY",rejection,symbol,payload.get("strategy_id")); return self.order(order_id)
        return self.approve_order(order_id) if approved_by_user else self.order(order_id)

    def approve_order(self,order_id,actor="user"):
        if actor!="user": raise PermissionError("Only the user can approve a paper order")
        order=self.order(order_id)
        if order["status"]!="pending_approval": raise ValueError(f"Order cannot be approved from {order['status']}")
        quote=self._quote(order["symbol"]); decision=self._risk(order,quote)
        if not decision["approved"]:
            with self.database.transaction() as c:self._transition(c,order["id"],order["status"],"rejected",decision["reason"])
            self._risk_event(decision["rule_id"],decision["reason"],order["symbol"],order.get("strategy_id"),decision)
            return self.order(order_id)
        now=_now()
        with self.database.transaction() as c:
            c.execute("UPDATE paper_orders SET approved_by_user=1,approved_at=?,updated_at=? WHERE id=?",(now,now,order["id"]))
            if order["side"]=="BUY":c.execute("UPDATE paper_accounts SET blocked_cash=blocked_cash+?,buying_power=cash-(blocked_cash+?),updated_at=? WHERE id=?",(order["estimated_value"]+order["estimated_costs"],order["estimated_value"]+order["estimated_costs"],now,self.account_id))
            self._transition(c,order["id"],"pending_approval","approved","Explicit user approval")
            self._transition(c,order["id"],"approved","submitted","Submitted to paper fill simulator")
        return self.process_order(order_id,quote)

    def _risk(self,order,quote):
        s=self.risk_settings(); account=self.account(); price=quote["price"]; value=price*order["quantity"]
        def reject(rule,reason,severity="high"): return {"approved":False,"severity":severity,"rule_id":rule,"reason":reason,"context":{"order_value":value}}
        if s.kill_switch:return reject("KILL_SWITCH","Paper kill switch is active","critical")
        if not order["approved_by_user"] and order["status"]!="pending_approval":return reject("APPROVAL_REQUIRED","Explicit user approval is required")
        if order["quantity"]<=0:return reject("INVALID_QUANTITY","Quantity must be positive")
        if price<s.minimum_price or price>s.maximum_price:return reject("PRICE_RANGE","Price is outside the configured range")
        if quote["liquidity"]<s.minimum_liquidity:return reject("LIQUIDITY","Liquidity threshold is not met")
        if quote.get("timestamp"):
            try:
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(str(quote["timestamp"]).replace("Z","+00:00"))).total_seconds()
                if age>s.stale_after_seconds:return reject("STALE_DATA","Price data is stale")
            except ValueError:return reject("STALE_DATA","Price timestamp is invalid")
        if value>s.max_order_value:return reject("MAX_ORDER_VALUE","Order value exceeds configured maximum")
        if order["side"]=="BUY":
            if account["daily_pnl"]<=-s.max_daily_loss:return reject("MAX_DAILY_LOSS","Daily paper loss limit reached","critical")
            if account["weekly_pnl"]<=-s.max_weekly_loss:return reject("MAX_WEEKLY_LOSS","Weekly paper loss limit reached","critical")
            if value+order["estimated_costs"]>account["cash"]-account["blocked_cash"]:return reject("INSUFFICIENT_CASH","Insufficient available paper cash")
            current=[p for p in self.positions() if p["symbol"]==order["symbol"]]
            if current and not s.allow_duplicate_position:return reject("DUPLICATE_POSITION","Duplicate paper position is not allowed")
            if current and price<current[0]["avg_price"] and not s.allow_averaging_down:return reject("AVERAGING_DOWN","Averaging down is not allowed")
            if len(self.positions())>=s.max_open_positions and not current:return reject("MAX_POSITIONS","Maximum open positions reached")
            if value>account["total_equity"]*s.max_position_value_pct/100:return reject("MAX_POSITION_VALUE","Position value limit exceeded")
            current_symbol=sum(p["market_value"] for p in current)
            if current_symbol+value>account["total_equity"]*s.max_per_symbol_exposure_pct/100:return reject("MAX_SYMBOL_EXPOSURE","Per-symbol exposure limit exceeded")
            strategy_value=sum(p["market_value"] for p in self.positions() if p.get("strategy_id")==order.get("strategy_id"))
            if order.get("strategy_id") and strategy_value+value>account["total_equity"]*s.max_per_strategy_exposure_pct/100:return reject("MAX_STRATEGY_EXPOSURE","Per-strategy exposure limit exceeded")
            if s.require_stop_for_strategy and order.get("strategy_id") and not order.get("stop_price"):return reject("STOP_REQUIRED","A stop loss is required for strategy orders")
        else:
            current=[p for p in self.positions() if p["symbol"]==order["symbol"]]
            if not current or current[0]["quantity"]<order["quantity"]:return reject("NO_POSITION","No sufficient long position exists")
        return {"approved":True,"severity":"info","rule_id":"APPROVED","reason":"Approved","context":{"order_value":value}}

    def process_order(self,order_id,quote=None):
        order=self.order(order_id)
        if order["status"]!="submitted":return order
        quote=quote or self._quote(order["symbol"]); price=quote["price"]; kind=order["order_type"]
        metadata=json.loads(order.get("metadata_json") or "{}"); can_fill=False
        if kind=="market":can_fill=True
        elif kind=="limit":can_fill=price<=order["limit_price"] if order["side"]=="BUY" else price>=order["limit_price"]
        elif kind=="stop":can_fill=price>=order["stop_price"] if order["side"]=="BUY" else price<=order["stop_price"]
        elif kind=="stop_limit":
            triggered=metadata.get("stop_triggered") or (price>=order["stop_price"] if order["side"]=="BUY" else price<=order["stop_price"])
            metadata["stop_triggered"]=bool(triggered); can_fill=triggered and (price<=order["limit_price"] if order["side"]=="BUY" else price>=order["limit_price"])
            with self.database.transaction() as c:c.execute("UPDATE paper_orders SET metadata_json=?,updated_at=? WHERE id=?",(json.dumps(metadata),_now(),order["id"]))
        if can_fill:self._fill(order,price)
        return self.order(order_id)

    def process_open_orders(self):
        results=[]
        for order in self.database.query("SELECT * FROM paper_orders WHERE account_id=? AND status='submitted' ORDER BY id",(self.account_id,)):
            if order.get("expires_at") and order["expires_at"]<=_now():
                with self.database.transaction() as c:
                    self._release_reserve(c,order);self._transition(c,order["id"],"submitted","expired","Order expired")
                results.append(self.order(order["id"])); continue
            results.append(self.process_order(order["id"]))
        return results

    def cancel_order(self,order_id):
        order=self.order(order_id)
        if order["status"] not in {"draft","pending_approval","approved","submitted"}:raise ValueError("Only unfilled paper orders can be cancelled")
        with self.database.transaction() as c:
            self._release_reserve(c,order)
            self._transition(c,order["id"],order["status"],"cancelled","Cancelled by user")
            c.execute("UPDATE paper_orders SET cancelled_at=? WHERE id=?",(_now(),order["id"]))
        return self.order(order_id)

    def _fill(self,order,market_price):
        s=self.risk_settings(); direction=1 if order["side"]=="BUY" else -1
        fill_price=market_price*(1+direction*(s.slippage_bps+s.spread_bps/2)/10000); notional=fill_price*order["quantity"]
        slippage=abs(fill_price-market_price)*order["quantity"]; spread=market_price*order["quantity"]*s.spread_bps/10000; fees=notional*s.fee_bps/10000; total_cost=slippage+spread+fees; now=_now()
        with self.database.transaction() as c:
            account=c.execute("SELECT * FROM paper_accounts WHERE id=?",(self.account_id,)).fetchone()
            position=c.execute("SELECT * FROM paper_positions WHERE account_id=? AND symbol=? AND status='OPEN'",(self.account_id,order["symbol"])).fetchone()
            if order["side"]=="BUY":
                debit=notional+fees
                if debit>account["cash"]:raise ValueError("Cash invariant violated by paper fill")
                if position:
                    new_qty=position["quantity"]+order["quantity"]; avg=(position["avg_price"]*position["quantity"]+fill_price*order["quantity"])/new_qty
                    c.execute("""UPDATE paper_positions SET quantity=?,avg_price=?,last_price=?,current_price=?,market_value=?,cost_basis=?,highest_price=?,lowest_price=?,unrealized_pnl=?,unrealized_pnl_pct=?,updated_at=? WHERE id=?""",(new_qty,avg,fill_price,fill_price,new_qty*fill_price,new_qty*avg,max(position["highest_price"],fill_price),min(position["lowest_price"] or fill_price,fill_price),(fill_price-avg)*new_qty,(fill_price/avg-1)*100,now,position["id"]))
                else:
                    c.execute("""INSERT INTO paper_positions(symbol,quantity,avg_price,last_price,highest_price,unrealized_pnl,opened_at,updated_at,status,account_id,strategy_id,combo_id,current_price,market_value,cost_basis,unrealized_pnl_pct,realized_pnl,lowest_price,stop_loss,target,trailing_stop,entry_reason,risk_amount,source,entry_order_id)
                        VALUES(?,?,?,?,?,?,?,?,'OPEN',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(order["symbol"],order["quantity"],fill_price,fill_price,fill_price,0,now,now,self.account_id,order.get("strategy_id"),order.get("combo_id"),fill_price,notional,notional,0,0,fill_price,order.get("stop_price"),json.loads(order.get("metadata_json") or "{}").get("target"),json.loads(order.get("metadata_json") or "{}").get("trailing_stop"),json.loads(order.get("metadata_json") or "{}").get("entry_reason"),0,order.get("source","manual"),order["id"]))
                c.execute("UPDATE paper_accounts SET cash=cash-?,updated_at=? WHERE id=?",(debit,now,self.account_id))
            else:
                if not position or position["quantity"]<order["quantity"]:raise ValueError("No sufficient position for paper sell")
                remaining=position["quantity"]-order["quantity"]; gross=(fill_price-position["avg_price"])*order["quantity"]; net=gross-fees
                entry_fill=c.execute("SELECT fees,quantity FROM paper_fills WHERE order_id=? ORDER BY id LIMIT 1",(position["entry_order_id"],)).fetchone();entry_fee_share=(entry_fill["fees"]*order["quantity"]/entry_fill["quantity"]) if entry_fill and entry_fill["quantity"] else 0;trade_costs=fees+entry_fee_share;net=gross-trade_costs
                if remaining:c.execute("UPDATE paper_positions SET quantity=?,last_price=?,current_price=?,market_value=?,cost_basis=?,realized_pnl=realized_pnl+?,updated_at=? WHERE id=?",(remaining,fill_price,fill_price,remaining*fill_price,remaining*position["avg_price"],net,now,position["id"]))
                else:c.execute("UPDATE paper_positions SET quantity=0,status='CLOSED',closed_at=?,last_price=?,current_price=?,market_value=0,unrealized_pnl=0,unrealized_pnl_pct=0,realized_pnl=realized_pnl+?,updated_at=? WHERE id=?",(now,fill_price,fill_price,net,now,position["id"]))
                c.execute("UPDATE paper_accounts SET cash=cash+?,realized_pnl=realized_pnl+?,updated_at=? WHERE id=?",(notional-fees,net,now,self.account_id))
                opened=datetime.fromisoformat(position["opened_at"]); hold=(datetime.fromisoformat(now)-opened).total_seconds()/86400
                meta=json.loads(order.get("metadata_json") or "{}")
                c.execute("""INSERT INTO paper_trade_journal(account_id,symbol,strategy_id,combo_id,source,entry_order_id,exit_order_id,entry_time,exit_time,entry_price,exit_price,quantity,gross_pnl,costs,net_pnl,return_pct,holding_period,entry_reason,exit_reason,mistake_tags_json,notes,rule_followed,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'[]','','unknown',?,?)""",(self.account_id,order["symbol"],position["strategy_id"],position["combo_id"],order.get("source","manual"),position["entry_order_id"],order["id"],position["opened_at"],now,position["avg_price"],fill_price,order["quantity"],gross,trade_costs,net,(fill_price/position["avg_price"]-1)*100,hold,position["entry_reason"],meta.get("exit_reason","manual_exit"),now,now))
            c.execute("INSERT INTO paper_fills(order_id,symbol,side,quantity,requested_price,fill_price,slippage,spread_cost,fees,total_cost,fill_time,fill_reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(order["id"],order["symbol"],order["side"],order["quantity"],order["requested_price"],fill_price,slippage,spread,fees,total_cost,now,"deterministic_paper_fill",now))
            self._release_reserve(c,order)
            c.execute("UPDATE paper_orders SET fill_price=?,filled_at=? WHERE id=?",(fill_price,now,order["id"])); self._transition(c,order["id"],"submitted","filled","Simulated fill")
            self._revalue_connection(c,now)
        self.snapshot(); return self.order(order["id"])

    def mark_to_market(self):
        now=_now()
        with self.database.transaction() as c:
            for p in c.execute("SELECT * FROM paper_positions WHERE account_id=? AND status='OPEN'",(self.account_id,)).fetchall():
                price=self._quote(p["symbol"])["price"]; pnl=(price-p["avg_price"])*p["quantity"]
                c.execute("UPDATE paper_positions SET last_price=?,current_price=?,market_value=?,unrealized_pnl=?,unrealized_pnl_pct=?,highest_price=?,lowest_price=?,updated_at=? WHERE id=?",(price,price,price*p["quantity"],pnl,(price/p["avg_price"]-1)*100,max(p["highest_price"],price),min(p["lowest_price"] or price,price),now,p["id"]))
            self._revalue_connection(c,now)
        return self.snapshot()

    def _revalue_connection(self,c,now):
        positions=c.execute("SELECT * FROM paper_positions WHERE account_id=? AND status='OPEN'",(self.account_id,)).fetchall(); account=c.execute("SELECT * FROM paper_accounts WHERE id=?",(self.account_id,)).fetchone()
        value=sum(p["quantity"]*(p["current_price"] or p["last_price"]) for p in positions); unreal=sum(p["unrealized_pnl"] for p in positions); equity=account["cash"]+value; peak=max(account["peak_equity"],equity); drawdown=(peak-equity)/peak*100 if peak else 0
        if account["cash"]<-0.00001:raise ValueError("Paper cash cannot be negative")
        period_pnl=equity-account["starting_capital"]
        c.execute("UPDATE paper_accounts SET unrealized_pnl=?,total_equity=?,buying_power=cash-blocked_cash,gross_exposure=?,net_exposure=?,open_positions_count=?,daily_pnl=?,weekly_pnl=?,monthly_pnl=?,peak_equity=?,max_drawdown=?,updated_at=? WHERE id=?",(unreal,equity,value,value,len(positions),period_pnl,period_pnl,period_pnl,peak,max(account["max_drawdown"],drawdown),now,self.account_id))

    def snapshot(self):
        now=_now(); a=self.account(); position_value=a["total_equity"]-a["cash"]; orders=self.database.query("SELECT COUNT(*) count FROM paper_orders WHERE account_id=?",(self.account_id,))[0]["count"]; trades=self.database.query("SELECT COUNT(*) count FROM paper_trade_journal WHERE account_id=?",(self.account_id,))[0]["count"]; costs=self.database.query("SELECT COALESCE(SUM(fees),0) total FROM paper_fills f JOIN paper_orders o ON o.id=f.order_id WHERE o.account_id=?",(self.account_id,))[0]["total"]; daily_return=a["daily_pnl"]/a["starting_capital"]*100 if a["starting_capital"] else 0; drawdown=(a["peak_equity"]-a["total_equity"])/a["peak_equity"]*100 if a["peak_equity"] else 0
        with self.database.transaction() as c:
            cur=c.execute("INSERT INTO paper_account_snapshots(account_id,snapshot_time,cash,position_value,total_equity,realized_pnl,unrealized_pnl,daily_pnl,daily_return_pct,drawdown_pct,open_positions,orders_count,trades_count,costs,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(self.account_id,now,a["cash"],position_value,a["total_equity"],a["realized_pnl"],a["unrealized_pnl"],a["daily_pnl"],daily_return,drawdown,a["open_positions_count"],orders,trades,costs,now)); snapshot_id=cur.lastrowid
        return self.database.query("SELECT * FROM paper_account_snapshots WHERE id=?",(snapshot_id,))[0]

    def exit_position(self,position_id,quantity=None,reason="manual_exit",approved_by_user=False,source="manual"):
        if not approved_by_user:raise PermissionError("Explicit user approval is required for paper exits")
        p=self.position(position_id); qty=int(quantity or p["quantity"])
        if qty<=0 or qty>p["quantity"]:raise ValueError("Invalid exit quantity")
        return self.create_order({"symbol":p["symbol"],"side":"SELL","quantity":qty,"order_type":"market","strategy_id":p["strategy_id"],"combo_id":p["combo_id"],"source":source,"metadata":{"exit_reason":reason}},approved_by_user=True)

    def update_position_risk(self,position_id,changes):
        allowed={"stop_loss","target","trailing_stop"}
        if set(changes)-allowed:raise ValueError("Only stop, target, and trailing stop may be changed")
        assignments=",".join(f"{key}=?" for key in changes)
        with self.database.transaction() as c:c.execute(f"UPDATE paper_positions SET {assignments},updated_at=? WHERE id=?",(*changes.values(),_now(),int(position_id)))
        return self.position(position_id)

    def exit_sweep(self):
        self.mark_to_market(); exits=[]
        for p in list(self.positions()):
            price=p["current_price"]; reason=None
            if p["stop_loss"] is not None and price<=p["stop_loss"]:reason="stop_loss_exit"
            elif p["target"] is not None and price>=p["target"]:reason="target_exit"
            elif p["trailing_stop"] is not None and price<=p["highest_price"]*(1-p["trailing_stop"]/100):reason="trailing_stop_exit"
            if reason:exits.append(self.exit_position(p["id"],reason=reason,approved_by_user=True,source="exit_manager"))
        return {"entries_created":0,"exits_created":len(exits),"orders":exits}

    def reset(self,confirm=False):
        if confirm is not True:raise PermissionError("Explicit reset confirmation is required")
        now=_now(); archive={"account":self.account(),"positions":self.positions(False),"orders":self.orders(),"fills":self.fills(),"journal":self.journal()}
        with self.database.transaction() as c:
            c.execute("INSERT INTO paper_reset_archives(account_id,snapshot_json,archived_at) VALUES(?,?,?)",(self.account_id,json.dumps(archive,default=str),now))
            c.execute("DELETE FROM paper_fills WHERE order_id IN (SELECT id FROM paper_orders WHERE account_id=?)",(self.account_id,));c.execute("DELETE FROM paper_order_events WHERE order_id IN (SELECT id FROM paper_orders WHERE account_id=?)",(self.account_id,));c.execute("DELETE FROM paper_positions WHERE account_id=?",(self.account_id,)); c.execute("DELETE FROM paper_orders WHERE account_id=?",(self.account_id,)); c.execute("DELETE FROM paper_trade_journal WHERE account_id=?",(self.account_id,)); c.execute("DELETE FROM paper_account_snapshots WHERE account_id=?",(self.account_id,))
            c.execute("UPDATE paper_accounts SET cash=starting_capital,blocked_cash=0,realized_pnl=0,unrealized_pnl=0,total_equity=starting_capital,buying_power=starting_capital,gross_exposure=0,net_exposure=0,open_positions_count=0,daily_pnl=0,weekly_pnl=0,monthly_pnl=0,max_drawdown=0,peak_equity=starting_capital,updated_at=? WHERE id=?",(now,self.account_id))
        self.snapshot(); return {"reset":True,"archived_at":now,"account":self.account()}

    def journal(self,filters=None,limit=500):
        filters=filters or {}; rows=self.database.query("SELECT * FROM paper_trade_journal WHERE account_id=? ORDER BY id DESC LIMIT ?",(self.account_id,limit))
        if filters.get("strategy_id"):rows=[r for r in rows if r["strategy_id"]==filters["strategy_id"]]
        if filters.get("symbol"):rows=[r for r in rows if r["symbol"]==str(filters["symbol"]).upper()]
        if filters.get("source"):rows=[r for r in rows if r["source"]==filters["source"]]
        if filters.get("outcome")=="winning":rows=[r for r in rows if r["net_pnl"]>0]
        if filters.get("outcome")=="losing":rows=[r for r in rows if r["net_pnl"]<0]
        return rows

    def update_journal(self,trade_id,changes):
        allowed={"notes","mistake_tags_json","rule_followed","setup_type","confidence"}
        if set(changes)-allowed:raise ValueError("Unsupported journal update")
        if "rule_followed" in changes and changes["rule_followed"] not in {"followed","not_followed","unknown"}:raise ValueError("Invalid rule-followed value")
        if isinstance(changes.get("mistake_tags_json"),list):changes["mistake_tags_json"]=json.dumps(changes["mistake_tags_json"])
        assignments=",".join(f"{key}=?" for key in changes)
        with self.database.transaction() as c:c.execute(f"UPDATE paper_trade_journal SET {assignments},updated_at=? WHERE id=? AND account_id=?",(*changes.values(),_now(),int(trade_id),self.account_id))
        rows=self.database.query("SELECT * FROM paper_trade_journal WHERE id=? AND account_id=?",(int(trade_id),self.account_id))
        if not rows:raise ValueError("Unknown paper journal trade")
        return rows[0]

    def _event(self,c,order_id,from_status,to_status,reason=None):c.execute("INSERT INTO paper_order_events(order_id,from_status,to_status,reason,created_at) VALUES(?,?,?,?,?)",(order_id,from_status,to_status,reason,_now()))
    def _release_reserve(self,c,order):
        if order["side"]=="BUY" and order["status"] in {"approved","submitted"}:
            reserve=order["estimated_value"]+order["estimated_costs"]
            c.execute("UPDATE paper_accounts SET blocked_cash=MAX(blocked_cash-?,0),buying_power=cash-MAX(blocked_cash-?,0),updated_at=? WHERE id=?",(reserve,reserve,_now(),self.account_id))
    def _transition(self,c,order_id,from_status,to_status,reason=None):
        c.execute("UPDATE paper_orders SET status=?,rejection_reason=CASE WHEN ?='rejected' THEN ? ELSE rejection_reason END,updated_at=? WHERE id=?",(to_status,to_status,reason,_now(),order_id));self._event(c,order_id,from_status,to_status,reason)
    def _risk_event(self,rule_id,reason,symbol,strategy_id=None,context=None):
        with self.database.transaction() as c:c.execute("INSERT INTO risk_events(severity,event_type,symbol,strategy_id,reason,context_json,created_at) VALUES(?,?,?,?,?,?,?)",((context or {}).get("severity","high"),"PAPER_ORDER_REJECTED",symbol,strategy_id,reason,json.dumps({"rule_id":rule_id,**((context or {}).get("context",{}))}),_now()))
