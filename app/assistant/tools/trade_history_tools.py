from __future__ import annotations


class TradeHistoryService:
    def __init__(self,database): self.database=database
    def list(self,filters:dict|None=None,limit:int=200):
        filters=filters or {}; rows=[]
        for row in self.database.query("SELECT id,symbol,strategy_id,entry_time,exit_time,entry_price,exit_price,quantity,net_pnl,exit_reason FROM paper_trades ORDER BY exit_time DESC LIMIT ?",(limit,)):
            rows.append({**row,"trade_id":f"paper:{row['id']}","source":"paper_trade","return_pct":((row["exit_price"]/row["entry_price"]-1)*100 if row["entry_price"] else 0),"notes":None,"mistake_tags":[],"rule_followed":None})
        for row in self.database.query("SELECT id,symbol,strategy_id,entry_time,exit_time,entry_price,exit_price,quantity,net_pnl,return_pct,exit_reason FROM backtest_trades ORDER BY exit_time DESC LIMIT ?",(limit,)):
            rows.append({**row,"trade_id":f"backtest:{row['id']}","source":"backtest_trade","notes":None,"mistake_tags":[],"rule_followed":None})
        annotations={row["trade_id"]:row for row in self.database.query("SELECT * FROM trade_history_annotations")}
        for row in rows:
            annotation=annotations.get(row["trade_id"])
            if annotation:
                import json
                row["notes"]=annotation["notes"];row["mistake_tags"]=json.loads(annotation["tags_json"] or "[]")
        if filters.get("symbol"): rows=[r for r in rows if r["symbol"].upper()==str(filters["symbol"]).upper()]
        if filters.get("strategy_id"): rows=[r for r in rows if r.get("strategy_id")==filters["strategy_id"]]
        if filters.get("outcome")=="winning": rows=[r for r in rows if r["net_pnl"]>0]
        if filters.get("outcome")=="losing": rows=[r for r in rows if r["net_pnl"]<0]
        return sorted(rows,key=lambda r:str(r.get("exit_time") or ""),reverse=True)[:limit]
    def get(self,trade_id):
        rows=[row for row in self.list(limit=10000) if row["trade_id"]==trade_id]
        if not rows: raise ValueError(f"Unknown trade: {trade_id}")
        return rows[0]
    def annotate(self,payload):
        import json
        from datetime import datetime,timezone
        trade_id=str(payload["trade_id"]);self.get(trade_id);existing=self.database.query("SELECT * FROM trade_history_annotations WHERE trade_id=?",(trade_id,));now=datetime.now(timezone.utc).isoformat();notes=payload.get("note",existing[0]["notes"] if existing else "");tags=payload.get("tags",json.loads(existing[0]["tags_json"]) if existing else [])
        with self.database.transaction() as c:c.execute("""INSERT INTO trade_history_annotations(trade_id,notes,tags_json,created_at,updated_at) VALUES(?,?,?,?,?)
            ON CONFLICT(trade_id) DO UPDATE SET notes=excluded.notes,tags_json=excluded.tags_json,updated_at=excluded.updated_at""",(trade_id,notes,json.dumps(tags),now,now))
        return self.get(trade_id)
