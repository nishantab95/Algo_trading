from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config_settings as cfg
from app.backtesting.benchmark import apply_benchmark
from app.backtesting.engine import BacktestEngine
from app.backtesting.metrics import calculate_metrics, metric_breakdown
from app.backtesting.models import BacktestConfig, BacktestResult
from app.backtesting.reports import export_result
from app.backtesting.walk_forward import run_walk_forward
from app.core.logging_config import log_event
from app.db.database import Database, get_database
from app.strategies.schemas import CatalogStrategy
from app.strategies.loader import generate_strategy_signals
from app.strategies.combos.combo_engine import generate_combo_signals


class BacktestService:
    def __init__(self, database: Database | None = None) -> None:
        self.database = database or get_database()

    def load_data(self, config: BacktestConfig) -> pd.DataFrame:
        if not Path(cfg.CONSOLIDATED_FILE).exists(): raise FileNotFoundError("Processed universe is missing. Run recalibration first.")
        data = pd.read_csv(cfg.CONSOLIDATED_FILE, parse_dates=["Date"])
        data = data.sort_values(["Ticker", "Date"])
        if config.strategy_id in data.columns:
            # Stage 1 persisted actionable t+1 signals. Recover observation-time t.
            data[config.strategy_id] = data.groupby("Ticker")[config.strategy_id].shift(-1).fillna(0).astype(int)
        else:
            data=self._attach_dynamic_signal(config,data)
        return data

    def _attach_dynamic_signal(self,config:BacktestConfig,data:pd.DataFrame)->pd.DataFrame:
        strategy_rows=self.database.query("SELECT config_json,status FROM strategy_definitions WHERE strategy_id=?",(config.strategy_id,))
        if strategy_rows:
            if strategy_rows[0]["status"]!="active": raise ValueError(f"Strategy status is {strategy_rows[0]['status']}")
            data=generate_strategy_signals(data,CatalogStrategy(**json.loads(strategy_rows[0]["config_json"])))
        else:
            combo_rows=self.database.query("SELECT * FROM combo_strategy_definitions WHERE combo_id=?",(config.strategy_id,))
            if not combo_rows: raise ValueError(f"Strategy signal is unavailable: {config.strategy_id}")
            row=combo_rows[0]
            if row["status"]!="active": raise ValueError(f"Combo status is {row['status']}")
            combo={"combo_id":row["combo_id"],"name":row["name"],"components":json.loads(row["components_json"]),"logic":json.loads(row["logic_json"]),"entry":json.loads(row["entry_json"])}
            base_rows=self.database.query("SELECT strategy_id,config_json FROM strategy_definitions")
            definitions={item["strategy_id"]:CatalogStrategy(**json.loads(item["config_json"])) for item in base_rows}
            data=generate_combo_signals(data,combo,definitions)
        return data

    def run(self, config: BacktestConfig, data: pd.DataFrame | None = None, persist: bool = True) -> BacktestResult:
        registry = self.database.query("""SELECT strategy_id,name FROM strategy_registry WHERE strategy_id=? UNION SELECT strategy_id,name FROM custom_strategies WHERE strategy_id=? UNION SELECT strategy_id,name FROM strategy_definitions WHERE strategy_id=? UNION SELECT combo_id AS strategy_id,name FROM combo_strategy_definitions WHERE combo_id=?""", (config.strategy_id, config.strategy_id,config.strategy_id,config.strategy_id))
        if not registry: raise ValueError(f"Strategy is not registered: {config.strategy_id}")
        source = data.copy() if data is not None else self.load_data(config)
        if data is not None and config.strategy_id not in source.columns: source=self._attach_dynamic_signal(config,source)
        created = datetime.now(timezone.utc).isoformat()
        engine = BacktestEngine(config); result = engine.run(source)
        benchmark_metrics, warnings = apply_benchmark(result.equity_curve, source, config.benchmark_symbol, config.initial_capital)
        result.benchmark_metrics = benchmark_metrics; result.warnings.extend(warnings)
        benchmark_return = benchmark_metrics.get("return_pct") if benchmark_metrics else None
        result.metrics = calculate_metrics(result.trades, result.equity_curve, config.initial_capital, engine.portfolio.turnover, engine.portfolio.exposure_observations, benchmark_return)
        result.metric_breakdown = metric_breakdown(result.metrics)
        result.warnings.extend(self._research_warnings(result))
        if persist:
            self._persist(result, registry[0]["name"], created)
            export_result(result, cfg.REPORTS_DIR)
        log_event("info", "backtest_service", "backtest_complete", "Decision-grade backtest completed", {"run_id": result.run_id, "strategy": config.strategy_id, "trades": len(result.trades)})
        return result

    def list_runs(self) -> list[dict]: return self.database.query("SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT 250")

    def details(self, run_id: str) -> dict:
        rows = self.database.query("SELECT * FROM backtest_runs WHERE run_id=?", (run_id,))
        if not rows: raise ValueError("Unknown backtest run.")
        row = rows[0]; row["config"] = json.loads(row.pop("config_json")); row["symbols"] = json.loads(row.pop("symbols_json")); return row

    def trades(self, run_id: str) -> list[dict]: return self.database.query("SELECT * FROM backtest_trades WHERE run_id=? ORDER BY entry_time", (run_id,))
    def equity(self, run_id: str) -> list[dict]: return self.database.query("SELECT * FROM backtest_equity_curve WHERE run_id=? ORDER BY timestamp", (run_id,))
    def metrics(self, run_id: str) -> list[dict]: return self.database.query("SELECT * FROM backtest_metric_breakdown WHERE run_id=? ORDER BY id", (run_id,))

    def compare(self, run_ids: list[str]) -> list[dict]:
        if not run_ids: return []
        placeholders = ",".join("?" for _ in run_ids)
        return self.database.query(f"SELECT run_id,strategy_name,start_date,end_date,net_return_pct,max_drawdown_pct,sharpe,profit_factor,win_rate,total_trades,cost_model_name,slippage_bps FROM backtest_runs WHERE run_id IN ({placeholders})", run_ids)

    def robustness(self, config: BacktestConfig, data: pd.DataFrame | None = None) -> dict:
        source = data.copy() if data is not None else self.load_data(config)
        scenarios = {
            "normal": config,
            "slippage_2x": replace(config, slippage_bps=config.slippage_bps*2),
            "slippage_3x": replace(config, slippage_bps=config.slippage_bps*3),
            "delayed_entry_1_bar": replace(config, entry_delay_bars=config.entry_delay_bars+1),
            "delayed_exit_1_bar": replace(config, exit_delay_bars=config.exit_delay_bars+1),
            "half_position_size": replace(config, position_size_multiplier=config.position_size_multiplier*0.5),
        }
        if config.start_date and config.end_date:
            midpoint = pd.Timestamp(config.start_date) + (pd.Timestamp(config.end_date)-pd.Timestamp(config.start_date))/2
            scenarios["first_half"] = replace(config, end_date=str(midpoint.date()))
            scenarios["second_half"] = replace(config, start_date=str((midpoint + pd.Timedelta(days=1)).date()))
        results = {}
        for name, scenario in scenarios.items():
            result = self.run(scenario, source, persist=False)
            results[name] = {"metrics": result.metrics, "warnings": result.warnings}
        normal = results["normal"]["metrics"]; flags = []
        if normal["net_profit"] > 0 and results["slippage_2x"]["metrics"]["net_profit"] <= 0: flags.append("Profit disappears at 2x slippage.")
        if normal["total_trades"] < 30: flags.append("Completed-trade sample is below 30.")
        if normal["max_drawdown_pct"] > 30: flags.append("Maximum drawdown exceeds 30%.")
        if normal["profit_factor"] < 1: flags.append("Profit factor is below 1.")
        if normal["expectancy"] < 0: flags.append("Completed-trade expectancy is negative.")
        if normal.get("benchmark_relative_return_pct") is not None and normal["benchmark_relative_return_pct"] < -10: flags.append("Benchmark outperforms strategy by more than 10 percentage points.")
        if normal["gross_profit"] > 0 and normal["largest_win"] / normal["gross_profit"] > 0.30: flags.append("One trade contributes more than 30% of gross profit.")
        if "first_half" in results and "second_half" in results:
            first=results["first_half"]["metrics"]["net_profit"]; second=results["second_half"]["metrics"]["net_profit"]
            if (first > 0) != (second > 0): flags.append("Performance is not positive in both date-window halves.")
        return {"scenarios": results, "flags": flags, "passed": not flags}

    def walk_forward(self, config: BacktestConfig, train_days=504, test_days=126, expanding=True, data=None) -> dict:
        return run_walk_forward(config, data.copy() if data is not None else self.load_data(config), train_days, test_days, expanding)

    def _research_warnings(self, result: BacktestResult) -> list[str]:
        warnings = [f"Execution model: {result.config.execution_price_model}.", "Stage 2 results are completed-trade simulations and are not comparable to legacy signal-day reports."]
        if result.config.execution_price_model == "signal_close_for_research_only": warnings.append("Same-close execution is research-only and may be unachievable.")
        if len(result.trades) < 30: warnings.append("Low completed-trade count; metrics are statistically fragile.")
        positive = sum(max(trade.net_pnl, 0) for trade in result.trades)
        if positive and max((max(trade.net_pnl, 0) for trade in result.trades), default=0) / positive > 0.30: warnings.append("One trade contributes more than 30% of gross profit.")
        total_costs=sum(trade.costs for trade in result.trades)
        gross_edge=sum(trade.gross_pnl for trade in result.trades)
        if total_costs > 0 and gross_edge > 0 and total_costs >= gross_edge: warnings.append("Modeled costs consume the entire gross trading edge.")
        if result.config.include_short_borrow_cost_placeholder and result.config.direction_mode != "long_only": warnings.append("Short borrow costs are a placeholder and are not deducted.")
        return warnings

    def _persist(self, result: BacktestResult, strategy_name: str, created: str) -> None:
        m=result.metrics; c=result.config; completed=datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as connection:
            run_row = {
                "run_id":result.run_id,"strategy_id":c.strategy_id,"strategy_name":strategy_name,"universe_name":"custom",
                "symbols_json":json.dumps(c.symbols),"timeframe":c.timeframe,"start_date":c.start_date,"end_date":c.end_date,
                "initial_capital":c.initial_capital,"execution_price_model":c.execution_price_model,"direction_mode":c.direction_mode,
                "max_positions":c.max_positions,"position_sizing_method":c.position_sizing_method,"risk_per_trade_pct":c.risk_per_trade_pct,
                "cost_model_name":c.cost_model_name,"slippage_bps":c.slippage_bps,"benchmark_symbol":c.benchmark_symbol,"status":"completed",
                "total_trades":m["total_trades"],"winning_trades":m["winning_trades"],"losing_trades":m["losing_trades"],
                "net_profit":m["net_profit"],"net_return_pct":m["net_return_pct"],"cagr":m["cagr"],"sharpe":m["sharpe"],
                "sortino":m["sortino"],"calmar":m["calmar"],"max_drawdown_pct":m["max_drawdown_pct"],
                "profit_factor":m["profit_factor"],"expectancy":m["expectancy"],"avg_win":m["average_win"],"avg_loss":m["average_loss"],
                "win_rate":m["win_rate"],"exposure_pct":m["exposure_pct"],"turnover":m["turnover"],"created_at":created,
                "completed_at":completed,"config_json":json.dumps(c.to_dict()),"notes":c.notes,
            }
            columns = list(run_row); placeholders = ",".join("?" for _ in columns)
            connection.execute(f"INSERT INTO backtest_runs({','.join(columns)}) VALUES({placeholders})", tuple(run_row[column] for column in columns))
            for trade in result.trades:
                connection.execute("""INSERT INTO backtest_trades(run_id,strategy_id,symbol,direction,quantity,entry_signal_time,entry_time,entry_price,entry_reason,stop_loss,target,trailing_stop,exit_signal_time,exit_time,exit_price,exit_reason,gross_pnl,costs,net_pnl,return_pct,holding_period_bars,mae,mfe,brokerage,taxes_and_charges,slippage_cost,spread_cost,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (result.run_id,c.strategy_id,trade.symbol,trade.direction,trade.quantity,str(trade.entry_signal_time),str(trade.entry_time),trade.entry_price,trade.entry_reason,trade.stop_loss,trade.target,trade.trailing_stop,str(trade.exit_signal_time),str(trade.exit_time),trade.exit_price,trade.exit_reason,trade.gross_pnl,trade.costs,trade.net_pnl,trade.return_pct,trade.holding_period_bars,trade.mae,trade.mfe,trade.brokerage,trade.taxes_and_charges,trade.slippage_cost,trade.spread_cost,completed))
            for order in result.orders:
                connection.execute("""INSERT INTO backtest_orders(run_id,trade_id,symbol,side,order_type,requested_time,requested_price,fill_time,fill_price,quantity,status,rejection_reason,slippage,costs,created_at) VALUES(?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (result.run_id,order.symbol,order.side,"MARKET",str(order.timestamp),order.requested_price,str(order.fill_time) if order.fill_time else None,order.fill_price,order.quantity,order.status,order.rejection_reason,order.slippage,order.costs,completed))
            for row in result.equity_curve:
                connection.execute("INSERT INTO backtest_equity_curve(run_id,timestamp,cash,position_value,total_equity,drawdown_pct,benchmark_value,benchmark_drawdown_pct,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(result.run_id,row["timestamp"],row["cash"],row["position_value"],row["total_equity"],row["drawdown_pct"],row["benchmark_value"],row["benchmark_drawdown_pct"],completed))
            for row in result.daily_summary:
                connection.execute("INSERT INTO backtest_daily_summary(run_id,date,starting_equity,ending_equity,realized_pnl,unrealized_pnl,gross_exposure,net_exposure,trades_opened,trades_closed,costs,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(result.run_id,row["date"],row["starting_equity"],row["ending_equity"],row["realized_pnl"],row["unrealized_pnl"],row["gross_exposure"],row["net_exposure"],row["trades_opened"],row["trades_closed"],row["costs"],completed))
            for row in result.metric_breakdown:
                connection.execute("INSERT INTO backtest_metric_breakdown(run_id,metric_name,metric_value,metric_status,explanation,created_at) VALUES(?,?,?,?,?,?)",(result.run_id,row["metric_name"],row["metric_value"],row["metric_status"],row["explanation"],completed))
