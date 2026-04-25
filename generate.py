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

        macd_s, sig_s, _ = calc_macd(close)
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
            'ticker':   sym,
            'name':     name,
            'price':    round(cur, 2),
            'pct':      round(pct, 2),
            'volume':   cvol,
            'avgvol':   int(avgvol),
            'vratio':   round(vratio, 2),
            'rsi':      round(rsi, 1),
            'macd':     round(float(macd_s.iloc[-1]), 4),
            'signal':   round(float(sig_s.iloc[-1]), 4),
            'ma25':     round(ma25_last, 2) if ma25_last else None,
            'ma75':     round(ma75_last, 2) if ma75_last else None,
            'ma_above': ma_above,
            'gc':       recent_gc,
            'dc':       recent_dc,
            'status':   status,
            'news':     news,
            'dates':    dates,
            'prices':   to_list(c60, 2),
            'ma25d':    to_list(ma25.tail(N), 2),
            'ma75d':    to_list(ma75.tail(N), 2),
            'macd_d':   to_list(macd_s.tail(N), 4),   # MACD line series
            'sig_d':    to_list(sig_s.tail(N), 4),    # Signal line series
            'gm':       gm,
            'dm':       dm,
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
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Stock Watchlist</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
/* ── Reset & Base ─────────────────────────────────────────────── */
*{box-sizing:border-box;margin:0;padding:0}
html{
  -webkit-text-size-adjust:100%;text-size-adjust:100%;
  overflow-x:hidden;
}
body{
  background:#0d1117;color:#e6edf3;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  font-size:13px;line-height:1.5;
  overflow-x:hidden;
  -webkit-overflow-scrolling:touch;
}
a{color:#58a6ff;text-decoration:none}
a:hover,a:focus{text-decoration:underline}

/* ── Header ───────────────────────────────────────────────────── */
.header{
  display:flex;align-items:center;justify-content:space-between;
  padding:12px 16px;border-bottom:1px solid #30363d;background:#161b22;
  position:-webkit-sticky;position:sticky;top:0;z-index:100;gap:10px;
}
.header-left{display:flex;flex-direction:column;gap:2px;min-width:0}
h1{font-size:17px;font-weight:700;color:#e6edf3;white-space:nowrap}
.gen-time{font-size:10px;color:#8b949e}
.header-right{text-align:right;flex-shrink:0;font-size:10px;color:#8b949e;line-height:1.6}

/* ── Heatmap ──────────────────────────────────────────────────── */
.heatmap-section{padding:12px 14px 6px}
.heatmap-section h2{
  font-size:10px;color:#8b949e;margin-bottom:7px;font-weight:600;
  text-transform:uppercase;letter-spacing:.6px;
}
.heatmap{display:flex;flex-wrap:wrap;gap:3px}
.hm-cell{
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  min-width:60px;min-height:40px;border-radius:6px;
  font-size:11px;font-weight:700;padding:3px 5px;
  border:1px solid rgba(255,255,255,.08);
  transition:transform .12s;
  -webkit-tap-highlight-color:transparent;
  user-select:none;-webkit-user-select:none;
  text-decoration:none;
}
.hm-cell:hover,.hm-cell:active{transform:scale(1.1);z-index:2}
.hm-cell .hm-pct{font-size:9px;font-weight:400;margin-top:1px}

/* ── Cards Section ────────────────────────────────────────────── */
.cards-section{padding:10px 14px 40px}
.cards-grid{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(min(100%,360px),1fr));
  gap:12px;
}

/* ── Card ─────────────────────────────────────────────────────── */
.card{
  background:#161b22;border:1px solid #30363d;border-radius:10px;
  overflow:hidden;
  /* sticky header height: ~50px desktop, ~46px mobile */
  scroll-margin-top:54px;
}
.card:hover{border-color:#58a6ff44}
.status-bar{height:4px;width:100%}
.status-bar.bullish{background:linear-gradient(90deg,#238636,#2ea043)}
.status-bar.bearish{background:linear-gradient(90deg,#da3633,#f85149)}
.status-bar.neutral{background:linear-gradient(90deg,#9e6a03,#d29922)}

/* Card Header */
.card-header{padding:10px 12px 5px}
.ticker-row{display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.ticker{font-size:18px;font-weight:800;color:#e6edf3}
.company-name{font-size:10px;color:#8b949e;margin-top:2px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}

/* Badges */
.badge{display:inline-flex;align-items:center;gap:3px;
  padding:2px 6px;border-radius:20px;font-size:10px;font-weight:700}
.badge-gc{background:#2d2500;color:#d4a017;border:1px solid #d4a017}
.badge-dc{background:#1e1e1e;color:#8b949e;border:1px solid #6e7681}
.badge-status{padding:2px 6px;border-radius:20px;font-size:10px;font-weight:600}
.badge-bullish{background:#1a3824;color:#3fb950}
.badge-bearish{background:#3d1a1a;color:#f85149}
.badge-neutral{background:#2a2000;color:#d29922}
.ma-badge{font-size:10px;padding:2px 6px;border-radius:4px;
  background:#1c2128;color:#8b949e;border:1px solid #30363d}

/* Price / Volume */
.price-row{display:flex;align-items:baseline;gap:10px;padding:0 12px 4px}
.price{font-size:22px;font-weight:700;color:#e6edf3}
.pct{font-size:14px;font-weight:700}
.pct.up{color:#3fb950}
.pct.down{color:#f85149}
.vol-row{
  display:flex;align-items:center;flex-wrap:wrap;
  gap:5px;padding:0 12px 7px;font-size:11px;color:#8b949e;
}
.vol-fire{font-size:12px}

/* Divider */
.divider{height:1px;background:#21262d;margin:0 12px}

/* Stats */
.summary-stats{display:flex;gap:7px;padding:5px 12px 7px;flex-wrap:wrap}
.stat{
  display:flex;flex-direction:column;align-items:center;
  background:#1c2128;border-radius:6px;padding:4px 10px;min-width:54px;
}
.stat-val{font-size:12px;font-weight:700;color:#e6edf3}
.stat-lbl{font-size:9px;color:#8b949e;text-transform:uppercase;
  letter-spacing:.3px;margin-top:1px}

/* Charts */
.charts-row{display:flex;gap:8px;padding:8px 12px 6px}
.gauge-wrap{display:flex;flex-direction:column;align-items:center;
  min-width:110px;flex-shrink:0}
.gauge-label{font-size:10px;color:#8b949e;margin-bottom:2px;
  text-transform:uppercase;letter-spacing:.5px}
.gauge-status{font-size:9px;color:#8b949e;margin-top:2px;text-align:center}
.price-chart-wrap{flex:1;min-height:120px;position:relative;min-width:0}

/* MACD line chart */
.macd-wrap{padding:2px 12px 8px}
.macd-label{font-size:10px;color:#8b949e;margin-bottom:3px;
  text-transform:uppercase;letter-spacing:.5px}
.macd-chart-wrap{height:60px;position:relative}

/* canvas: block only, let Chart.js handle dimensions */
canvas{display:block}

/* News */
.news-section{padding:4px 12px 12px}
.news-label{font-size:10px;color:#8b949e;margin-bottom:5px;
  text-transform:uppercase;letter-spacing:.5px}
.news-item{display:flex;align-items:flex-start;gap:5px;
  margin-bottom:6px;line-height:1.45}
.news-item a{font-size:11px;color:#58a6ff;flex:1;
  word-break:break-word;min-width:0;overflow-wrap:anywhere}
.sent-badge{flex-shrink:0;padding:1px 5px;border-radius:3px;
  font-size:9px;font-weight:700;text-transform:uppercase}
.sent-positive{background:#1a3824;color:#3fb950}
.sent-negative{background:#3d1a1a;color:#f85149}
.sent-neutral{background:#1c2128;color:#8b949e}
.no-news{font-size:11px;color:#6e7681;font-style:italic}

/* ── Tablet 2-col (601–900px) ─────────────────────────────────── */
@media(min-width:601px) and (max-width:900px){
  .cards-grid{grid-template-columns:repeat(2,1fr)}
}

/* ── Mobile ≤600px ────────────────────────────────────────────── */
@media(max-width:600px){
  body{font-size:12px}
  .header{padding:9px 12px}
  h1{font-size:15px}
  .heatmap-section{padding:9px 10px 5px}
  .heatmap{gap:3px}
  .hm-cell{min-width:52px;min-height:37px;font-size:10px;
    padding:3px 4px;border-radius:5px}
  .hm-cell .hm-pct{font-size:8px}
  .cards-section{padding:8px 10px 36px}
  .cards-grid{grid-template-columns:1fr;gap:10px}
  .card{border-radius:8px;scroll-margin-top:50px}
  .card-header{padding:9px 10px 4px}
  .ticker{font-size:16px}
  .price-row{padding:0 10px 4px}
  .price{font-size:20px}
  .pct{font-size:13px}
  .vol-row{padding:0 10px 6px;font-size:10px}
  .divider{margin:0 10px}
  .summary-stats{padding:5px 10px 6px;gap:6px}
  .stat{padding:4px 8px;min-width:48px}
  .stat-val{font-size:11px}
  .charts-row{padding:7px 10px 5px;gap:6px}
  .gauge-wrap{min-width:100px}
  .price-chart-wrap{min-height:115px}
  .macd-wrap{padding:2px 10px 7px}
  .macd-chart-wrap{height:54px}
  .news-section{padding:4px 10px 10px}
  .news-item a{font-size:11px}
  .badge,.badge-status,.ma-badge{padding:3px 7px}
}

/* ── Small phones ≤375px ──────────────────────────────────────── */
@media(max-width:375px){
  .hm-cell{min-width:46px;font-size:9px}
  .ticker{font-size:15px}
  .price{font-size:18px}
  .gauge-wrap{min-width:90px}
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
  const t = abs / 5;
  if (pct >= 0) {
    return `rgb(${Math.round(20+t*10)},${Math.round(56+t*100)},${Math.round(20+t*10)})`;
  }
  return `rgb(${Math.round(100+t*155)},${Math.round(20+(1-t)*36)},${Math.round(20+(1-t)*36)})`;
}

const hm = document.getElementById('heatmap');
STOCKS.forEach(s => {
  const a = document.createElement('a');
  a.className = 'hm-cell';
  a.href = `#card-${s.ticker}`;
  a.style.background = pctToColor(s.pct);
  a.style.color = Math.abs(s.pct) > 2 ? '#fff' : '#e6edf3';
  a.title = `${s.name}  ${s.pct > 0 ? '+' : ''}${s.pct}%`;
  a.innerHTML = `<span>${s.ticker}</span><span class="hm-pct">${s.pct >= 0 ? '+' : ''}${s.pct}%</span>`;
  hm.appendChild(a);
});

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtVol(v) {
  if (v >= 1e9) return (v / 1e9).toFixed(1) + 'B';
  if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
  if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K';
  return String(v);
}

function rsiGaugeSVG(rsi) {
  const R = 38, cx = 50, cy = 50;
  const pt = deg => {
    const r = deg * Math.PI / 180;
    return [cx + R * Math.cos(r), cy - R * Math.sin(r)];
  };
  const [bx, by]   = pt(126); // RSI=30 boundary
  const [rx2, ry2] = pt(54);  // RSI=70 boundary
  const [bxf, byf]   = [bx.toFixed(1), by.toFixed(1)];
  const [rx2f, ry2f] = [rx2.toFixed(1), ry2.toFixed(1)];
  const nRad = (1 - rsi / 100) * Math.PI;
  const nx = (cx + 30 * Math.cos(nRad)).toFixed(1);
  const ny = (cy - 30 * Math.sin(nRad)).toFixed(1);
  const nc = rsi >= 70 ? '#f85149' : rsi <= 30 ? '#388bfd' : '#6e7681';
  return `<svg viewBox="0 0 100 58" width="108" height="61" aria-label="RSI ${rsi}">
    <path d="M 12,${cy} A ${R},${R} 0 0,1 ${bxf},${byf}" stroke="#388bfd" stroke-width="7" fill="none"/>
    <path d="M ${bxf},${byf} A ${R},${R} 0 0,1 ${rx2f},${ry2f}" stroke="#484f58" stroke-width="7" fill="none"/>
    <path d="M ${rx2f},${ry2f} A ${R},${R} 0 0,1 88,${cy}" stroke="#f85149" stroke-width="7" fill="none"/>
    <line x1="${cx}" y1="${cy}" x2="${nx}" y2="${ny}" stroke="${nc}" stroke-width="2.5" stroke-linecap="round"/>
    <circle cx="${cx}" cy="${cy}" r="3.5" fill="#e6edf3"/>
    <text x="${cx}" y="${cy+9}" text-anchor="middle" fill="#e6edf3" font-size="11" font-weight="bold">${rsi}</text>
    <text x="9" y="${cy+12}" fill="#388bfd" font-size="7">0</text>
    <text x="82" y="${cy+12}" fill="#f85149" font-size="7">100</text>
  </svg>`;
}

// ── Chart defaults (shared config) ───────────────────────────────────────────
const GRID_COLOR  = '#21262d';
const TICK_COLOR  = '#6e7681';
const TIP_BG      = '#1c2128';
const TIP_BORDER  = '#30363d';

function axisX(extra) {
  return Object.assign({
    ticks: { color: TICK_COLOR, maxTicksLimit: 6, font: { size: 9 } },
    grid:  { color: GRID_COLOR },
  }, extra);
}
function axisY(extra) {
  return Object.assign({
    position: 'right',
    ticks: { color: TICK_COLOR, font: { size: 9 } },
    grid:  { color: GRID_COLOR },
  }, extra);
}
function tooltipBase() {
  return {
    backgroundColor: TIP_BG, borderColor: TIP_BORDER, borderWidth: 1,
    titleColor: TICK_COLOR, bodyColor: '#e6edf3',
  };
}

// ── Build card DOM & queue charts ─────────────────────────────────────────────
const cardsEl = document.getElementById('cards');

STOCKS.forEach((s, idx) => {
  const pctSign  = s.pct >= 0 ? '+' : '';
  const pctClass = s.pct >= 0 ? 'up' : 'down';

  let crossBadges = '';
  if (s.gc) crossBadges += '<span class="badge badge-gc">🌟 GC</span>';
  if (s.dc) crossBadges += '<span class="badge badge-dc">💀 DC</span>';

  const maColor = s.ma_above ? '#3fb950' : '#f85149';
  const maBadge = (s.ma25 && s.ma75)
    ? `<span class="ma-badge" style="color:${maColor}">${s.ma_above ? '▲' : '▼'} MA25 ${s.ma_above ? '>' : '<'} MA75</span>`
    : '';

  const statusLabels = { bullish: '🟢 強気', bearish: '🔴 弱気', neutral: '🟡 中立' };
  const statusBadge  = `<span class="badge-status badge-${s.status}">${statusLabels[s.status]}</span>`;

  const volFire  = s.vratio >= 1.5 ? ' <span class="vol-fire">🔥</span>' : '';
  const volColor = s.vratio >= 1.5 ? '#f0883e' : '#8b949e';
  const volBold  = s.vratio >= 1.5 ? 700 : 400;

  const sentLabel = sent => {
    const m = { positive: ['sent-positive','POS'], negative: ['sent-negative','NEG'], neutral: ['sent-neutral','NEU'] };
    const [cls, lbl] = m[sent] || m.neutral;
    return `<span class="sent-badge ${cls}">${lbl}</span>`;
  };

  let newsHTML = s.news && s.news.length
    ? s.news.map(n => `<div class="news-item">${sentLabel(n.sentiment)}<a href="${n.link}" target="_blank" rel="noopener noreferrer">${n.title}</a></div>`).join('')
    : '<div class="no-news">No news available</div>';

  const macdDiff  = (s.macd - s.signal).toFixed(4);
  const macdColor = s.macd > s.signal ? '#3fb950' : '#f85149';

  const card = document.createElement('div');
  card.className = 'card';
  card.id = `card-${s.ticker}`;
  card.innerHTML = `
    <div class="status-bar ${s.status}"></div>
    <div class="card-header">
      <div class="ticker-row">
        <span class="ticker">${s.ticker}</span>
        ${statusBadge}${crossBadges}${maBadge}
      </div>
      <div class="company-name">${s.name}</div>
    </div>
    <div class="price-row">
      <span class="price">$${s.price.toLocaleString('en-US',{minimumFractionDigits:2})}</span>
      <span class="pct ${pctClass}">${pctSign}${s.pct}%</span>
    </div>
    <div class="vol-row">
      <span>Vol: <b>${fmtVol(s.volume)}</b>${volFire}</span>
      <span style="color:#484f58">·</span>
      <span>Avg10: ${fmtVol(s.avgvol)}</span>
      <span style="color:#484f58">·</span>
      <span style="color:${volColor};font-weight:${volBold}">${s.vratio.toFixed(1)}×</span>
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
        <canvas id="pc-${idx}"></canvas>
      </div>
    </div>
    <div class="macd-wrap">
      <div class="macd-label">MACD (12/26/9) — Line &amp; Signal</div>
      <div class="macd-chart-wrap">
        <canvas id="mc-${idx}"></canvas>
      </div>
    </div>
    <div class="divider"></div>
    <div class="news-section">
      <div class="news-label">Latest News</div>
      ${newsHTML}
    </div>`;
  cardsEl.appendChild(card);
});

// ── Lazy chart rendering via IntersectionObserver ─────────────────────────────
function renderPriceChart(s, idx) {
  const cv = document.getElementById(`pc-${idx}`);
  if (!cv || cv._rendered) return;
  cv._rendered = true;

  const datasets = [
    {
      label: 'Price', data: s.prices,
      borderColor: '#58a6ff', borderWidth: 1.5,
      pointRadius: 0, tension: 0.2, fill: false, order: 3,
    },
    {
      label: 'MA25', data: s.ma25d,
      borderColor: '#d4a017', borderWidth: 1.2,
      pointRadius: 0, tension: 0.3, fill: false, order: 2,
    },
    {
      label: 'MA75', data: s.ma75d,
      borderColor: '#8b949e', borderWidth: 1,
      borderDash: [4, 2],
      pointRadius: 0, tension: 0.3, fill: false, order: 1,
    },
  ];

  if (s.gm && s.gm.length) {
    datasets.push({
      label: 'GC', type: 'scatter',
      data: s.gm.map(p => ({ x: p.x, y: p.y })),
      pointStyle: 'triangle', pointRadius: 8,
      borderColor: '#d4a017', backgroundColor: '#d4a017', order: 0,
    });
  }
  if (s.dm && s.dm.length) {
    datasets.push({
      label: 'DC', type: 'scatter',
      data: s.dm.map(p => ({ x: p.x, y: p.y })),
      pointStyle: 'triangle', pointRotation: 180, pointRadius: 8,
      borderColor: '#8b949e', backgroundColor: '#8b949e', order: 0,
    });
  }

  new Chart(cv, {
    type: 'line',
    data: { labels: s.dates, datasets },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: {
        legend: { display: false },
        tooltip: Object.assign(tooltipBase(), {
          mode: 'index', intersect: false,
          callbacks: { label: ctx => `${ctx.dataset.label}: $${ctx.parsed.y ?? ''}` },
        }),
      },
      scales: { x: axisX(), y: axisY() },
    },
  });
}

function renderMacdChart(s, idx) {
  const cv = document.getElementById(`mc-${idx}`);
  if (!cv || cv._rendered) return;
  cv._rendered = true;

  new Chart(cv, {
    type: 'line',
    data: {
      labels: s.dates,
      datasets: [
        {
          label: 'MACD', data: s.macd_d,
          borderColor: '#58a6ff', borderWidth: 1.5,
          pointRadius: 0, tension: 0.2, fill: false, order: 1,
        },
        {
          label: 'Signal', data: s.sig_d,
          borderColor: '#f0883e', borderWidth: 1.2,
          borderDash: [3, 2],
          pointRadius: 0, tension: 0.2, fill: false, order: 2,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: {
        legend: { display: false },
        tooltip: Object.assign(tooltipBase(), {
          mode: 'index', intersect: false,
        }),
      },
      scales: {
        x: axisX({ ticks: { display: false }, grid: { color: GRID_COLOR } }),
        y: axisY({ ticks: { maxTicksLimit: 3, font: { size: 8 } } }),
      },
    },
  });
}

// IntersectionObserver: render charts only when card enters viewport
const io = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (!entry.isIntersecting) return;
    const idx = parseInt(entry.target.dataset.idx, 10);
    const s = STOCKS[idx];
    renderPriceChart(s, idx);
    renderMacdChart(s, idx);
    io.unobserve(entry.target);
  });
}, { rootMargin: '300px 0px' });

document.querySelectorAll('.card').forEach((card, idx) => {
  card.dataset.idx = idx;
  io.observe(card);
});
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
