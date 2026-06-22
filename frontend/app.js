const API = '';
let mainChart = null, chartData = null, gaugeChart = null;

// ── TOP10 (폴링 방식) ──────────────────────────────────────────────────────
let pollTimer = null;
let pollRetries = 0;
const MAX_RETRIES = 6;

async function loadTop10(force = false) {
  const btn = document.getElementById('refreshBtn');
  btn.disabled = true;
  pollRetries = 0;
  if (force) {
    document.getElementById('top10Content').classList.add('hidden');
    document.getElementById('top10Loading').classList.remove('hidden');
    document.getElementById('top10Loading').innerHTML =
      `<div class="spinner"></div><div><p>국내 종목 분석 중...</p><p class="loading-sub">잠시만 기다려 주세요</p></div>`;
  }
  clearTimeout(pollTimer);
  await pollTop10(force);
}

async function pollTop10(forceRefresh = false) {
  try {
    const url = forceRefresh ? `${API}/api/top10?refresh=true` : `${API}/api/top10`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const hasData = (data.kr?.length || 0) > 0;

    // 진행 상황 표시
    if (data.computing) {
      const prog = data.progress || '분석 중...';
      const cnt = data.total > 0 ? ` (${data.done}/${data.total})` : '';
      const el = document.querySelector('#top10Loading p');
      if (el) el.textContent = prog + cnt;
    }

    if (hasData) {
      renderTop10List('krList', data.kr || [], 'KR');
      renderTop10List('usList', data.us || [], 'US');
      document.querySelector('.top10-grid').classList.add('kr-only');
      document.getElementById('usComingSoon').textContent = '준비 중';
      document.getElementById('top10Content').classList.remove('hidden');
      document.getElementById('top10Loading').classList.add('hidden');
      document.getElementById('refreshBtn').disabled = false;
      if (data.briefing && Object.keys(data.briefing).length) renderBriefing(data.briefing);
      pollRetries = 0;
      return;
    }

    // 오류 표시 (데이터도 없고 computing도 끝난 경우)
    if (data.error && !data.computing) {
      pollRetries++;
      if (pollRetries >= MAX_RETRIES) {
        document.getElementById('top10Loading').innerHTML =
          `<p style="color:var(--sell);padding:16px">⚠️ ${data.error}</p>`;
        document.getElementById('refreshBtn').disabled = false;
        return;
      }
    }

    // 계산 중이면 3초마다, 아니면 결과 없으므로 재계산 요청
    if (data.computing) {
      pollTimer = setTimeout(() => pollTop10(false), 3000);
    } else {
      // computing 끝났는데 데이터 없음 → 재계산 트리거
      const delay = Math.min(5000 * (pollRetries + 1), 20000);
      pollTimer = setTimeout(() => pollTop10(true), delay);
    }
  } catch (err) {
    pollRetries++;
    const delay = Math.min(5000 * pollRetries, 20000);
    if (pollRetries >= MAX_RETRIES) {
      document.getElementById('top10Loading').innerHTML =
        `<p style="color:var(--sell);padding:16px">⚠️ 서버에 연결할 수 없습니다. 페이지를 새로고침 해주세요.</p>`;
      document.getElementById('refreshBtn').disabled = false;
      return;
    }
    pollTimer = setTimeout(() => pollTop10(false), delay);
  }
}

function renderTop10List(elId, stocks, market) {
  const el = document.getElementById(elId);
  if (!stocks.length) { el.innerHTML = '<p style="color:var(--text2);padding:12px">데이터 없음</p>'; return; }

  el.innerHTML = stocks.map((s, i) => {
    const rankClass = i === 0 ? 'rank-1' : i === 1 ? 'rank-2' : i === 2 ? 'rank-3' : 'rank-other';
    const price = market === 'KR'
      ? s.current_price.toLocaleString('ko-KR') + '원'
      : '$' + s.current_price.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
    const d1 = fmtChange(s.price_change_1d);
    const m1 = fmtChange(s.price_change_1m);
    const m3 = fmtChange(s.price_change_3m);
    const scoreColor = s.combined_score >= 65 ? 'var(--buy)' : s.combined_score <= 40 ? 'var(--sell)' : 'var(--hold)';
    const recMap = {
      '적극매수': 'badge-buy', '매수': 'badge-buy', '분할매수': 'badge-hold',
      '관망': 'badge-hold', '회피': 'badge-sell',
      'BUY': 'badge-buy', 'SELL': 'badge-sell', 'HOLD': 'badge-hold',
    };
    const badgeClass = recMap[s.recommendation] || 'badge-hold';
    const rrTxt = s.risk_reward != null ? `R/R ${s.risk_reward}` : '';
    const rrCls = s.risk_reward >= 2 ? 'up' : s.risk_reward < 1 ? 'down' : 'flat';
    const setupTxt = s.setup_label ? `<span class="top10-setup grade-${s.setup_grade||'D'}">${s.setup_label}</span>` : '';
    let flowTxt = '';
    if (market === 'KR' && s.foreign_net_eok != null) {
      const fcls = s.foreign_net_eok > 0 ? 'up' : s.foreign_net_eok < 0 ? 'down' : 'flat';
      const fsign = s.foreign_net_eok > 0 ? '+' : '';
      flowTxt = `· <span class="${fcls}">외인 ${fsign}${s.foreign_net_eok.toLocaleString()}억</span>`;
    }

    return `
    <div class="top10-item" onclick="quickPick('${market}','${s.ticker}')">
      <div class="top10-rank ${rankClass}">${i+1}</div>
      <div class="top10-info">
        <div class="top10-name">${s.name} ${setupTxt}</div>
        <div class="top10-sub">${s.ticker} · ${price} ${rrTxt ? `· <span class="${rrCls}">${rrTxt}</span>` : ''} ${flowTxt}</div>
      </div>
      <div class="top10-changes">
        <span class="${d1.cls}">${d1.str} 1일</span><br>
        <span class="${m1.cls}">${m1.str} 1달</span><br>
        <span class="${m3.cls}">${m3.str} 3달</span>
      </div>
      <div class="top10-score">
        <div class="top10-score-val" style="color:${scoreColor}">${s.combined_score}</div>
        <div class="top10-score-lbl">점수</div>
      </div>
      <div class="top10-badge ${badgeClass}">${s.recommendation || '관망'}</div>
    </div>`;
  }).join('');
}

function renderBriefing(b) {
  const card = document.getElementById('briefingCard');
  const content = document.getElementById('briefingContent');
  const moodClass = b.mood === '긍정적' ? 'mood-positive' : b.mood === '부정적' ? 'mood-negative' : 'mood-neutral';
  const moodIcon = b.mood === '긍정적' ? '📈' : b.mood === '부정적' ? '📉' : '➡️';
  const issues = (b.key_issues || []).map(i => `<li>${i}</li>`).join('');
  content.innerHTML = `
    <div class="briefing-mood ${moodClass}">${moodIcon} ${b.mood} — ${b.mood_reason || ''}</div>
    <ul class="briefing-issues">${issues}</ul>
    ${b.top_pick ? `<div class="briefing-highlight">⭐ ${b.top_pick}</div>` : ''}
    ${b.caution ? `<div class="briefing-caution">⚠️ ${b.caution}</div>` : ''}
  `;
  card.classList.remove('hidden');
}

function fmtChange(v) {
  if (v == null) return { str: '-', cls: 'flat' };
  const sign = v > 0 ? '+' : '';
  return { str: `${sign}${v}%`, cls: v > 0 ? 'up' : v < 0 ? 'down' : 'flat' };
}

// ── Search Dropdown ────────────────────────────────────────────────────────
let searchTimer = null;
const tickerInput = document.getElementById('tickerInput');
const dropdown = document.getElementById('searchDropdown');

tickerInput.addEventListener('input', () => {
  clearTimeout(searchTimer);
  const q = tickerInput.value.trim();
  if (q.length < 1) { dropdown.classList.add('hidden'); return; }
  searchTimer = setTimeout(() => fetchSearch(q), 280);
});
tickerInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') { dropdown.classList.add('hidden'); analyzeStock(); }
  if (e.key === 'Escape') dropdown.classList.add('hidden');
});
document.addEventListener('click', e => {
  if (!e.target.closest('.input-wrap')) dropdown.classList.add('hidden');
});

async function fetchSearch(q) {
  const market = document.getElementById('marketSelect').value;
  try {
    const res = await fetch(`${API}/api/search?query=${encodeURIComponent(q)}&market=${market}`);
    if (!res.ok) { dropdown.classList.add('hidden'); return; }
    const text = await res.text();
    if (!text) { dropdown.classList.add('hidden'); return; }
    const data = JSON.parse(text);
    const results = data.results || [];
    if (!results.length) { dropdown.classList.add('hidden'); return; }
    dropdown.innerHTML = results.map(r => `
      <div class="search-item" onclick="selectStock('${r.market}','${r.ticker}')">
        <span class="search-item-ticker">${r.ticker}</span>
        <span class="search-item-name">${r.name}</span>
        <span class="search-item-market">${r.market}</span>
      </div>`).join('');
    dropdown.classList.remove('hidden');
  } catch { dropdown.classList.add('hidden'); }
}

function selectStock(market, ticker) {
  document.getElementById('marketSelect').value = market;
  tickerInput.value = ticker;
  dropdown.classList.add('hidden');
  analyzeStock();
}

// ── Analysis ───────────────────────────────────────────────────────────────
function quickPick(market, ticker) {
  document.getElementById('marketSelect').value = market;
  tickerInput.value = ticker;
  analyzeStock();
}

async function analyzeStock() {
  const market = document.getElementById('marketSelect').value;
  const ticker = tickerInput.value.trim();
  if (!ticker) return;

  document.getElementById('loading').classList.remove('hidden');
  document.getElementById('result').classList.add('hidden');
  document.getElementById('error').classList.add('hidden');

  try {
    const res = await fetch(`${API}/api/analyze/${market}/${ticker}`);
    if (!res.ok) {
      let msg = '분석 실패';
      try { const e = await res.json(); msg = e.detail || msg; } catch {}
      throw new Error(msg);
    }
    showResult(await res.json());
  } catch (e) {
    const el = document.getElementById('error');
    el.textContent = '⚠️ ' + e.message;
    el.classList.remove('hidden');
  } finally {
    document.getElementById('loading').classList.add('hidden');
  }
}

// ── 매매 플랜 렌더링 ────────────────────────────────────────────────────────
function renderTradePlan(s, fmt) {
  const badge = document.getElementById('setupBadge');
  const desc = document.getElementById('setupDesc');
  const levels = document.getElementById('planLevels');
  const rr = document.getElementById('planRR');

  badge.textContent = `${s.setup_label || '관망'} (${s.setup_grade || '-'}등급)`;
  badge.className = 'setup-badge grade-' + (s.setup_grade || 'D');
  desc.textContent = s.setup_desc || '';

  if (s.entry_low && s.target && s.stop) {
    levels.innerHTML = `
      <div class="plan-level entry">
        <div class="plan-level-label">📥 진입 구간</div>
        <div class="plan-level-val">${fmt(s.entry_low)}</div>
        <div class="plan-level-sub" style="color:var(--text2)">~ ${fmt(s.entry_high)}</div>
      </div>
      <div class="plan-level target">
        <div class="plan-level-label">🎯 목표가</div>
        <div class="plan-level-val">${fmt(s.target)}</div>
        <div class="plan-level-sub up">+${s.upside_pct}%</div>
      </div>
      <div class="plan-level stop">
        <div class="plan-level-label">🛑 손절가</div>
        <div class="plan-level-val">${fmt(s.stop)}</div>
        <div class="plan-level-sub down">-${s.downside_pct}%</div>
      </div>`;
    const rrCls = (s.risk_reward >= 2) ? 'rr-good' : (s.risk_reward < 1 ? 'rr-bad' : '');
    rr.innerHTML = `
      <div class="plan-rr-item">손익비(R/R)<strong class="${rrCls}">${s.risk_reward ?? '-'} : 1</strong></div>
      <div class="plan-rr-item">기대수익<strong class="up">+${s.upside_pct}%</strong></div>
      <div class="plan-rr-item">감수손실<strong class="down">-${s.downside_pct}%</strong></div>
      <div class="plan-rr-item">일변동성(ATR)<strong>${s.atr_pct}%</strong></div>`;
    rr.style.display = 'flex';
    levels.style.display = 'grid';
  } else {
    levels.innerHTML = `<p class="plan-empty">현재는 명확한 진입 구간이 없습니다. ${s.setup_label === '과열 관망' ? '조정 후 재진입을 노리세요.' : '추세가 잡힐 때까지 관망을 권장합니다.'}</p>`;
    levels.style.display = 'block';
    rr.style.display = 'none';
  }
}

// ── Result Rendering ───────────────────────────────────────────────────────
function showResult(data) {
  document.getElementById('result').classList.remove('hidden');

  const fmt = n => data.currency === 'KRW'
    ? n.toLocaleString('ko-KR') + ' 원'
    : '$' + n.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});

  document.getElementById('stockName').textContent = data.name;
  document.getElementById('stockTicker').textContent = `${data.ticker} · ${data.market}`;
  document.getElementById('stockPrice').textContent = fmt(data.current_price);

  const ch = data.technical.price_changes;
  document.getElementById('priceChanges').innerHTML = ['1d','1w','1m','3m'].map(k => {
    const v = ch[k], cls = v > 0 ? 'up' : v < 0 ? 'down' : 'flat';
    const lbl = {'1d':'1일','1w':'1주','1m':'1개월','3m':'3개월'}[k] || k;
    return `<div class="price-change-item ${cls}">${v > 0?'+':''}${v}%<span>${lbl}</span></div>`;
  }).join('');

  drawGauge(data.combined_score);
  document.getElementById('scoreValue').textContent = data.combined_score;

  // ── 매매 플랜 카드 ──────────────────────────────────────────────────
  renderTradePlan(data.trade_setup || {}, fmt);

  // ── 수급 동향 (외국인·기관, KR 전용) ─────────────────────────────────
  renderInvestorFlow(data.investor_flow);

  const ai = data.ai_recommendation;
  const badge = document.getElementById('recBadge');
  const recColors = {'적극매수':'rec-buy','매수':'rec-buy','분할매수':'rec-hold','관망':'rec-hold','회피':'rec-sell','BUY':'rec-buy','SELL':'rec-sell','HOLD':'rec-hold'};
  badge.textContent = data.recommendation || ai.recommendation || '관망';
  badge.className = 'rec-badge ' + (recColors[data.recommendation || ai.recommendation] || 'rec-hold');
  document.getElementById('aiSummary').textContent = ai.summary || '';
  document.getElementById('aiAction').textContent = ai.action_plan || '';
  document.getElementById('aiAction').style.display = ai.action_plan ? 'block' : 'none';
  document.getElementById('aiReasoning').textContent = ai.reasoning || '';
  document.getElementById('aiMeta').innerHTML = [
    ai.confidence != null ? `<div class="ai-meta-item">${ai.confidence}%<span>신뢰도</span></div>` : '',
    ai.risk_level ? `<div class="ai-meta-item">${ai.risk_level}<span>위험도</span></div>` : '',
    ai.investment_horizon ? `<div class="ai-meta-item">${ai.investment_horizon}<span>투자기간</span></div>` : '',
    ai.data_source ? `<div class="ai-meta-item" style="font-size:10px;color:var(--text2)">${ai.data_source}<span>분석출처</span></div>` : '',
  ].join('');

  let listsHtml = '';
  if (ai.strengths?.length) listsHtml += `<div class="ai-list"><h4>✅ 강점</h4><ul class="strengths">${ai.strengths.map(s=>`<li>${s}</li>`).join('')}</ul></div>`;
  if (ai.risks?.length) listsHtml += `<div class="ai-list"><h4>⚠️ 위험</h4><ul class="risks">${ai.risks.map(r=>`<li>${r}</li>`).join('')}</ul></div>`;
  document.getElementById('aiLists').innerHTML = listsHtml;

  const ts = data.technical.score;
  document.getElementById('techScore').textContent = ts + '점';
  document.getElementById('techScore').style.color = scoreColor(ts);
  document.getElementById('techSignals').innerHTML = data.technical.signals.map(s =>
    `<div class="signal signal-${s.type}"><div class="signal-dot"></div><div><strong>${s.indicator}</strong> ${s.message}</div></div>`
  ).join('');

  const fs = data.fundamental.score;
  document.getElementById('fundScore').textContent = fs + '점';
  document.getElementById('fundScore').style.color = scoreColor(fs);
  document.getElementById('fundSignals').innerHTML = data.fundamental.signals.map(s =>
    `<div class="signal signal-${s.type}"><div class="signal-dot"></div><div><strong>${s.indicator}</strong> ${s.message}</div></div>`
  ).join('');

  const m = data.fundamental.metrics;
  document.getElementById('fundMetrics').innerHTML = [
    ['PER', m.per], ['PBR', m.pbr], ['ROE', m.roe != null ? m.roe + '%' : null],
    ['배당', m.dividend_yield != null ? m.dividend_yield + '%' : null],
    ['순이익률', m.profit_margin != null ? m.profit_margin + '%' : null],
    ['부채비율', m.debt_to_equity != null ? m.debt_to_equity + '%' : null],
  ].filter(([,v]) => v != null).map(([l,v]) =>
    `<div class="metric-item"><div class="metric-label">${l}</div><div class="metric-value">${v}</div></div>`
  ).join('');

  const ind = data.technical.indicators;
  document.getElementById('indicatorsGrid').innerHTML = [
    ['RSI(14)', ind.rsi != null ? ind.rsi.toFixed(1) : '-'],
    ['MACD', ind.macd != null ? ind.macd.toFixed(4) : '-'],
    ['Signal', ind.macd_signal != null ? ind.macd_signal.toFixed(4) : '-'],
    ['MA20', ind.ma20 != null ? fmtNum(ind.ma20, data.currency) : '-'],
    ['MA60', ind.ma60 != null ? fmtNum(ind.ma60, data.currency) : '-'],
    ['BB 상단', ind.bb_upper != null ? fmtNum(ind.bb_upper, data.currency) : '-'],
    ['BB 하단', ind.bb_lower != null ? fmtNum(ind.bb_lower, data.currency) : '-'],
  ].map(([l,v]) =>
    `<div class="indicator-item"><div class="ind-label">${l}</div><div class="ind-value">${v}</div></div>`
  ).join('');

  chartData = data.technical.chart_data;
  showChart('price', document.querySelector('.tab-btn'));
  document.getElementById('result').scrollIntoView({behavior:'smooth', block:'start'});
}

function fmtNum(v, currency) {
  return currency === 'KRW'
    ? Math.round(v).toLocaleString('ko-KR')
    : v.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
}

function scoreColor(s) {
  return s >= 65 ? 'var(--buy)' : s <= 40 ? 'var(--sell)' : 'var(--hold)';
}

function drawGauge(score) {
  if (gaugeChart) gaugeChart.destroy();
  const ctx = document.getElementById('scoreGauge').getContext('2d');
  const color = scoreColor(score);
  gaugeChart = new Chart(ctx, {
    type: 'doughnut',
    data: { datasets: [{ data: [score, 100-score], backgroundColor: [color, '#252836'], borderWidth: 0, borderRadius: 4 }] },
    options: { cutout:'72%', rotation:-90, circumference:180, plugins:{legend:{display:false},tooltip:{enabled:false}}, animation:{duration:700} }
  });
}

function showChart(type, btnEl) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  if (btnEl) btnEl.classList.add('active');
  if (!chartData) return;
  if (mainChart) mainChart.destroy();

  const ctx = document.getElementById('mainChart').getContext('2d');
  const labels = chartData.dates;
  const grid = 'rgba(255,255,255,0.05)', tc = '#9ba3bf';
  const base = {
    responsive:true, maintainAspectRatio:false,
    interaction:{mode:'index',intersect:false},
    plugins:{
      legend:{labels:{color:tc,boxWidth:12,font:{size:11}}},
      tooltip:{backgroundColor:'#1a1d27',titleColor:'#e8eaf0',bodyColor:tc,borderColor:'#2e3347',borderWidth:1}
    },
    scales:{
      x:{ticks:{color:tc,maxTicksLimit:10,font:{size:10}},grid:{color:grid}},
      y:{ticks:{color:tc,font:{size:10}},grid:{color:grid}}
    }
  };

  if (type === 'price') {
    mainChart = new Chart(ctx, { type:'line', data:{ labels, datasets:[
      {label:'종가',data:chartData.close,borderColor:'#6c63ff',backgroundColor:'rgba(108,99,255,.08)',borderWidth:2,pointRadius:0,tension:.1,fill:true},
      {label:'MA20',data:chartData.ma20,borderColor:'#22c55e',borderWidth:1.5,pointRadius:0,tension:.1},
      {label:'MA60',data:chartData.ma60,borderColor:'#ef4444',borderWidth:1.5,pointRadius:0,tension:.1},
      {label:'BB상단',data:chartData.bb_upper,borderColor:'rgba(156,163,175,.4)',borderWidth:1,pointRadius:0,borderDash:[2,4]},
      {label:'BB하단',data:chartData.bb_lower,borderColor:'rgba(156,163,175,.4)',borderWidth:1,pointRadius:0,borderDash:[2,4]},
    ]}, options:base });
  } else if (type === 'rsi') {
    mainChart = new Chart(ctx, { type:'line', data:{ labels, datasets:[
      {label:'RSI(14)',data:chartData.rsi,borderColor:'#6c63ff',borderWidth:2,pointRadius:0,tension:.2}
    ]}, options:{...base, scales:{...base.scales, y:{...base.scales.y,min:0,max:100}}} });
  } else if (type === 'macd') {
    mainChart = new Chart(ctx, { type:'bar', data:{ labels, datasets:[
      {type:'line',label:'MACD',data:chartData.macd,borderColor:'#6c63ff',borderWidth:2,pointRadius:0,tension:.1},
      {type:'line',label:'Signal',data:chartData.macd_signal,borderColor:'#f59e0b',borderWidth:1.5,pointRadius:0},
      {label:'Histogram',data:chartData.macd_hist,backgroundColor:chartData.macd_hist?.map(v=>v>=0?'rgba(34,197,94,.6)':'rgba(239,68,68,.6)')},
    ]}, options:base });
  } else if (type === 'volume') {
    mainChart = new Chart(ctx, { type:'bar', data:{ labels, datasets:[
      {label:'거래량',data:chartData.volume,backgroundColor:'rgba(108,99,255,.5)',borderRadius:2}
    ]}, options:base });
  }
}

// ── 미국 증시 → 국내 증시 전망 ───────────────────────────────────────────────
async function loadMarketOutlook() {
  try {
    const res = await fetch(`${API}/api/market-outlook`);
    if (!res.ok) return;
    const d = await res.json();
    if (!d) return;
    const hasIdx = d.indices && Object.keys(d.indices).length > 0;
    if (!hasIdx && !d.kr_outlook) return;
    renderOutlook(d);
  } catch { /* 전망 실패는 무시 */ }
}

function renderOutlook(d) {
  const card = document.getElementById('outlookCard');
  const idxEl = document.getElementById('outlookIndices');
  const bodyEl = document.getElementById('outlookBody');
  const dirEl = document.getElementById('outlookDir');

  // 지표 칩
  const idx = d.indices || {};
  idxEl.innerHTML = Object.entries(idx).map(([k, v]) => {
    const cls = v.change > 0 ? 'up' : v.change < 0 ? 'down' : 'flat';
    const sign = v.change > 0 ? '+' : '';
    return `<div class="idx-chip">
      <div class="idx-name">${k}</div>
      <div class="idx-val">${v.value.toLocaleString()}</div>
      <div class="idx-chg ${cls}">${sign}${v.change}%</div>
    </div>`;
  }).join('');

  // 방향 배지
  if (d.direction) {
    const dcls = d.direction === '강세' ? 'up' : d.direction === '약세' ? 'down' : 'flat';
    dirEl.textContent = `예상: ${d.direction}`;
    dirEl.className = 'outlook-dir ' + dcls;
  } else {
    dirEl.textContent = '';
  }

  // 본문
  let html = '';
  if (d.us_summary) html += `<div class="outlook-row"><span class="outlook-tag">🇺🇸 미국장</span>${d.us_summary}</div>`;
  if (d.kr_outlook) html += `<div class="outlook-row main"><span class="outlook-tag">🇰🇷 국내 전망</span>${d.kr_outlook}</div>`;
  if (d.fx_note) html += `<div class="outlook-row"><span class="outlook-tag">💱 환율</span>${d.fx_note}</div>`;
  if (d.watch_sectors?.length) html += `<div class="outlook-sectors"><strong>👀 주목 섹터</strong><ul>${d.watch_sectors.map(s => `<li>${s}</li>`).join('')}</ul></div>`;
  if (d.special_notes?.length) html += `<div class="outlook-notes"><strong>⚠️ 특이사항</strong><ul>${d.special_notes.map(s => `<li>${s}</li>`).join('')}</ul></div>`;
  bodyEl.innerHTML = html;

  card.classList.remove('hidden');
}

// ── 수급 동향 렌더링 ─────────────────────────────────────────────────────────
function renderInvestorFlow(flow) {
  const card = document.getElementById('flowCard');
  if (!flow || !flow.metrics || flow.metrics.foreign_net_eok == null) {
    card.classList.add('hidden');
    return;
  }
  const m = flow.metrics;
  document.getElementById('flowPeriod').textContent = `최근 ${m.days || 20}일`;

  const box = (label, eok) => {
    const cls = eok > 0 ? 'up' : eok < 0 ? 'down' : 'flat';
    const sign = eok > 0 ? '+' : '';
    return `<div class="flow-box ${cls}">
      <div class="flow-box-label">${label}</div>
      <div class="flow-box-val">${sign}${(eok || 0).toLocaleString()}억</div>
      <div class="flow-box-sub">${eok > 0 ? '순매수' : eok < 0 ? '순매도' : '중립'}</div>
    </div>`;
  };
  document.getElementById('flowMetrics').innerHTML =
    box('외국인', m.foreign_net_eok) + box('기관', m.inst_net_eok);

  document.getElementById('flowSignals').innerHTML = (flow.signals || []).map(s =>
    `<div class="signal signal-${s.type}"><div class="signal-dot"></div><div><strong>${s.indicator}</strong> ${s.message}</div></div>`
  ).join('');

  card.classList.remove('hidden');
}

// ── Init ───────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => { loadTop10(); loadMarketOutlook(); });
