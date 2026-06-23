let btChart = null;

function applyBacktestUniverse() {
  if (document.getElementById('bt-universe').value === 'configured') {
    document.getElementById('bt-symbols').value = (STATE.ticker_universe || []).join(',');
  }
}

function btConfig() {
  const val = id => document.getElementById(id).value;
  return {
    strategy_id: val('bt-strategy'), symbols: val('bt-symbols').split(',').map(x=>x.trim().toUpperCase()).filter(Boolean),
    start_date: val('bt-start') || null, end_date: val('bt-end') || null,
    initial_capital: Number(val('bt-capital')), execution_price_model: val('bt-execution'), direction_mode: val('bt-direction'),
    position_sizing_method: val('bt-sizing'), max_positions: Number(val('bt-maxpos')),
    stop_loss_pct: Number(val('bt-stop'))/100, target_pct: Number(val('bt-target'))/100,
    trailing_stop_pct: Number(val('bt-trailing'))/100, cost_model_name: val('bt-cost'),
    slippage_bps: Number(val('bt-slippage')), benchmark_symbol: val('bt-benchmark').trim().toUpperCase() || null
  };
}

async function btApi(url, options={}) {
  const response = await fetch(url, options); const payload = await response.json();
  if (!payload.success) throw new Error(payload.error || 'Backtest request failed');
  return payload;
}

async function loadBacktests() {
  const select = document.getElementById('bt-strategy');
  if (select && !select.options.length) {
    (STATE.strategies || []).filter(x=>x.enabled).forEach(strategy => select.add(new Option(strategy.label, strategy.name)));
    try {
      const [library,combos]=await Promise.all([btApi('/api/strategy-library?status=active'),btApi('/api/combo-strategies')]);
      library.data.forEach(strategy=>select.add(new Option(`Library · ${strategy.name}`,strategy.strategy_id)));
      combos.data.filter(combo=>combo.status==='active').forEach(combo=>select.add(new Option(`Combo · ${combo.name}`,combo.combo_id)));
    } catch(error) { toast('Strategy catalog: '+error.message,'err'); }
  }
  try {
    const payload = await btApi('/api/backtests'); const body = document.getElementById('bt-history'); const rows = payload.data || [];
    body.innerHTML = rows.length ? rows.map(row=>`<tr><td class="ticker">${esc(row.run_id.slice(0,8))}</td><td>${esc(row.strategy_name)}</td><td>${esc(row.start_date||'—')} → ${esc(row.end_date||'—')}</td><td class="num ${row.net_return_pct>=0?'up':'dn'}">${Number(row.net_return_pct).toFixed(2)}%</td><td class="num dn">${Number(row.max_drawdown_pct).toFixed(2)}%</td><td class="num">${Number(row.win_rate).toFixed(1)}%</td><td class="num">${row.profit_factor==null?'—':Number(row.profit_factor).toFixed(2)}</td><td>${esc((row.created_at||'').slice(0,19))}</td><td><button class="btn btn-sm" onclick="viewBacktest('${esc(row.run_id)}')">View</button></td></tr>`).join('') : '<tr><td colspan="9" class="empty">No persisted backtest runs.</td></tr>';
  } catch(error) { toast('Backtest history: '+error.message,'err'); }
}

async function runBacktest() {
  const button=document.getElementById('bt-run'), status=document.getElementById('bt-status'); button.disabled=true; status.textContent='Running chronological simulation…';
  try {
    const payload=await btApi('/api/backtests/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(btConfig())});
    renderBtWarnings(payload.warnings); await viewBacktest(payload.data.run_id); toast('Backtest completed and persisted','ok'); await loadBacktests();
  } catch(error) { status.textContent='Failed'; toast(error.message,'err'); }
  finally { button.disabled=false; }
}

async function viewBacktest(runId) {
  const [run,trades,equity,metrics]=await Promise.all([btApi(`/api/backtests/${runId}`),btApi(`/api/backtests/${runId}/trades`),btApi(`/api/backtests/${runId}/equity`),btApi(`/api/backtests/${runId}/metrics`)]);
  renderBtSummary(run.data); renderBtTrades(trades.data); renderBtMetrics(metrics.data); renderBtChart(equity.data);
  document.getElementById('bt-status').textContent=`Viewing ${runId.slice(0,8)} · ${run.data.execution_price_model}`;
}

function renderBtSummary(run) {
  const values=[['Net return',run.net_return_pct,'%'],['Net profit',run.net_profit,'₹'],['CAGR',run.cagr,'%'],['Max drawdown',run.max_drawdown_pct,'%'],['Sharpe',run.sharpe,''],['Sortino',run.sortino,''],['Profit factor',run.profit_factor,''],['Win rate',run.win_rate,'%'],['Total trades',run.total_trades,''],['Exposure',run.exposure_pct,'%'],['Cost model',run.cost_model_name,''],['Execution',run.execution_price_model,'']];
  document.getElementById('bt-summary').innerHTML=values.map(([label,value,suffix])=>`<div class="bt-stat"><b>${esc(label)}</b><span>${suffix==='₹'?fmt(value):typeof value==='number'?Number(value).toFixed(2)+suffix:esc(value||'—')}</span></div>`).join('');
}
function renderBtTrades(rows) { document.getElementById('bt-trades').innerHTML=rows.length?rows.map(t=>`<tr><td class="ticker">${esc(t.symbol)}</td><td>${esc(t.direction)}</td><td>${esc(t.entry_time.slice(0,19))}</td><td class="num">${Number(t.entry_price).toFixed(2)}</td><td>${esc(t.exit_time.slice(0,19))}</td><td class="num">${Number(t.exit_price).toFixed(2)}</td><td>${esc(t.exit_reason)}</td><td class="num">${t.quantity}</td><td class="num ${t.gross_pnl>=0?'up':'dn'}">${Number(t.gross_pnl).toFixed(2)}</td><td class="num">${Number(t.costs).toFixed(2)}</td><td class="num ${t.net_pnl>=0?'up':'dn'}">${Number(t.net_pnl).toFixed(2)}</td><td class="num">${Number(t.return_pct).toFixed(2)}%</td><td class="num">${t.holding_period_bars}</td></tr>`).join(''):'<tr><td colspan="13" class="empty">No completed trades in this configuration.</td></tr>'; }
function renderBtMetrics(rows) { document.getElementById('bt-metrics').innerHTML=rows.map(m=>`<div class="bt-metric"><i class="${esc(m.metric_status)}"></i><div>${esc(m.metric_name.replaceAll('_',' '))}<small>${esc(m.explanation)}</small></div><strong>${m.metric_value==null?'—':Number(m.metric_value).toFixed(3)}</strong></div>`).join(''); }
function renderBtWarnings(rows=[]) { document.getElementById('bt-warnings').innerHTML=rows.length?rows.map(w=>`<div class="bt-warning-row">${esc(w)}</div>`).join(''):'<div class="empty">No automatic warning generated.</div>'; }
function renderBtChart(rows) { const ctx=document.getElementById('backtestEquityChart'); if(btChart)btChart.destroy(); btChart=new Chart(ctx,{type:'line',data:{labels:rows.map(x=>x.timestamp.slice(0,10)),datasets:[{label:'Strategy',data:rows.map(x=>x.total_equity),borderColor:'#6366f1',pointRadius:0},{label:'Benchmark',data:rows.map(x=>x.benchmark_value),borderColor:'#64748b',pointRadius:0,borderDash:[5,4]}]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{labels:{color:'#94a3b8'}}},scales:{x:{ticks:{color:'#64748b',maxTicksLimit:10},grid:{color:'#242830'}},y:{ticks:{color:'#64748b'},grid:{color:'#242830'}}}}}); }

async function runRobustness() {
  const button=document.getElementById('bt-robust'); button.disabled=true; document.getElementById('bt-status').textContent='Running robustness scenarios…';
  try { const payload=await btApi('/api/backtests/robustness',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(btConfig())}); const rows=Object.entries(payload.data.scenarios).map(([name,result])=>`${name}: return ${Number(result.metrics.net_return_pct).toFixed(2)}%, DD ${Number(result.metrics.max_drawdown_pct).toFixed(2)}%`); renderBtWarnings([...payload.data.flags,...rows]); document.getElementById('bt-status').textContent=payload.data.passed?'Robustness: PASS':'Robustness: REVIEW'; }
  catch(error){toast(error.message,'err');} finally{button.disabled=false;}
}
