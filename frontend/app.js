const API = '';
let mainChart = null;
let chartData = null;
let gaugeChart = null;

// ── TOP 5 ──────────────────────────────────────────
async function loadTop5(forceRefresh = false) {
  const listEl = document.getElementById('top5List');
  const loadingEl = document.getElementById('top5Loading');
  const refreshBtn = document.getElementById('refreshBtn');

  listEl.classList.add('hidden');
  loadingEl.classList.remove('hidden');
  refreshBtn.disabled = true;

  try {
    const url = forceRefresh ? `${API}/api/top5?_=${Date.now()}` : `${API}/api/top5`;
    const res = await fetch(url);
    if (!res.ok) throw new Error('TOP5 로드 실패');
    const data = await res.json();
    renderTop5(data.stocks);
  } catch (e) {
    loadingEl.textContent = '⚠️ TOP5 로드 실패. 새로고침을 눌러주세요.';
  } finally {
    loadingEl.classList.add('hidden');
    listEl.classList.remove('hidden');
    refreshBtn.disabled = false;
  }
}

function renderTop5(stocks) {
  const listEl = document.getElementById('top5List');
  const rankLabels = ['gold', 'silver', 'bronze', '', ''];
  const rankEmoji = ['1', '2', '3', '4', '5'];

  listEl.innerHTML = stocks.map((s, i) => {
    const priceStr = s.currency === 'KRW'
      ? s.current_price.toLocaleString('ko-KR') + ' 원'
      : '$' + s.current_price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const changeSign = s.price_change_1d > 0 ? '+' : '';
    const changeCls = s.price_change_1d > 0 ? 'up' : s.price_change_1d < 0 ? 'down' : 'flat';
    const recClass = `top5-rec-${s.recommendation.toLowerCase()}`;
    const recLabel = s.recommendation === 'BUY' ? '매수' : s.recommendation === 'SELL' ? '매도' : '보류';
    const scoreCls = s.combined_score >= 65 ? 'up' : s.combined_score <= 40 ? 'down' : '';

    return `
    <div class="top5-item" onclick="quickPick('${s.market}','${s.ticker}')">
      <div class="top5-rank ${rankLabels[i]}">${rankEmoji[i]}</div>
      <div class="top5-info">
        <div class="top5-name">${s.name}</div>
        <div class="top5-ticker">${s.ticker} · ${s.market}</div>
      </div>
      <div class="top5-price">
        <div class="top5-price-val">${priceStr}</div>
        <div class="top5-change ${changeCls}">${changeSign}${s.price_change_1d}% 오늘</div>
      </div>
      <div class="top5-score">
        <div class="top5-score-val ${scoreCls}">${s.combined_score}</div>
        <div class="top5-score-label">점수</div>
      </div>
      <div class="top5-rec ${recClass}">${recLabel}</div>
    </div>`;
  }).join('');
}

// ── 검색 ───────────────────────────────────────────
function quickPick(market, ticker) {
  document.getElementById('marketSelect').value = market;
  document.getElementById('tickerInput').value = ticker;
  analyzeStock();
}

// 페이지 로드 시 TOP5 자동 로드
window.addEventListener('DOMContentLoaded', () => loadTop5());

async function analyzeStock() {
  const market = document.getElementById('marketSelect').value;
  const ticker = document.getElementById('tickerInput').value.trim();
  if (!ticker) return;

  showLoading(true);
  hideResult();
  hideError();

  try {
    const res = await fetch(`${API}/api/analyze/${market}/${ticker}`);
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || '분석 실패');
    }
    const data = await res.json();
    showResult(data);
  } catch (e) {
    showError(e.message);
  } finally {
    showLoading(false);
  }
}

function showLoading(show) {
  document.getElementById('loading').classList.toggle('hidden', !show);
}
function hideResult() { document.getElementById('result').classList.add('hidden'); }
function hideError() { document.getElementById('error').classList.add('hidden'); }
function showError(msg) {
  const el = document.getElementById('error');
  el.textContent = '⚠️ ' + msg;
  el.classList.remove('hidden');
}

function showResult(data) {
  document.getElementById('result').classList.remove('hidden');

  // Overview
  document.getElementById('stockName').textContent = data.name;
  document.getElementById('stockTicker').textContent = `${data.ticker} · ${data.market} 시장`;

  const fmt = (n) => data.currency === 'KRW'
    ? n.toLocaleString('ko-KR') + ' 원'
    : '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  document.getElementById('stockPrice').textContent = fmt(data.current_price);

  // Price changes
  const changes = data.technical.price_changes;
  const pcEl = document.getElementById('priceChanges');
  pcEl.innerHTML = ['1d', '1w', '1m', '3m'].map(k => {
    const v = changes[k];
    const cls = v > 0 ? 'up' : v < 0 ? 'down' : 'flat';
    const sign = v > 0 ? '+' : '';
    const label = { '1d': '1일', '1w': '1주', '1m': '1개월', '3m': '3개월' }[k];
    return `<div class="price-change-item ${cls}">${sign}${v}%<span>${label}</span></div>`;
  }).join('');

  // Score gauge
  drawGauge(data.combined_score);
  document.getElementById('scoreValue').textContent = data.combined_score;

  // AI recommendation
  const ai = data.ai_recommendation;
  const badge = document.getElementById('recBadge');
  badge.textContent = ai.recommendation === 'BUY' ? '매수 (BUY)' : ai.recommendation === 'SELL' ? '매도 (SELL)' : '보류 (HOLD)';
  badge.className = 'rec-badge rec-' + ai.recommendation.toLowerCase();

  document.getElementById('aiSummary').textContent = ai.summary || '';
  document.getElementById('aiReasoning').textContent = ai.reasoning || '';

  document.getElementById('aiMeta').innerHTML = [
    ai.confidence != null ? `<div class="ai-meta-item">${ai.confidence}%<span>신뢰도</span></div>` : '',
    ai.risk_level ? `<div class="ai-meta-item">${ai.risk_level}<span>위험도</span></div>` : '',
    ai.investment_horizon ? `<div class="ai-meta-item">${ai.investment_horizon}<span>투자 기간</span></div>` : '',
    ai.target_price ? `<div class="ai-meta-item">${fmt(ai.target_price)}<span>목표가</span></div>` : '',
  ].join('');

  let listsHtml = '';
  if (ai.strengths && ai.strengths.length) {
    listsHtml += `<div class="ai-list"><h4>✅ 강점</h4><ul class="strengths">${ai.strengths.map(s => `<li>${s}</li>`).join('')}</ul></div>`;
  }
  if (ai.risks && ai.risks.length) {
    listsHtml += `<div class="ai-list"><h4>⚠️ 위험 요인</h4><ul class="risks">${ai.risks.map(r => `<li>${r}</li>`).join('')}</ul></div>`;
  }
  document.getElementById('aiLists').innerHTML = listsHtml;

  // Technical signals
  const techScore = data.technical.score;
  document.getElementById('techScore').textContent = techScore + '점';
  document.getElementById('techScore').style.color = scoreColor(techScore);
  document.getElementById('techSignals').innerHTML = data.technical.signals.map(s => `
    <div class="signal signal-${s.type}">
      <div class="signal-dot"></div>
      <div><strong>${s.indicator}</strong> ${s.message}</div>
    </div>`).join('');

  // Fundamental signals
  const fundScore = data.fundamental.score;
  document.getElementById('fundScore').textContent = fundScore + '점';
  document.getElementById('fundScore').style.color = scoreColor(fundScore);
  document.getElementById('fundSignals').innerHTML = data.fundamental.signals.map(s => `
    <div class="signal signal-${s.type}">
      <div class="signal-dot"></div>
      <div><strong>${s.indicator}</strong> ${s.message}</div>
    </div>`).join('');

  // Fundamental metrics
  const m = data.fundamental.metrics;
  const metricItems = [
    ['PER', m.per != null ? m.per : '-'],
    ['PBR', m.pbr != null ? m.pbr : '-'],
    ['ROE', m.roe != null ? m.roe + '%' : '-'],
    ['배당수익률', m.dividend_yield != null ? m.dividend_yield + '%' : '-'],
    ['순이익률', m.profit_margin != null ? m.profit_margin + '%' : '-'],
    ['부채비율', m.debt_to_equity != null ? m.debt_to_equity + '%' : '-'],
    ['매출성장률', m.revenue_growth != null ? m.revenue_growth + '%' : '-'],
  ].filter(([, v]) => v !== '-');

  document.getElementById('fundMetrics').innerHTML = metricItems.map(([l, v]) => `
    <div class="metric-item">
      <div class="metric-label">${l}</div>
      <div class="metric-value">${v}</div>
    </div>`).join('');

  // Technical indicators table
  const ind = data.technical.indicators;
  document.getElementById('indicatorsGrid').innerHTML = [
    ['RSI(14)', ind.rsi != null ? ind.rsi.toFixed(1) : '-'],
    ['MACD', ind.macd != null ? ind.macd.toFixed(4) : '-'],
    ['Signal', ind.macd_signal != null ? ind.macd_signal.toFixed(4) : '-'],
    ['MA5', ind.ma5 != null ? formatPrice(ind.ma5, data.currency) : '-'],
    ['MA20', ind.ma20 != null ? formatPrice(ind.ma20, data.currency) : '-'],
    ['MA60', ind.ma60 != null ? formatPrice(ind.ma60, data.currency) : '-'],
    ['MA120', ind.ma120 != null ? formatPrice(ind.ma120, data.currency) : '-'],
    ['BB 상단', ind.bb_upper != null ? formatPrice(ind.bb_upper, data.currency) : '-'],
    ['BB 중단', ind.bb_middle != null ? formatPrice(ind.bb_middle, data.currency) : '-'],
    ['BB 하단', ind.bb_lower != null ? formatPrice(ind.bb_lower, data.currency) : '-'],
  ].map(([l, v]) => `
    <div class="indicator-item">
      <div class="ind-label">${l}</div>
      <div class="ind-value">${v}</div>
    </div>`).join('');

  // Store chart data and draw
  chartData = data.technical.chart_data;
  const firstTab = document.querySelector('.tab-btn');
  showChart('price', firstTab);

  // Scroll to result
  document.getElementById('result').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function formatPrice(v, currency) {
  if (currency === 'KRW') return v.toLocaleString('ko-KR');
  return v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function scoreColor(score) {
  if (score >= 65) return '#22c55e';
  if (score <= 40) return '#ef4444';
  return '#f59e0b';
}

function drawGauge(score) {
  const canvas = document.getElementById('scoreGauge');
  const ctx = canvas.getContext('2d');
  if (gaugeChart) gaugeChart.destroy();

  const color = score >= 65 ? '#22c55e' : score <= 40 ? '#ef4444' : '#f59e0b';
  gaugeChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      datasets: [{
        data: [score, 100 - score],
        backgroundColor: [color, '#252836'],
        borderWidth: 0,
        borderRadius: 4,
      }]
    },
    options: {
      cutout: '72%',
      rotation: -90,
      circumference: 180,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      animation: { duration: 800 },
    }
  });
}

function showChart(type, btnEl) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  if (btnEl) btnEl.classList.add('active');

  if (!chartData) return;
  if (mainChart) mainChart.destroy();

  const ctx = document.getElementById('mainChart').getContext('2d');
  const labels = chartData.dates;

  const gridColor = 'rgba(255,255,255,0.05)';
  const textColor = '#9ba3bf';

  const baseOpts = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { labels: { color: textColor, boxWidth: 12, font: { size: 12 } } },
      tooltip: { backgroundColor: '#1a1d27', titleColor: '#e8eaf0', bodyColor: '#9ba3bf', borderColor: '#2e3347', borderWidth: 1 }
    },
    scales: {
      x: { ticks: { color: textColor, maxTicksLimit: 10, font: { size: 11 } }, grid: { color: gridColor } },
      y: { ticks: { color: textColor, font: { size: 11 } }, grid: { color: gridColor } },
    },
  };

  if (type === 'price') {
    mainChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          { label: '종가', data: chartData.close, borderColor: '#6c63ff', backgroundColor: 'rgba(108,99,255,0.08)', borderWidth: 2, pointRadius: 0, tension: 0.1, fill: true },
          { label: 'MA5', data: chartData.ma5, borderColor: '#f59e0b', borderWidth: 1.5, pointRadius: 0, tension: 0.1, borderDash: [4, 3] },
          { label: 'MA20', data: chartData.ma20, borderColor: '#22c55e', borderWidth: 1.5, pointRadius: 0, tension: 0.1 },
          { label: 'MA60', data: chartData.ma60, borderColor: '#ef4444', borderWidth: 1.5, pointRadius: 0, tension: 0.1 },
          { label: 'BB상단', data: chartData.bb_upper, borderColor: 'rgba(156,163,175,0.4)', borderWidth: 1, pointRadius: 0, tension: 0.1, borderDash: [2, 4] },
          { label: 'BB하단', data: chartData.bb_lower, borderColor: 'rgba(156,163,175,0.4)', borderWidth: 1, pointRadius: 0, tension: 0.1, borderDash: [2, 4] },
        ]
      },
      options: baseOpts,
    });
  } else if (type === 'rsi') {
    mainChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          { label: 'RSI(14)', data: chartData.rsi, borderColor: '#6c63ff', borderWidth: 2, pointRadius: 0, tension: 0.2 },
        ]
      },
      options: {
        ...baseOpts,
        plugins: {
          ...baseOpts.plugins,
          annotation: {},
        },
        scales: {
          ...baseOpts.scales,
          y: { ...baseOpts.scales.y, min: 0, max: 100,
            ticks: { color: textColor, callback: (v) => v, stepSize: 10 },
            grid: { color: (ctx) => ctx.tick.value === 30 || ctx.tick.value === 70 ? 'rgba(239,68,68,0.3)' : gridColor } }
        }
      }
    });
  } else if (type === 'macd') {
    mainChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { type: 'line', label: 'MACD', data: chartData.macd, borderColor: '#6c63ff', borderWidth: 2, pointRadius: 0, tension: 0.1 },
          { type: 'line', label: 'Signal', data: chartData.macd_signal, borderColor: '#f59e0b', borderWidth: 1.5, pointRadius: 0, tension: 0.1 },
          {
            label: 'Histogram',
            data: chartData.macd_hist,
            backgroundColor: chartData.macd_hist.map(v => v >= 0 ? 'rgba(34,197,94,0.6)' : 'rgba(239,68,68,0.6)'),
          },
        ]
      },
      options: baseOpts,
    });
  } else if (type === 'volume') {
    mainChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: '거래량',
          data: chartData.volume,
          backgroundColor: 'rgba(108,99,255,0.5)',
          borderRadius: 2,
        }]
      },
      options: baseOpts,
    });
  }
}

document.getElementById('tickerInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') analyzeStock();
});
