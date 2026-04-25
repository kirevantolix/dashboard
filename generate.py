#!/usr/bin/env python3
"""US Stock Watchlist Dashboard Generator
Usage: python generate.py
Reads watchlist.txt, fetches data via yfinance, generates dashboard.html
"""

import yfinance as yf
import pandas as pd
import requests
import json
import math
from datetime import datetime
import xml.etree.ElementTree as ET

# ── Helpers ────────────────────────────────────────────────────────────────────

def calc_rsi(prices, n=14):
    d = prices.diff()
    g = d.clip(lower=0).ewm(com=n - 1, min_periods=n).mean()
    l = (-d.clip(upper=0)).ewm(com=n - 1, min_periods=n).mean()
    rs = g / l.replace(0, float('nan'))
    return 100 - 100 / (1 + rs)

def calc_macd(prices, fast=12, slow=26, sig=9):
    ef = prices.ewm(span=fast, adjust=False).mean()
    es = prices.ewm(span=slow, adjust=False).mean()
    m = ef - es
    s = m.ewm(span=sig, adjust=False).mean()
    return m, s, m - s

def detect_crosses(ma_s, ma_l, lookback=5):
    gc_idx, dc_idx = [], []
    for i in range(1, len(ma_s)):
        if pd.isna(ma_s.iloc[i - 1]) or pd.isna(ma_l.iloc[i - 1]):
            continue
        prev = ma_s.iloc[i - 1] - ma_l.iloc[i - 1]
        curr = ma_s.iloc[i] - ma_l.iloc[i]
        if prev < 0 < curr:
            gc_idx.append(i)
        if prev > 0 > curr:
            dc_idx.append(i)
    n = len(ma_s)
    rec = set(range(max(0, n - lookback), n))
    return gc_idx, dc_idx, bool(rec & set(gc_idx)), bool(rec & set(dc_idx))

def sentiment(text):
    t = text.lower()
    pos = sum(1 for w in [
        'surge', 'gain', 'rise', 'beat', 'growth', 'profit', 'strong',
        'rally', 'boost', 'soar', 'jump', 'upgrade', 'record', 'outperform',
        'tops', 'high', 'positive', 'bullish', 'buy', 'wins'
    ] if w in t)
    neg = sum(1 for w in [
        'fall', 'drop', 'decline', 'miss', 'loss', 'weak', 'crash', 'plunge',
        'cut', 'warn', 'risk', 'fear', 'concern', 'downgrade', 'disappoints',
        'low', 'negative', 'bearish', 'sell', 'loses'
    ] if w in t)
    return 'positive' if pos > neg else ('negative' if neg > pos else 'neutral')

def fetch_news(ticker, n=3):
    url = (
        f"https://feeds.finance.yahoo.com/rss/2.0/headline"
        f"?s={ticker}&region=US&lang=en-US"
    )
    try:
        r = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
        root = ET.fromstring(r.content)
        out = []
        for item in root.findall('.//item')[:n]:
            title = getattr(item.find('title'), 'text', '') or ''
            link = getattr(item.find('link'), 'text', '#') or '#'
            out.append({'title': title, 'link': link, 'sentiment': sentiment(title)})
        return out
    except Exception:
        return []

def overall_status(rsi, ma25, ma75, pct):
    sc = 0
    if rsi > 55:
        sc += 1
    elif rsi < 45:
        sc -= 1
    if ma25 and ma75:
        sc += 1 if ma25 > ma75 else -1
    sc += 1 if pct > 0.5 else (-1 if pct < -0.5 else 0)
    return 'bullish' if sc >= 2 else ('bearish' if sc <= -2 else 'neutral')

def to_list(series, dec=2):
    return [
        round(float(v), dec) if pd.notna(v) and not math.isnan(float(v)) else None
        for v in series
    ]

# ── Fetch Data ─────────────────────────────────────────────────────────────────

print("Reading watchlist.txt ...")
with open('watchlist.txt') as f:
    tickers = [l.strip() for l in f if l.strip() and not l.startswith('#')]

stocks = []
for sym in tickers:
    print(f"  {sym:8s}", end=' ', flush=True)
    try:
        tk = yf.Ticker(sym)
        hist = tk.history(period='6mo')
        if len(hist) < 30:
            print("skip (insufficient data)")
            continue

        close = hist['Close']
        vol = hist['Volume']

        cur = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        pct = (cur - prev) / prev * 100

        cvol = int(vol.iloc[-1])
        avgvol = float(vol.tail(11).iloc[:-1].mean())
        vratio = cvol / avgvol if avgvol else 1.0

        rsi_s = calc_rsi(close)
        rsi = float(rsi_s.iloc[-1]) if pd.notna(rsi_s.iloc[-1]) else 50.0

        macd_s, sig_s, hist_s = calc_macd(close)
        ma25 = close.rolling(25).mean()
        ma75 = close.rolling(75).mean()

        gc_idx, dc_idx, recent_gc, recent_dc = detect_crosses(ma25, ma75, 5)

        ma25_last = float(ma25.iloc[-1]) if pd.notna(ma25.iloc[-1]) else None
        ma75_last = float(ma75.iloc[-1]) if pd.notna(ma75.iloc[-1]) else None
        ma_above = bool(ma25_last and ma75_last and ma25_last > ma75_last)

        status = overall_status(rsi, ma25_last, ma75_last, pct)

        try:
            fi = tk.fast_info
            name = getattr(fi, 'long_name', None) or sym
        except Exception:
            name = sym

        news = fetch_news(sym)

        N = 60
        c60 = close.tail(N)
        dates = c60.index.strftime('%m/%d').tolist()
        n60_dates = list(c60.index)

        gm, dm = [], []
        for i in gc_idx:
            if i < len(close) and close.index[i] in n60_dates:
                p = n60_dates.index(close.index[i])
                gm.append({'x': p, 'y': round(float(close.iloc[i]), 2)})
        for i in dc_idx:
            if i < len(close) and close.index[i] in n60_dates:
                p = n60_dates.index(close.index[i])
                dm.append({'x': p, 'y': round(float(close.iloc[i]), 2)})

        stocks.append({
            'ticker': sym,
            'name': name,
            'price': round(cur, 2),
            'pct': round(pct, 2),
            'volume': cvol,
            'avgvol': int(avgvol),
            'vratio': round(vratio, 2),
            'rsi': round(rsi, 1),
            'macd': round(float(macd_s.iloc[-1]), 4),
            'signal': round(float(sig_s.iloc[-1]), 4),
            'ma25': round(ma25_last, 2) if ma25_last else None,
            'ma75': round(ma75_last, 2) if ma75_last else None,
            'ma_above': ma_above,
            'gc': recent_gc,
            'dc': recent_dc,
            'status': status,
            'news': news,
            'dates': dates,
            'prices': to_list(c60, 2),
            'ma25d': to_list(ma25.tail(N), 2),
            'ma75d': to_list(ma75.tail(N), 2),
            'machist': to_list(hist_s.tail(N), 4),
            'gm': gm,
            'dm': dm,
        })
        print("ok")
    except Exception as e:
        print(f"ERROR: {e}")

stocks.sort(key=lambda s: abs(s['pct']), reverse=True)

now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
stocks_json = json.dumps(stocks, ensure_ascii=False)

# ── HTML Template ──────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stock Watchlist Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
/* ── Reset & Base ─────────────────────────────────────────────── */
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{
  background:#0d1117;color:#e6edf3;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  font-size:13px;line-height:1.5;
  overscroll-behavior-y:contain;
}
a{color:#58a6ff;text-decoration:none}
a:hover,a:focus{text-decoration:underline}

/* ── Header ───────────────────────────────────────────────────── */
.header{
  display:flex;align-items:center;justify-content:space-between;
  padding:14px 18px;border-bottom:1px solid #30363d;background:#161b22;
  position:sticky;top:0;z-index:100;gap:10px;
}
.header-left{display:flex;flex-direction:column;gap:3px;min-width:0}
h1{font-size:18px;font-weight:700;color:#e6edf3;white-space:nowrap}
.gen-time{font-size:11px;color:#8b949e}
.header-right{text-align:right;flex-shrink:0;font-size:11px;color:#8b949e;line-height:1.6}

/* ── Heatmap ──────────────────────────────────────────────────── */
.heatmap-section{padding:14px 16px 8px}
.heatmap-section h2{
  font-size:11px;color:#8b949e;margin-bottom:8px;font-weight:600;
  text-transform:uppercase;letter-spacing:.6px;
}
.heatmap{display:flex;flex-wrap:wrap;gap:4px}
.hm-cell{
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  min-width:62px;min-height:42px;border-radius:6px;
  font-size:11px;font-weight:700;padding:4px 5px;
  border:1px solid rgba(255,255,255,.08);
  transition:transform .12s;cursor:default;
  -webkit-tap-highlight-color:transparent;user-select:none;
}
.hm-cell:hover,.hm-cell:active{transform:scale(1.1);z-index:2}
.hm-cell .hm-pct{font-size:9px;font-weight:400;margin-top:1px}

/* ── Cards Section ────────────────────────────────────────────── */
.cards-section{padding:12px 16px 40px}
.cards-grid{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(min(100%,370px),1fr));
  gap:14px;
}

/* ── Card ─────────────────────────────────────────────────────── */
.card{background:#161b22;border:1px solid #30363d;border-radius:10px;overflow:hidden;transition:border-color .15s;scroll-margin-top:58px}
.card:hover{border-color:#58a6ff55}
.status-bar{height:4px;width:100%}
.status-bar.bullish{background:linear-gradient(90deg,#238636,#2ea043)}
.status-bar.bearish{background:linear-gradient(90deg,#da3633,#f85149)}
.status-bar.neutral{background:linear-gradient(90deg,#9e6a03,#d29922)}
.card-header{padding:10px 12px 6px}
.ticker-row{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.ticker{font-size:18px;font-weight:800;color:#e6edf3}
.company-name{font-size:11px;color:#8b949e;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* ── Badges ───────────────────────────────────────────────────── */
.badge{display:inline-flex;align-items:center;gap:3px;padding:2px 7px;border-radius:20px;font-size:10px;font-weight:700}
.badge-gc{background:#2d2500;color:#d4a017;border:1px solid #d4a017}
.badge-dc{background:#1e1e1e;color:#8b949e;border:1px solid #6e7681}
.badge-status{padding:2px 7px;border-radius:20px;font-size:10px;font-weight:600}
.badge-bullish{background:#1a3824;color:#3fb950}
.badge-bearish{background:#3d1a1a;color:#f85149}
.badge-neutral{background:#2a2000;color:#d29922}
.ma-badge{font-size:10px;padding:2px 6px;border-radius:4px;background:#1c2128;color:#8b949e;border:1px solid #30363d}

/* ── Price / Volume ───────────────────────────────────────────── */
.price-row{display:flex;align-items:baseline;gap:10px;padding:0 12px 5px}
.price{font-size:22px;font-weight:700;color:#e6edf3}
.pct{font-size:14px;font-weight:700}
.pct.up{color:#3fb950}
.pct.down{color:#f85149}
.vol-row{
  display:flex;align-items:center;flex-wrap:wrap;
  gap:6px;padding:0 12px 8px;font-size:11px;color:#8b949e;
}
.vol-fire{font-size:13px}
.divider{height:1px;background:#21262d;margin:0 12px}

/* ── Stats Bar ────────────────────────────────────────────────── */
.summary-stats{display:flex;gap:8px;padding:6px 12px 8px;flex-wrap:wrap}
.stat{
  display:flex;flex-direction:column;align-items:center;
  background:#1c2128;border-radius:6px;padding:5px 10px;min-width:56px;
}
.stat-val{font-size:12px;font-weight:700;color:#e6edf3}
.stat-lbl{font-size:9px;color:#8b949e;text-transform:uppercase;letter-spacing:.3px;margin-top:1px}

/* ── Charts ───────────────────────────────────────────────────── */
.charts-row{display:flex;gap:8px;padding:8px 12px}
.gauge-wrap{display:flex;flex-direction:column;align-items:center;min-width:115px;flex-shrink:0}
.gauge-label{font-size:10px;color:#8b949e;margin-bottom:2px;text-transform:uppercase;letter-spacing:.5px}
.gauge-status{font-size:9px;color:#8b949e;margin-top:2px;text-align:center}
.price-chart-wrap{flex:1;min-height:120px;position:relative}
.macd-wrap{padding:2px 12px 8px}
.macd-label{font-size:10px;color:#8b949e;margin-bottom:4px;text-transform:uppercase;letter-spacing:.5px}
canvas{display:block;width:100%!important}

/* ── News ─────────────────────────────────────────────────────── */
.news-section{padding:4px 12px 12px}
.news-label{font-size:10px;color:#8b949e;margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px}
.news-item{display:flex;align-items:flex-start;gap:5px;margin-bottom:7px;line-height:1.45}
.news-item a{font-size:11px;color:#58a6ff;flex:1;word-break:break-word;min-width:0}
.sent-badge{flex-shrink:0;padding:1px 5px;border-radius:3px;font-size:9px;font-weight:700;text-transform:uppercase}
.sent-positive{background:#1a3824;color:#3fb950}
.sent-negative{background:#3d1a1a;color:#f85149}
.sent-neutral{background:#1c2128;color:#8b949e}
.no-news{font-size:11px;color:#6e7681;font-style:italic}

/* ── Tablet 2-column (601–900px) ─────────────────────────────── */
@media(min-width:601px) and (max-width:900px){
  .cards-grid{grid-template-columns:repeat(2,1fr)}
  .hm-cell{min-width:58px}
}

/* ── Mobile (≤600px) ──────────────────────────────────────────── */
@media(max-width:600px){
  body{font-size:12px}

  /* Sticky header compact */
  .header{padding:10px 12px;gap:8px}
  h1{font-size:15px}
  .gen-time{font-size:10px}
  .header-right{font-size:10px}

  /* Heatmap: smaller tiles, 5-6 per row */
  .heatmap-section{padding:10px 10px 6px}
  .heatmap{gap:3px}
  .hm-cell{min-width:54px;min-height:38px;font-size:10px;border-radius:5px;padding:3px 4px}
  .hm-cell .hm-pct{font-size:8px}

  /* Cards: single column, tighter */
  .cards-section{padding:8px 10px 36px}
  .cards-grid{grid-template-columns:1fr;gap:10px}
  .card{border-radius:8px}
  .card-header{padding:9px 11px 5px}
  .ticker{font-size:17px}
  .company-name{font-size:10px}

  /* Price */
  .price-row{padding:0 11px 4px}
  .price{font-size:21px}
  .pct{font-size:13px}
  .vol-row{padding:0 11px 7px;font-size:10px;gap:5px}
  .divider{margin:0 11px}

  /* Stats */
  .summary-stats{padding:5px 11px 7px;gap:6px}
  .stat{padding:4px 8px;min-width:50px}
  .stat-val{font-size:11px}

  /* Charts row: gauge left, price chart right (keep side-by-side) */
  .charts-row{padding:8px 11px;gap:6px}
  .gauge-wrap{min-width:105px}
  .price-chart-wrap{min-height:130px}

  /* MACD */
  .macd-wrap{padding:2px 11px 7px}

  /* News */
  .news-section{padding:4px 11px 11px}
  .news-item{margin-bottom:8px}
  .news-item a{font-size:11px;line-height:1.5}

  /* Touch: increase tap targets */
  .badge,.badge-status,.ma-badge{padding:3px 7px;font-size:10px}
}

/* ── Small phones (≤375px) ────────────────────────────────────── */
@media(max-width:375px){
  .hm-cell{min-width:48px;font-size:9px}
  .price{font-size:19px}
  .ticker{font-size:15px}
  .gauge-wrap{min-width:95px}
}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <h1>📈 Watchlist</h1>
    <span class="gen-time">Updated: <span id="gen-time"></span></span>
  </div>
  <div class="header-right">
    <div id="stock-count"></div>
    <div>Sorted by |Δ%|</div>
  </div>
</div>

<div class="heatmap-section">
  <h2>Heatmap — Daily Change</h2>
  <div class="heatmap" id="heatmap"></div>
</div>

<div class="cards-section">
  <div class="cards-grid" id="cards"></div>
</div>

<script>
const STOCKS = STOCKS_JSON_PLACEHOLDER;
const GENERATED_AT = 'GENERATED_AT_PLACEHOLDER';

document.getElementById('gen-time').textContent = GENERATED_AT;
document.getElementById('stock-count').textContent = STOCKS.length + ' stocks';

// ── Heatmap ───────────────────────────────────────────────────────────────────
function pctToColor(pct) {
  const abs = Math.min(Math.abs(pct), 5);
  const intensity = abs / 5;
  if (pct >= 0) {
    const g = Math.round(56 + intensity * 100);
    const r = Math.round(20 + intensity * 10);
    return `rgb(${r},${g},${r})`;
  } else {
    const r = Math.round(100 + intensity * 155);
    const g = Math.round(20 + (1 - intensity) * 36);
    return `rgb(${r},${g},${g})`;
  }
}
const hm = document.getElementById('heatmap');
STOCKS.forEach(s => {
  const cell = document.createElement('a');
  cell.className = 'hm-cell';
  cell.href = `#card-${s.ticker}`;
  cell.style.background = pctToColor(s.pct);
  cell.style.color = Math.abs(s.pct) > 2 ? '#fff' : '#e6edf3';
  cell.title = `${s.name}\n${s.pct > 0 ? '+' : ''}${s.pct}%`;
  cell.innerHTML = `<span>${s.ticker}</span><span class="hm-pct">${s.pct > 0 ? '+' : ''}${s.pct}%</span>`;
  hm.appendChild(cell);
});

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtVol(v) {
  if (v >= 1e9) return (v / 1e9).toFixed(1) + 'B';
  if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
  if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K';
  return String(v);
}

function rsiGaugeSVG(rsi) {
  const r = 38, cx = 50, cy = 50;
  const toXY = deg => {
    const rad = deg * Math.PI / 180;
    return [cx + r * Math.cos(rad), cy - r * Math.sin(rad)];
  };
  const [bx, by] = toXY(126);  // RSI=30 boundary
  const [rx2, ry2] = toXY(54); // RSI=70 boundary
  const bxf = bx.toFixed(1), byf = by.toFixed(1);
  const rx2f = rx2.toFixed(1), ry2f = ry2.toFixed(1);

  const needleAngle = (1 - rsi / 100) * 180;
  const needleRad = needleAngle * Math.PI / 180;
  const nx = (cx + 30 * Math.cos(needleRad)).toFixed(1);
  const ny = (cy - 30 * Math.sin(needleRad)).toFixed(1);

  let needleColor = '#6e7681';
  if (rsi >= 70) needleColor = '#f85149';
  else if (rsi <= 30) needleColor = '#388bfd';

  return `<svg viewBox="0 0 100 58" width="110" height="62">
    <path d="M 12,${cy} A ${r},${r} 0 0,1 ${bxf},${byf}" stroke="#388bfd" stroke-width="7" fill="none" stroke-linecap="butt"/>
    <path d="M ${bxf},${byf} A ${r},${r} 0 0,1 ${rx2f},${ry2f}" stroke="#484f58" stroke-width="7" fill="none" stroke-linecap="butt"/>
    <path d="M ${rx2f},${ry2f} A ${r},${r} 0 0,1 88,${cy}" stroke="#f85149" stroke-width="7" fill="none" stroke-linecap="butt"/>
    <line x1="${cx}" y1="${cy}" x2="${nx}" y2="${ny}" stroke="${needleColor}" stroke-width="2.5" stroke-linecap="round"/>
    <circle cx="${cx}" cy="${cy}" r="3.5" fill="#e6edf3"/>
    <text x="${cx}" y="${cy + 9}" text-anchor="middle" fill="#e6edf3" font-size="11" font-weight="bold">${rsi}</text>
    <text x="9" y="${cy + 12}" fill="#388bfd" font-size="7">0</text>
    <text x="82" y="${cy + 12}" fill="#f85149" font-size="7">100</text>
  </svg>`;
}

// ── Cards ─────────────────────────────────────────────────────────────────────
const cards = document.getElementById('cards');
const chartQueue = [];

STOCKS.forEach((s, idx) => {
  const pctSign = s.pct >= 0 ? '+' : '';
  const pctClass = s.pct >= 0 ? 'up' : 'down';

  // GC/DC badges
  let crossBadges = '';
  if (s.gc) crossBadges += '<span class="badge badge-gc">🌟 GC</span>';
  if (s.dc) crossBadges += '<span class="badge badge-dc">💀 DC</span>';

  // MA position
  const maIcon = s.ma_above ? '▲' : '▼';
  const maColor = s.ma_above ? '#3fb950' : '#f85149';
  const maBadge = (s.ma25 && s.ma75)
    ? `<span class="ma-badge" style="color:${maColor}">${maIcon} MA25 ${s.ma_above ? '>' : '<'} MA75</span>`
    : '';

  const statusClass = s.status;
  const statusEmoji = { bullish: '🟢 強気', bearish: '🔴 弱気', neutral: '🟡 中立' }[s.status];
  const statusBadge = `<span class="badge-status badge-${s.status}">${statusEmoji}</span>`;

  const volFire = s.vratio >= 1.5 ? ' <span class="vol-fire">🔥</span>' : '';

  // Sentiment label
  const sentLabel = (sent) => {
    const map = { positive: ['sent-positive', 'POS'], negative: ['sent-negative', 'NEG'], neutral: ['sent-neutral', 'NEU'] };
    const [cls, lbl] = map[sent] || map.neutral;
    return `<span class="sent-badge ${cls}">${lbl}</span>`;
  };

  // News HTML
  let newsHTML = '';
  if (s.news && s.news.length > 0) {
    s.news.forEach(n => {
      newsHTML += `<div class="news-item">
        ${sentLabel(n.sentiment)}
        <a href="${n.link}" target="_blank" rel="noopener">${n.title}</a>
      </div>`;
    });
  } else {
    newsHTML = '<div class="no-news">No news available</div>';
  }

  // MACD info
  const macdDiff = (s.macd - s.signal).toFixed(4);
  const macdColor = s.macd > s.signal ? '#3fb950' : '#f85149';

  const card = document.createElement('div');
  card.className = 'card';
  card.id = `card-${s.ticker}`;
  card.innerHTML = `
    <div class="status-bar ${statusClass}"></div>
    <div class="card-header">
      <div>
        <div class="ticker-row">
          <span class="ticker">${s.ticker}</span>
          ${statusBadge}
          ${crossBadges}
          ${maBadge}
        </div>
        <div class="company-name">${s.name}</div>
      </div>
    </div>
    <div class="price-row">
      <span class="price">$${s.price.toLocaleString('en-US', {minimumFractionDigits:2})}</span>
      <span class="pct ${pctClass}">${pctSign}${s.pct}%</span>
    </div>
    <div class="vol-row">
      <span>Vol: <b>${fmtVol(s.volume)}</b>${volFire}</span>
      <span style="color:#484f58">·</span>
      <span>Avg10: ${fmtVol(s.avgvol)}</span>
      <span style="color:#484f58">·</span>
      <span style="color:${s.vratio>=1.5?'#f0883e':'#8b949e'};font-weight:${s.vratio>=1.5?700:400}">${s.vratio.toFixed(1)}×</span>
    </div>
    <div class="summary-stats">
      ${s.ma25 ? `<div class="stat"><span class="stat-val">$${s.ma25}</span><span class="stat-lbl">MA25</span></div>` : ''}
      ${s.ma75 ? `<div class="stat"><span class="stat-val">$${s.ma75}</span><span class="stat-lbl">MA75</span></div>` : ''}
      <div class="stat"><span class="stat-val" style="color:${macdColor}">${macdDiff}</span><span class="stat-lbl">MACD Diff</span></div>
    </div>
    <div class="divider"></div>
    <div class="charts-row">
      <div class="gauge-wrap">
        <div class="gauge-label">RSI(14)</div>
        ${rsiGaugeSVG(s.rsi)}
        <div class="gauge-status">${s.rsi >= 70 ? '⚠️ Overbought' : s.rsi <= 30 ? '⚠️ Oversold' : 'Normal'}</div>
      </div>
      <div class="price-chart-wrap">
        <canvas id="pc-${idx}" height="120"></canvas>
      </div>
    </div>
    <div class="divider"></div>
    <div class="news-section">
      <div class="news-label">Latest News</div>
      ${newsHTML}
    </div>
  `;
  cards.appendChild(card);
  chartQueue.push({ s, idx });
});

// ── Render Charts (batched via requestAnimationFrame) ─────────────────────────
function renderCharts() {
  chartQueue.forEach(({ s, idx }) => {
    // Price chart
    const pcCanvas = document.getElementById(`pc-${idx}`);
    if (pcCanvas) {
      const labels = s.dates;
      const datasets = [
        {
          label: 'Price',
          data: s.prices,
          borderColor: '#58a6ff',
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.2,
          fill: false,
          order: 3,
        },
        {
          label: 'MA25',
          data: s.ma25d,
          borderColor: '#d4a017',
          borderWidth: 1,
          pointRadius: 0,
          tension: 0.3,
          fill: false,
          borderDash: [],
          order: 2,
        },
        {
          label: 'MA75',
          data: s.ma75d,
          borderColor: '#8b949e',
          borderWidth: 1,
          pointRadius: 0,
          tension: 0.3,
          fill: false,
          borderDash: [4, 2],
          order: 1,
        },
      ];

      // Golden cross markers
      if (s.gm && s.gm.length > 0) {
        datasets.push({
          label: 'GC',
          data: s.gm.map(p => ({ x: p.x, y: p.y })),
          type: 'scatter',
          pointStyle: 'triangle',
          pointRadius: 8,
          borderColor: '#d4a017',
          backgroundColor: '#d4a017',
          order: 0,
        });
      }
      // Dead cross markers
      if (s.dm && s.dm.length > 0) {
        datasets.push({
          label: 'DC',
          data: s.dm.map(p => ({ x: p.x, y: p.y })),
          type: 'scatter',
          pointStyle: 'triangle',
          rotation: 180,
          pointRadius: 8,
          borderColor: '#8b949e',
          backgroundColor: '#8b949e',
          order: 0,
        });
      }

      new Chart(pcCanvas, {
        type: 'line',
        data: { labels, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              mode: 'index',
              intersect: false,
              backgroundColor: '#1c2128',
              borderColor: '#30363d',
              borderWidth: 1,
              titleColor: '#8b949e',
              bodyColor: '#e6edf3',
              callbacks: {
                label: ctx => `${ctx.dataset.label}: $${ctx.parsed.y ?? ''}`,
              },
            },
          },
          scales: {
            x: {
              ticks: { color: '#6e7681', maxTicksLimit: 6, font: { size: 9 } },
              grid: { color: '#21262d' },
            },
            y: {
              position: 'right',
              ticks: { color: '#6e7681', font: { size: 9 } },
              grid: { color: '#21262d' },
            },
          },
        },
        plugins: [{
          id: 'rsiZones',
          beforeDraw(chart) {
            // light RSI band visual — handled via MACD chart instead
          },
        }],
      });
    }

  });
}

requestAnimationFrame(renderCharts);
</script>
</body>
</html>
"""

HTML = HTML.replace('STOCKS_JSON_PLACEHOLDER', stocks_json)
HTML = HTML.replace('GENERATED_AT_PLACEHOLDER', now_str)

with open('dashboard.html', 'w', encoding='utf-8') as f:
    f.write(HTML)

kb = len(HTML) // 1024
print(f"\n✅  Generated dashboard.html  ({kb} KB, {len(stocks)} stocks)")
