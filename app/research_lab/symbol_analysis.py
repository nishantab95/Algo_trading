from __future__ import annotations

from collections import defaultdict


def analyze_symbols(trades,requested_symbols=None):
    groups=defaultdict(list)
    for trade in trades:
        row=trade.to_dict() if hasattr(trade,"to_dict") else dict(trade);groups[row["symbol"]].append(row)
    total=sum(float(t.get("net_pnl",0)) for rows in groups.values() for t in rows);results=[]
    for symbol,rows in groups.items():
        pnl=[float(t.get("net_pnl",0)) for t in rows];wins=[x for x in pnl if x>0];losses=[x for x in pnl if x<0];gross_win=sum(wins);gross_loss=abs(sum(losses));contribution=(sum(pnl)/total*100) if total else 0;warnings=[]
        if contribution>60:warnings.append("One symbol produced most profits; concentration risk is high")
        results.append({"symbol":symbol,"trades_count":len(rows),"net_pnl":sum(pnl),"return_pct":sum(float(t.get("return_pct",0)) for t in rows),"win_rate":len(wins)/len(rows)*100,"profit_factor":gross_win/gross_loss if gross_loss else (999 if gross_win else 0),"expectancy":sum(pnl)/len(rows),"max_drawdown":0,"contribution_pct":contribution,"warnings":warnings})
    coverage=len(groups)/max(len(requested_symbols or groups),1)*100;warnings=[]
    if len(groups)<3:warnings.append("Too few symbols traded")
    if results and max(abs(r["contribution_pct"]) for r in results)>60:warnings.append("One-symbol concentration warning")
    skipped=sorted(set(requested_symbols or [])-set(groups))
    if skipped:warnings.append(f"{len(skipped)} requested symbols produced no completed trades")
    return results,{"symbol_coverage_pct":coverage,"traded_symbols":len(groups),"skipped_symbols":skipped,"warnings":warnings}
