from __future__ import annotations

import json
from collections import Counter, defaultdict


class PaperAnalytics:
    def __init__(self,broker): self.broker=broker; self.database=broker.database
    def summary(self,filters=None):
        trades=self.broker.journal(filters); snapshots=list(reversed(self.broker.snapshots(5000))); pnl=[float(t["net_pnl"]) for t in trades]; wins=[x for x in pnl if x>0]; losses=[x for x in pnl if x<0]; total=sum(pnl); gross_win=sum(wins); gross_loss=abs(sum(losses)); costs=sum(float(t["costs"]) for t in trades); account=self.broker.account()
        profit_factor=gross_win/gross_loss if gross_loss else (float("inf") if gross_win else 0)
        holding=sum(float(t["holding_period"]) for t in trades)/len(trades) if trades else 0
        followed=[t for t in trades if t["rule_followed"]!="unknown"]
        setup=defaultdict(list)
        for t in trades:setup[str(t.get("setup_type") or "unassigned")].append(t)
        metrics={"trades":len(trades),"total_net_pnl":total,"total_return_pct":total/account["starting_capital"]*100 if account["starting_capital"] else 0,"daily_return_pct":snapshots[-1]["daily_return_pct"] if snapshots else 0,"win_rate":len(wins)/len(trades)*100 if trades else 0,"profit_factor":profit_factor,"expectancy":total/len(trades) if trades else 0,"average_win":gross_win/len(wins) if wins else 0,"average_loss":sum(losses)/len(losses) if losses else 0,"payoff_ratio":(gross_win/len(wins))/(abs(sum(losses)/len(losses))) if wins and losses else 0,"max_drawdown":max([float(s["drawdown_pct"]) for s in snapshots] or [0]),"drawdown_duration":self._drawdown_duration(snapshots),"best_trade":max(pnl,default=0),"worst_trade":min(pnl,default=0),"average_holding_period":holding,"cost_drag":costs/(abs(total)+costs)*100 if total or costs else 0,"total_costs":costs,"open_risk":sum(float(p["risk_amount"]) for p in self.broker.positions()),"realized_vs_unrealized_pnl":{"realized":account["realized_pnl"],"unrealized":account["unrealized_pnl"]},"rule_following_rate":sum(t["rule_followed"]=="followed" for t in followed)/len(followed)*100 if followed else 0,"pnl_by_strategy":self.grouped("strategy_id"),"pnl_by_symbol":self.grouped("symbol"),"pnl_by_source":self.grouped("source"),"win_rate_by_setup":{name:sum(t["net_pnl"]>0 for t in rows)/len(rows)*100 for name,rows in setup.items()},"mistake_frequency":self.mistakes()}
        metrics["warnings"]=self.warnings(metrics,trades);return metrics
    def _drawdown_duration(self,snapshots):
        longest=current=0
        for row in snapshots:
            current=current+1 if row["drawdown_pct"]>0 else 0;longest=max(longest,current)
        return longest
    def grouped(self,key):
        groups=defaultdict(list)
        for trade in self.broker.journal():groups[str(trade.get(key) or "unassigned")].append(trade)
        return [{key:name,"trades":len(rows),"net_pnl":sum(r["net_pnl"] for r in rows),"win_rate":sum(r["net_pnl"]>0 for r in rows)/len(rows)*100} for name,rows in groups.items()]
    def mistakes(self):
        counts=Counter()
        for trade in self.broker.journal():counts.update(json.loads(trade["mistake_tags_json"] or "[]"))
        return [{"tag":tag,"count":count} for tag,count in counts.most_common()]
    def warnings(self,m,trades):
        warnings=[]
        if len(trades)<20:warnings.append("Sample size is too low for a promotion decision")
        if m["total_net_pnl"]<0:warnings.append("Paper result is losing after costs")
        if m["max_drawdown"]>20:warnings.append("Paper drawdown exceeds 20%")
        if trades and m["best_trade"]>max(abs(m["total_net_pnl"]),1)*.5:warnings.append("One trade dominates the result")
        if m["cost_drag"]>20:warnings.append("Trading costs are materially high")
        if m["payoff_ratio"] and m["payoff_ratio"]<1:warnings.append("Paper risk-reward is poor")
        if sum(x["count"] for x in m["mistake_frequency"])>len(trades)*.5:warnings.append("Mistake frequency is high")
        if m["rule_following_rate"] and m["rule_following_rate"]<80:warnings.append("Rule-following rate is below 80%")
        return warnings

    def promotion_review(self,strategy_id,criteria=None,persist=True):
        criteria={"minimum_paper_trades":20,"minimum_paper_days":30,"positive_expectancy":True,"profit_factor_threshold":1.2,"max_drawdown_threshold":20,"cost_drag_threshold":20,"rule_following_rate_threshold":80,"no_critical_risk_violations":True,**(criteria or {})}
        trades=self.broker.journal({"strategy_id":strategy_id}); metrics=self.summary({"strategy_id":strategy_id}); dates=[t["exit_time"] for t in trades if t.get("exit_time")]; days=0
        if dates: days=max(1,(max(dates)[:10]!=min(dates)[:10])+1)
        warnings=[]
        if len(trades)<criteria["minimum_paper_trades"]:warnings.append("Trade count is too low")
        if days<criteria["minimum_paper_days"]:warnings.append("Paper-testing duration is too short")
        if criteria["positive_expectancy"] and metrics["expectancy"]<=0:warnings.append("Expectancy is not positive")
        if metrics["profit_factor"]<criteria["profit_factor_threshold"]:warnings.append("Profit factor is below threshold")
        if metrics["max_drawdown"]>criteria["max_drawdown_threshold"]:warnings.append("Drawdown exceeds threshold")
        if metrics["cost_drag"]>criteria["cost_drag_threshold"]:warnings.append("Cost drag exceeds threshold")
        if metrics["rule_following_rate"]<criteria["rule_following_rate_threshold"]:warnings.append("Rule-following rate is below threshold")
        critical=self.database.query("SELECT COUNT(*) count FROM risk_events WHERE strategy_id=? AND severity='critical'",(strategy_id,))[0]["count"]
        if criteria["no_critical_risk_violations"] and critical:warnings.append("Critical paper risk violations are present")
        status="candidate_for_tiny_live" if not warnings else ("needs_more_data" if any("too low" in w or "too short" in w for w in warnings) else "rejected")
        result={"strategy_id":strategy_id,"account_id":self.broker.account_id,"status":"paper_testing","trades_count":len(trades),"days_tested":days,"net_pnl":metrics["total_net_pnl"],"expectancy":metrics["expectancy"],"profit_factor":metrics["profit_factor"],"max_drawdown":metrics["max_drawdown"],"cost_drag":metrics["cost_drag"],"rule_following_rate":metrics["rule_following_rate"],"promotion_status":status,"warnings":warnings}
        if persist:
            from app.paper.broker import _now
            now=_now()
            with self.database.transaction() as c:c.execute("INSERT INTO paper_strategy_reviews(strategy_id,account_id,status,trades_count,days_tested,net_pnl,expectancy,profit_factor,max_drawdown,cost_drag,rule_following_rate,promotion_status,warnings_json,reviewed_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(strategy_id,self.broker.account_id,result["status"],result["trades_count"],days,result["net_pnl"],result["expectancy"],result["profit_factor"],result["max_drawdown"],result["cost_drag"],result["rule_following_rate"],status,json.dumps(warnings),now,now))
        return result
