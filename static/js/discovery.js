const universe = document.querySelector('#universe');
const customControls = document.querySelector('#custom-controls');
const customList = document.querySelector('#custom-list');
const report = document.querySelector('#download-report');
const scanReport = document.querySelector('#scan-report');
const patternSelection = document.querySelector('#pattern-selection');
const patternCatalogue = document.querySelector('#pattern-catalogue');
const scanResults = document.querySelector('#scan-results');
const patternDetails = document.querySelector('#pattern-details');
const patternChart = document.querySelector('#pattern-chart');
const healthFilter = document.querySelector('#financial-health-filter');
const fundamentalPanel = document.querySelector('#fundamental-panel');
const fundamentalSummary = document.querySelector('#fundamental-summary');
const fundamentalDetails = document.querySelector('#fundamental-details');
const refreshFundamentals = document.querySelector('#refresh-fundamentals');
const historicalReport = document.querySelector('#historical-report');
const historicalResults = document.querySelector('#historical-results');
let implementedPatterns = [];
let currentFindings = [];
let selectedFinding = null;

function showReport(message, type = '') {
  report.className = `download-report ${type}`;
  report.textContent = message;
}

async function request(path, options = {}) {
  const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
  const payload = await response.json();
  if (!response.ok || !payload.success) throw new Error(payload.error || 'Request failed.');
  return payload.data;
}

async function refreshCustomSymbols() {
  try {
    const data = await request('/api/discovery/symbols?universe=custom');
    customList.replaceChildren();
    data.symbols.forEach((item) => {
      const row = document.createElement('span');
      row.className = 'custom-symbol';
      row.textContent = item.symbol;
      const remove = document.createElement('button');
      remove.type = 'button'; remove.textContent = 'Remove';
      remove.addEventListener('click', async () => {
        try { await request(`/api/discovery/symbols/${encodeURIComponent(item.symbol)}`, {method: 'DELETE'}); await refreshCustomSymbols(); }
        catch (error) { showReport(error.message, 'error'); }
      });
      row.append(' ', remove); customList.append(row);
    });
    if (!data.symbols.length) customList.textContent = 'No custom stocks added.';
  } catch (error) { showReport(error.message, 'error'); }
}

universe.addEventListener('change', async () => {
  customControls.hidden = universe.value !== 'custom';
  customList.hidden = universe.value !== 'custom';
  if (universe.value === 'custom') await refreshCustomSymbols();
  showReport('Select Update Data to download only missing or corrected daily candles.');
});

document.querySelector('#add-symbol').addEventListener('click', async () => {
  const symbol = document.querySelector('#custom-symbol').value.trim();
  if (!symbol) return showReport('Enter a stock symbol first.', 'error');
  try {
    const item = await request('/api/discovery/symbols', {method: 'POST', body: JSON.stringify({symbol, exchange: document.querySelector('#custom-exchange').value})});
    document.querySelector('#custom-symbol').value = '';
    await refreshCustomSymbols();
    showReport(`${item.symbol} added to the custom universe.`, 'success');
  } catch (error) { showReport(error.message, 'error'); }
});

document.querySelector('#update-data').addEventListener('click', async (event) => {
  event.currentTarget.disabled = true;
  showReport('Downloading daily candles and validating cached data…');
  try {
    const result = await request('/api/discovery/update', {method: 'POST', body: JSON.stringify({universe: universe.value, provider: document.querySelector('#provider').value, lookback: document.querySelector('#lookback').value})});
    const latest = result.succeeded.map(row => `${row.symbol}: ${row.latest_date || 'no valid candle'}`).join(' · ');
    const skipped = result.skipped.map(row => row.symbol).join(', ');
    const failed = result.failed.map(row => `${row.symbol}: ${row.error || 'download failed'}`).join(' · ');
    const stale = result.stale.join(', ');
    showReport(`Completed ${result.total}: ${result.succeeded.length} succeeded, ${result.skipped.length} skipped, ${result.failed.length} failed, ${result.stale.length} stale.${latest ? ` Latest: ${latest}.` : ''}${skipped ? ` Skipped: ${skipped}.` : ''}${failed ? ` Failed: ${failed}.` : ''}${stale ? ` Stale: ${stale}.` : ''}`, result.failed.length ? 'error' : 'success');
  } catch (error) { showReport(error.message, 'error'); }
  finally { event.currentTarget.disabled = false; }
});

function scanMessage(message, type = '') { scanReport.className = `download-report ${type}`; scanReport.textContent = message; }
function historicalMessage(message, type = '') { historicalReport.className = `download-report ${type}`; historicalReport.textContent = message; }

function renderResults(findings) {
  const filter = healthFilter.value;
  const visible = findings.filter((finding) => filter === 'ALL' || (finding.fundamentals?.assessment?.health || 'UNKNOWN') === filter);
  scanResults.replaceChildren();
  if (!visible.length) {
    scanResults.innerHTML = '<tr class="empty-row"><td colspan="12"><strong>No matching current findings.</strong>No implemented pattern met every deterministic condition under the selected financial-health filter.</td></tr>';
    return;
  }
  visible.forEach((finding) => {
    const row = document.createElement('tr');
    const level = finding.levels.support_resistance_or_neckline;
    const assessment = finding.fundamentals?.assessment || {health: 'UNKNOWN', valuation: {classification: 'UNKNOWN'}};
    [finding.symbol.split(':')[1], finding.exchange, finding.pattern_name, finding.direction, finding.status, finding.formation_start_date || '—', finding.signal_detection_date || '—', finding.latest_candle_date || '—', level == null ? '—' : Number(level).toFixed(2), assessment.health || 'UNKNOWN', assessment.valuation?.classification || 'UNKNOWN'].forEach((value) => { const cell = document.createElement('td'); cell.textContent = value; row.append(cell); });
    const details = document.createElement('button'); details.type = 'button'; details.textContent = 'Details';
    details.addEventListener('click', () => { selectedFinding = finding; renderChart(finding); renderFundamentals(finding); patternDetails.hidden = false; patternDetails.textContent = JSON.stringify(finding, null, 2); });
    const cell = document.createElement('td'); cell.append(details); row.append(cell); scanResults.append(row);
  });
}

function renderFundamentals(finding) {
  const data = finding.fundamentals;
  fundamentalPanel.hidden = false;
  const assessment = data?.assessment || {health: 'UNKNOWN', reasons: ['Fundamental data has not been retrieved.'], valuation: {classification: 'UNKNOWN'}};
  fundamentalSummary.textContent = `Financial Health: ${assessment.health || 'UNKNOWN'} · Valuation: ${assessment.valuation?.classification || 'UNKNOWN'} · Statement freshness: ${data?.freshness || 'missing'} · Valuation freshness: ${data?.valuation_freshness || 'missing'}`;
  const snapshot = data?.snapshot || {};
  fundamentalDetails.textContent = JSON.stringify({
    company: {...(snapshot.identity || {}), symbol: snapshot.symbol, provider: snapshot.provider, provider_symbol: snapshot.provider_symbol},
    refresh: {last_successful: data?.last_successful_refresh || null, last_attempted: data?.last_attempted_refresh || null, valuation_last_successful: data?.valuation_last_successful_refresh || null},
    reporting_periods: {annual: (snapshot.annual || []).map((row) => row.period_end), quarterly: (snapshot.quarterly || []).map((row) => row.period_end)},
    financial_indicators: assessment.metrics?.values || {},
    assessment,
  }, null, 2);
  refreshFundamentals.hidden = false;
}

function renderHistoricalEvents(events) {
  historicalResults.replaceChildren();
  if (!events.length) {
    historicalResults.innerHTML = '<tr class="empty-row"><td colspan="11"><strong>No historical detector events.</strong>No selected detector met every configured condition on the cached candles.</td></tr>';
    return;
  }
  events.forEach((event) => {
    const row = document.createElement('tr');
    [event.symbol.split(':')[1], event.exchange, event.pattern_name, event.direction, `${event.formation_start_date || '—'} → ${event.formation_end_date || '—'}`, event.first_detection_date || '—', event.confirmation_date || '—', event.invalidation_date || '—', event.review_classification || event.status, event.detector_version].forEach((value) => { const cell = document.createElement('td'); cell.textContent = value; row.append(cell); });
    const details = document.createElement('button'); details.type = 'button'; details.textContent = 'Chart / evidence';
    details.addEventListener('click', () => { selectedFinding = event; renderChart(event); fundamentalPanel.hidden = true; refreshFundamentals.hidden = true; patternDetails.hidden = false; patternDetails.textContent = JSON.stringify(event, null, 2); });
    const cell = document.createElement('td'); cell.append(details); row.append(cell); historicalResults.append(row);
  });
}

healthFilter.addEventListener('change', () => renderResults(currentFindings));
refreshFundamentals.addEventListener('click', async () => {
  if (!selectedFinding) return;
  refreshFundamentals.disabled = true;
  try {
    selectedFinding.fundamentals = await request(`/api/discovery/fundamentals/${encodeURIComponent(selectedFinding.symbol)}/refresh`, {method: 'POST'});
    renderFundamentals(selectedFinding); renderResults(currentFindings);
  } catch (error) { scanMessage(error.message, 'error'); }
  finally { refreshFundamentals.disabled = false; }
});

function renderChart(finding) {
  const closes = finding.chart?.closes || [];
  if (closes.length < 2) { patternChart.hidden = true; return; }
  const width = 760, height = 180, margin = 14, level = finding.levels.support_resistance_or_neckline;
  const trendlines = Array.isArray(finding.evidence?.trendlines) ? finding.evidence.trendlines : [];
  const annotations = Array.isArray(finding.evidence?.annotations) ? finding.evidence.annotations : [];
  const trendValues = trendlines.flatMap((line) => [Number(line.start_price), Number(line.end_price)]).filter(Number.isFinite);
  const annotationValues = annotations.flatMap((annotation) => annotation.type === 'polyline' ? (annotation.points || []).map((point) => Number(point.price)) : [Number(annotation.start_price), Number(annotation.end_price)]).filter(Number.isFinite);
  const values = (level == null ? closes : closes.concat([Number(level)])).concat(trendValues, annotationValues);
  const minimum = Math.min(...values), maximum = Math.max(...values), range = Math.max(maximum - minimum, 0.01);
  const x = (index) => margin + index * (width - margin * 2) / (closes.length - 1);
  const y = (value) => height - margin - (value - minimum) * (height - margin * 2) / range;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  const line = document.createElementNS(svg.namespaceURI, 'polyline'); line.setAttribute('points', closes.map((value, index) => `${x(index)},${y(value)}`).join(' ')); line.setAttribute('class', 'price-line'); svg.append(line);
  const dateIndex = new Map((finding.chart?.dates || []).map((value, index) => [String(value), index]));
  trendlines.forEach((trendline) => {
    const start = dateIndex.get(String(trendline.start_date)); const end = dateIndex.get(String(trendline.end_date));
    if (start == null || end == null) return;
    const boundary = document.createElementNS(svg.namespaceURI, 'line');
    boundary.setAttribute('x1', x(start)); boundary.setAttribute('x2', x(end));
    boundary.setAttribute('y1', y(Number(trendline.start_price))); boundary.setAttribute('y2', y(Number(trendline.end_price)));
    boundary.setAttribute('class', trendline.name.includes('resistance') ? 'trendline-upper' : 'trendline-lower'); svg.append(boundary);
  });
  annotations.forEach((annotation) => {
    if (annotation.type === 'line') {
      const start = dateIndex.get(String(annotation.start_date)); const end = dateIndex.get(String(annotation.end_date));
      if (start == null || end == null) return;
      const marker = document.createElementNS(svg.namespaceURI, 'line'); marker.setAttribute('x1', x(start)); marker.setAttribute('x2', x(end));
      marker.setAttribute('y1', y(Number(annotation.start_price))); marker.setAttribute('y2', y(Number(annotation.end_price))); marker.setAttribute('class', 'pattern-annotation'); svg.append(marker);
    } else if (annotation.type === 'polyline') {
      const points = (annotation.points || []).map((point) => ({index: dateIndex.get(String(point.date)), price: Number(point.price)})).filter((point) => point.index != null && Number.isFinite(point.price));
      if (points.length < 2) return;
      const marker = document.createElementNS(svg.namespaceURI, 'polyline'); marker.setAttribute('points', points.map((point) => `${x(point.index)},${y(point.price)}`).join(' ')); marker.setAttribute('class', 'pattern-annotation'); svg.append(marker);
    }
  });
  if (level != null) { const horizontal = document.createElementNS(svg.namespaceURI, 'line'); horizontal.setAttribute('x1', margin); horizontal.setAttribute('x2', width - margin); horizontal.setAttribute('y1', y(Number(level))); horizontal.setAttribute('y2', y(Number(level))); horizontal.setAttribute('class', 'level-line'); svg.append(horizontal); }
  patternChart.replaceChildren(svg); patternChart.hidden = false;
}

async function loadPatterns() {
  try {
    const data = await request('/api/discovery/patterns');
    implementedPatterns = data.patterns.filter((pattern) => pattern.implementation_status === 'EXPERIMENTAL');
    patternSelection.replaceChildren();
    implementedPatterns.forEach((pattern) => {
      const label = document.createElement('label'); const input = document.createElement('input');
      input.type = 'checkbox'; input.value = pattern.id; input.checked = true;
      label.append(input, ` ${pattern.name}`); patternSelection.append(label);
    });
    patternCatalogue.replaceChildren();
    data.patterns.forEach((pattern) => { const item = document.createElement('span'); item.className = `catalogue-item ${pattern.implementation_status.toLowerCase()}`; item.textContent = `${pattern.name} — ${pattern.implementation_status}`; patternCatalogue.append(item); });
  } catch (error) { patternSelection.textContent = error.message; }
}

document.querySelector('#analyse-stocks').addEventListener('click', async (event) => {
  const patterns = [...patternSelection.querySelectorAll('input:checked')].map((input) => input.value);
  event.currentTarget.disabled = true; scanMessage('Scanning cached daily candles with confirmed pivots only…'); patternDetails.hidden = true;
  try {
    const result = await request('/api/discovery/scan', {method: 'POST', body: JSON.stringify({universe: universe.value, patterns})});
    currentFindings = result.findings; renderResults(currentFindings);
    scanMessage(`Scan ${result.scan_id}: ${result.symbols_scanned.length} symbols scanned, ${result.symbols_skipped.length} skipped, ${result.matches_found} current matches.`, result.symbols_skipped.length ? 'error' : 'success');
  } catch (error) { scanMessage(error.message, 'error'); }
  finally { event.currentTarget.disabled = false; }
});

document.querySelector('#review-history').addEventListener('click', async (event) => {
  const patterns = [...patternSelection.querySelectorAll('input:checked')].map((input) => input.value);
  event.currentTarget.disabled = true; historicalMessage('Replaying cached daily candles chronologically with only then-known pivots…');
  try {
    const result = await request('/api/discovery/historical-pattern-review', {method: 'POST', body: JSON.stringify({universe: universe.value, patterns})});
    renderHistoricalEvents(result.events || []);
    const summary = result.summary || {};
    historicalMessage(`Review ${result.review_id}: ${result.symbols_scanned.length} symbols, ${summary.events || 0} events (${summary.forming || 0} forming, ${summary.confirmed || 0} confirmed, ${summary.invalidated || 0} invalidated). No trade outcomes were calculated.`, result.symbols_skipped.length ? 'error' : 'success');
  } catch (error) { historicalMessage(error.message, 'error'); }
  finally { event.currentTarget.disabled = false; }
});

loadPatterns();
