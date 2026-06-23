from __future__ import annotations

import json
import re


def search_rows(database, query: str, filters: dict | None = None, limit: int = 30) -> list[dict]:
    filters=filters or {}; tokens=[token for token in re.findall(r"[A-Za-z0-9_]+",query.lower()) if len(token)>1]
    clauses=[]; params=[]
    if tokens:
        clauses.append("("+" OR ".join("LOWER(title || ' ' || summary || ' ' || keywords) LIKE ?" for _ in tokens)+")")
        params.extend(f"%{token}%" for token in tokens)
    result_type=filters.get("result_type") or filters.get("source")
    if result_type: clauses.append("result_type=?"); params.append(result_type)
    sql="SELECT * FROM app_search_index"+(" WHERE "+" AND ".join(clauses) if clauses else "")+" ORDER BY updated_at DESC LIMIT ?"
    rows=database.query(sql,(*params,limit)); results=[]
    for row in rows:
        metadata=json.loads(row["metadata_json"] or "{}"); haystack=f"{row['title']} {row['summary']} {row['keywords']}".lower()
        score=sum(token in haystack for token in tokens)/len(tokens) if tokens else 1.0
        if filters.get("symbol") and str(metadata.get("symbol","")).upper()!=str(filters["symbol"]).upper(): continue
        strategy_filter=filters.get("strategy") or filters.get("strategy_id")
        if strategy_filter and str(metadata.get("strategy_id","")).lower()!=str(strategy_filter).lower(): continue
        if filters.get("status") and metadata.get("status")!=filters["status"]: continue
        item_date=str(metadata.get("created_at") or metadata.get("updated_at") or metadata.get("exit_time") or "")[:10]
        if filters.get("date_from") and item_date and item_date < str(filters["date_from"]): continue
        if filters.get("date_to") and item_date and item_date > str(filters["date_to"]): continue
        actions=["open","ask_assistant","add_to_dashboard"]
        if row["result_type"] in {"strategy","combo"}: actions.extend(["run_backtest","edit_strategy"])
        if row["result_type"] in {"paper_trade","backtest_trade","paper_order"}: actions.append("view_trade_history")
        results.append({"result_type":row["result_type"],"source_id":row["source_id"],"title":row["title"],
                        "summary":row["summary"],"score":round(score,4),"source":row["result_type"],"metadata":metadata,
                        "actions":actions})
    return sorted(results,key=lambda item:item["score"],reverse=True)
