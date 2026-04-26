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
            'macd_d':   to_list(macd_s.tail(N), 4),
            'sig_d':    to_list(sig_s.tail(N), 4),
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
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Stock Watchlist</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
/* ── Reset & Base ─────────────────────────────────────────────── */
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%;overflow-x:hidden}
body{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:13px;line-height:1.5;overflow-x:hidden;-webkit-overflow-scrolling:touch}
a{color:#58a6ff;text-decoration:none}
a:hover,a:focus{text-decoration:underline}
button{cursor:pointer;font-family:inherit;-webkit-tap-highlight-color:transparent}

/* ── Header ───────────────────────────────────────────────────── */
.header{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid #30363d;background:#161b22;position:-webkit-sticky;position:sticky;top:0;z-index:200;gap:8px}
.header-left{display:flex;flex-direction:column;gap:2px;min-width:0}
h1{font-size:17px;font-weight:700;color:#e6edf3;white-space:nowrap}
.gen-time{font-size:10px;color:#8b949e}
.header-right{display:flex;align-items:center;gap:6px;flex-shrink:0}
.hdr-btn{display:inline-flex;align-items:center;gap:3px;padding:5px 9px;border-radius:6px;font-size:11px;font-weight:600;background:#1c2128;color:#e6edf3;border:1px solid #30363d}
.hdr-btn:active{background:#2d333b}

/* ── Market Bar ───────────────────────────────────────────────── */
.market-bar{display:flex;align-items:center;gap:0;overflow-x:auto;background:#0d1117;border-bottom:1px solid #21262d;padding:0 4px;scrollbar-width:none;-ms-overflow-style:none}
.market-bar::-webkit-scrollbar{display:none}
.mkt-item{display:flex;flex-direction:column;align-items:center;padding:6px 10px;border-right:1px solid #21262d;flex-shrink:0;min-width:72px}
.mkt-label{font-size:9px;color:#8b949e;text-transform:uppercase;letter-spacing:.4px;margin-bottom:2px}
.mkt-price{font-size:12px;font-weight:700;color:#e6edf3}
.mkt-pct{font-size:10px;font-weight:600}
.mkt-pct.up{color:#3fb950}
.mkt-pct.down{color:#f85149}
.mkt-loading{font-size:10px;color:#484f58;padding:8px 14px}

/* ── Heatmap ──────────────────────────────────────────────────── */
.heatmap-section{padding:10px 14px 6px}
.heatmap-section h2{font-size:10px;color:#8b949e;margin-bottom:7px;font-weight:600;text-transform:uppercase;letter-spacing:.6px}
.heatmap{display:flex;flex-wrap:wrap;gap:3px}
.hm-cell{display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:60px;min-height:40px;border-radius:6px;font-size:11px;font-weight:700;padding:3px 5px;border:1px solid rgba(255,255,255,.08);transition:transform .12s;-webkit-tap-highlight-color:transparent;user-select:none;-webkit-user-select:none;text-decoration:none}
.hm-cell:hover,.hm-cell:active{transform:scale(1.1);z-index:2}
.hm-cell .hm-pct{font-size:9px;font-weight:400;margin-top:1px}

/* ── Sort Bar ─────────────────────────────────────────────────── */
.sort-bar{display:flex;align-items:center;gap:6px;padding:8px 14px 4px;flex-wrap:wrap}
.sort-label{font-size:10px;color:#8b949e}
.sort-btn{padding:4px 10px;border-radius:20px;font-size:11px;font-weight:600;border:1px solid #30363d;background:#1c2128;color:#8b949e;transition:all .12s}
.sort-btn.active{background:#1f6feb22;border-color:#1f6feb;color:#58a6ff}
.sort-btn:active{opacity:.7}
.add-btn-inline{margin-left:auto;display:inline-flex;align-items:center;gap:4px;padding:4px 10px;border-radius:20px;font-size:11px;font-weight:600;border:1px solid #3fb95066;background:#1a382466;color:#3fb950}
.add-btn-inline:active{opacity:.7}

/* ── Cards ────────────────────────────────────────────────────── */
.cards-section{padding:6px 14px 40px}
.cards-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,360px),1fr));gap:12px}
.card{background:#161b22;border:1px solid #30363d;border-radius:10px;overflow:hidden;scroll-margin-top:50px;position:relative}
.card:hover{border-color:#58a6ff44}
.card.hidden-card{display:none}

/* Remove button */
.remove-btn{position:absolute;top:6px;right:8px;width:22px;height:22px;border-radius:50%;background:transparent;border:none;color:#484f58;font-size:14px;line-height:1;display:flex;align-items:center;justify-content:center;z-index:10;transition:all .12s;padding:0}
.remove-btn:hover,.remove-btn:active{background:#3d1a1a;color:#f85149}

.status-bar{height:4px;width:100%}
.status-bar.bullish{background:linear-gradient(90deg,#238636,#2ea043)}
.status-bar.bearish{background:linear-gradient(90deg,#da3633,#f85149)}
.status-bar.neutral{background:linear-gradient(90deg,#9e6a03,#d29922)}
.card-header{padding:10px 30px 5px 12px}
.ticker-row{display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.ticker{font-size:18px;font-weight:800;color:#e6edf3}
.company-name{font-size:10px;color:#8b949e;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}

/* Badges */
.badge{display:inline-flex;align-items:center;gap:3px;padding:2px 6px;border-radius:20px;font-size:10px;font-weight:700}
.badge-gc{background:#2d2500;color:#d4a017;border:1px solid #d4a017}
.badge-dc{background:#1e1e1e;color:#8b949e;border:1px solid #6e7681}
.badge-status{padding:2px 6px;border-radius:20px;font-size:10px;font-weight:600}
.badge-bullish{background:#1a3824;color:#3fb950}
.badge-bearish{background:#3d1a1a;color:#f85149}
.badge-neutral{background:#2a2000;color:#d29922}
.ma-badge{font-size:10px;padding:2px 6px;border-radius:4px;background:#1c2128;color:#8b949e;border:1px solid #30363d}
.extra-badge{font-size:9px;padding:1px 5px;border-radius:3px;background:#2a2000;color:#d29922;border:1px solid #9e6a03}

/* Price / Volume */
.price-row{display:flex;align-items:baseline;gap:10px;padding:0 12px 4px}
.price{font-size:22px;font-weight:700;color:#e6edf3}
.pct{font-size:14px;font-weight:700}
.pct.up{color:#3fb950}
.pct.down{color:#f85149}
.vol-row{display:flex;align-items:center;flex-wrap:wrap;gap:5px;padding:0 12px 7px;font-size:11px;color:#8b949e}
.vol-fire{font-size:12px}
.divider{height:1px;background:#21262d;margin:0 12px}

/* Stats */
.summary-stats{display:flex;gap:7px;padding:5px 12px 7px;flex-wrap:wrap}
.stat{display:flex;flex-direction:column;align-items:center;background:#1c2128;border-radius:6px;padding:4px 10px;min-width:54px}
.stat-val{font-size:12px;font-weight:700;color:#e6edf3}
.stat-lbl{font-size:9px;color:#8b949e;text-transform:uppercase;letter-spacing:.3px;margin-top:1px}

/* Charts */
.charts-row{display:flex;gap:8px;padding:8px 12px 6px}
.gauge-wrap{display:flex;flex-direction:column;align-items:center;min-width:110px;flex-shrink:0}
.gauge-label{font-size:10px;color:#8b949e;margin-bottom:2px;text-transform:uppercase;letter-spacing:.5px}
.gauge-status{font-size:9px;color:#8b949e;margin-top:2px;text-align:center}
.price-chart-wrap{flex:1;min-height:120px;position:relative;min-width:0}
.macd-wrap{padding:2px 12px 8px}
.macd-label{font-size:10px;color:#8b949e;margin-bottom:3px;text-transform:uppercase;letter-spacing:.5px}
.macd-chart-wrap{height:60px;position:relative}
canvas{display:block}

/* News */
.news-section{padding:4px 12px 12px}
.news-label{font-size:10px;color:#8b949e;margin-bottom:5px;text-transform:uppercase;letter-spacing:.5px}
.news-item{display:flex;align-items:flex-start;gap:5px;margin-bottom:6px;line-height:1.45}
.news-item a{font-size:11px;color:#58a6ff;flex:1;word-break:break-word;min-width:0;overflow-wrap:anywhere}
.sent-badge{flex-shrink:0;padding:1px 5px;border-radius:3px;font-size:9px;font-weight:700;text-transform:uppercase}
.sent-positive{background:#1a3824;color:#3fb950}
.sent-negative{background:#3d1a1a;color:#f85149}
.sent-neutral{background:#1c2128;color:#8b949e}
.no-news{font-size:11px;color:#6e7681;font-style:italic}

/* ── Add Modal ────────────────────────────────────────────────── */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:500;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.modal-box{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px;width:min(320px,90vw);display:flex;flex-direction:column;gap:12px}
.modal-title{font-size:14px;font-weight:700;color:#e6edf3}
.modal-input{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:9px 12px;color:#e6edf3;font-size:14px;font-family:inherit;width:100%;outline:none}
.modal-input:focus{border-color:#58a6ff}
.modal-input::placeholder{color:#484f58}
.modal-btns{display:flex;gap:8px}
.modal-ok{flex:1;padding:8px;border-radius:6px;border:none;background:#1f6feb;color:#fff;font-size:13px;font-weight:600}
.modal-ok:active{opacity:.8}
.modal-cancel{padding:8px 14px;border-radius:6px;border:1px solid #30363d;background:transparent;color:#8b949e;font-size:13px}
.modal-cancel:active{opacity:.7}
.modal-err{font-size:11px;color:#f85149;display:none}
.modal-err.show{display:block}
.spinner{display:none;text-align:center;color:#8b949e;font-size:12px}
.spinner.show{display:block}

/* ── Tablet / Mobile ──────────────────────────────────────────── */
@media(min-width:601px) and (max-width:900px){
  .cards-grid{grid-template-columns:repeat(2,1fr)}
}
@media(max-width:600px){
  body{font-size:12px}
  .header{padding:8px 12px}
  h1{font-size:15px}
  .mkt-item{min-width:64px;padding:5px 8px}
  .mkt-price{font-size:11px}
  .heatmap-section{padding:8px 10px 5px}
  .hm-cell{min-width:52px;min-height:37px;font-size:10px;padding:3px 4px;border-radius:5px}
  .hm-cell .hm-pct{font-size:8px}
  .sort-bar{padding:6px 10px 3px;gap:5px}
  .cards-section{padding:5px 10px 36px}
  .cards-grid{grid-template-columns:1fr;gap:10px}
  .card{border-radius:8px}
  .price{font-size:20px}
  .ticker{font-size:16px}
  .charts-row{padding:7px 10px 5px}
  .gauge-wrap{min-width:100px}
  .price-chart-wrap{min-height:115px}
  .macd-chart-wrap{height:54px}
  .divider{margin:0 10px}
  .summary-stats,.vol-row,.price-row{padding-left:10px;padding-right:10px}
  .news-section{padding:4px 10px 10px}
  .macd-wrap{padding:2px 10px 7px}
}
@media(max-width:375px){
  .hm-cell{min-width:46px;font-size:9px}
  .ticker{font-size:15px}
  .price{font-size:18px}
  .gauge-wrap{min-width:90px}
}
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <div class="header-left">
    <h1>📈 Watchlist</h1>
    <span class="gen-time">Updated: <span id="gen-time"></span></span>
  </div>
  <div class="header-right">
    <span id="stock-count" style="font-size:10px;color:#8b949e"></span>
    <button class="hdr-btn" onclick="savePage()">💾 保存</button>
  </div>
</div>

<!-- Market Bar -->
<div class="market-bar" id="market-bar">
  <div class="mkt-loading">マーケット情報を取得中...</div>
</div>

<!-- Heatmap -->
<div class="heatmap-section">
  <h2>Heatmap — Daily Change</h2>
  <div class="heatmap" id="heatmap"></div>
</div>

<!-- Sort Bar + Cards -->
<div class="sort-bar">
  <span class="sort-label">並び替え:</span>
  <button class="sort-btn active" id="sort-abs" onclick="setSort('abs')">|Δ%| 絶対値</button>
  <button class="sort-btn" id="sort-up"  onclick="setSort('up')">▲ 値上がり</button>
  <button class="sort-btn" id="sort-down" onclick="setSort('down')">▼ 値下がり</button>
  <button class="add-btn-inline" onclick="openAddModal()">＋ 銘柄追加</button>
</div>
<div class="cards-section">
  <div class="cards-grid" id="cards"></div>
</div>

<!-- Add Ticker Modal -->
<div class="modal-overlay" id="add-modal" onclick="if(event.target===this)closeAddModal()">
  <div class="modal-box">
    <div class="modal-title">📌 銘柄を追加</div>
    <input class="modal-input" id="add-input" placeholder="ティッカー例: GOOG, TSLA" maxlength="10"
      onkeydown="if(event.key==='Enter')doAddTicker()">
    <div class="spinner" id="add-spinner">⏳ データ取得中...</div>
    <div class="modal-err" id="add-err"></div>
    <div class="modal-btns">
      <button class="modal-ok" onclick="doAddTicker()">追加</button>
      <button class="modal-cancel" onclick="closeAddModal()">キャンセル</button>
    </div>
    <div style="font-size:10px;color:#484f58">
      ※ブラウザ上での追加は簡易表示です。<br>永続化するには watchlist.txt に追記して再生成してください。
    </div>
  </div>
</div>

<script>
const STOCKS = STOCKS_JSON_PLACEHOLDER;
const GENERATED_AT = 'GENERATED_AT_PLACEHOLDER';

document.getElementById('gen-time').textContent = GENERATED_AT;

// ── Persistence ───────────────────────────────────────────────────────────────
const LS = {
  get: (k, def) => { try { return JSON.parse(localStorage.getItem(k) ?? 'null') ?? def; } catch { return def; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
let hiddenSet  = new Set(LS.get('wl_hidden', []));
let extraStocks = LS.get('wl_extra', []);
let sortMode   = LS.get('wl_sort', 'abs');

// ── Save Page ─────────────────────────────────────────────────────────────────
function savePage() {
  const html = '<!DOCTYPE html>\n' + document.documentElement.outerHTML;
  const a = Object.assign(document.createElement('a'), {
    href: URL.createObjectURL(new Blob([html], {type:'text/html;charset=utf-8'})),
    download: 'dashboard.html',
  });
  a.click(); URL.revokeObjectURL(a.href);
}

// ── Market Bar ────────────────────────────────────────────────────────────────
const MARKET_ITEMS = [
  { sym: 'USDJPY=X', label: '$/¥',   fmt: v => v.toFixed(2) },
  { sym: '^IXIC',    label: 'NASDAQ', fmt: v => v.toLocaleString('en-US',{maximumFractionDigits:0}) },
  { sym: 'NQ=F',     label: 'NQ先物', fmt: v => v.toLocaleString('en-US',{maximumFractionDigits:0}) },
  { sym: '^DJI',     label: 'DOW',    fmt: v => v.toLocaleString('en-US',{maximumFractionDigits:0}) },
  { sym: '^N225',    label: '日経',   fmt: v => v.toLocaleString('en-US',{maximumFractionDigits:0}) },
  { sym: '^VIX',     label: 'VIX',    fmt: v => v.toFixed(2) },
];

async function fetchMarketBar() {
  const bar = document.getElementById('market-bar');
  try {
    const syms = MARKET_ITEMS.map(m => encodeURIComponent(m.sym)).join(',');
    const res  = await fetch(
      `https://query1.finance.yahoo.com/v7/finance/quote?symbols=${syms}`,
      { headers: { Accept: 'application/json' } }
    );
    const data = await res.json();
    const results = data.quoteResponse?.result ?? [];
    bar.innerHTML = '';
    MARKET_ITEMS.forEach(item => {
      const q = results.find(r => r.symbol === item.sym);
      if (!q) return;
      const price = q.regularMarketPrice;
      const pct   = q.regularMarketChangePercent ?? 0;
      const sign  = pct >= 0 ? '+' : '';
      const cls   = pct >= 0 ? 'up' : 'down';
      const el = document.createElement('div');
      el.className = 'mkt-item';
      el.innerHTML = `<span class="mkt-label">${item.label}</span>
        <span class="mkt-price">${item.fmt(price)}</span>
        <span class="mkt-pct ${cls}">${sign}${pct.toFixed(2)}%</span>`;
      bar.appendChild(el);
    });
  } catch {
    bar.innerHTML = '<div class="mkt-loading">マーケット情報を取得できませんでした</div>';
  }
}
fetchMarketBar();
setInterval(fetchMarketBar, 60000);

// ── Heatmap & pct color ───────────────────────────────────────────────────────
function pctToColor(pct) {
  const t = Math.min(Math.abs(pct), 5) / 5;
  return pct >= 0
    ? `rgb(${Math.round(20+t*10)},${Math.round(56+t*100)},${Math.round(20+t*10)})`
    : `rgb(${Math.round(100+t*155)},${Math.round(20+(1-t)*36)},${Math.round(20+(1-t)*36)})`;
}

function renderHeatmap(stocks) {
  const hm = document.getElementById('heatmap');
  hm.innerHTML = '';
  stocks.forEach(s => {
    const a = document.createElement('a');
    a.className = 'hm-cell';
    a.href = `#card-${s.ticker}`;
    a.dataset.ticker = s.ticker;
    a.dataset.pct = s.pct;
    a.style.background = pctToColor(s.pct);
    a.style.color = Math.abs(s.pct) > 2 ? '#fff' : '#e6edf3';
    a.title = `${s.name}  ${s.pct >= 0 ? '+' : ''}${s.pct}%`;
    a.innerHTML = `<span>${s.ticker}</span><span class="hm-pct">${s.pct >= 0 ? '+' : ''}${s.pct}%</span>`;
    hm.appendChild(a);
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtVol(v) {
  if (v >= 1e9) return (v/1e9).toFixed(1)+'B';
  if (v >= 1e6) return (v/1e6).toFixed(1)+'M';
  if (v >= 1e3) return (v/1e3).toFixed(0)+'K';
  return String(v);
}

function rsiGaugeSVG(rsi) {
  const R=38,cx=50,cy=50;
  const pt = d => [cx+R*Math.cos(d*Math.PI/180), cy-R*Math.sin(d*Math.PI/180)];
  const [bx,by]=pt(126), [rx2,ry2]=pt(54);
  const nRad=(1-rsi/100)*Math.PI;
  const nx=(cx+30*Math.cos(nRad)).toFixed(1), ny=(cy-30*Math.sin(nRad)).toFixed(1);
  const nc=rsi>=70?'#f85149':rsi<=30?'#388bfd':'#6e7681';
  return `<svg viewBox="0 0 100 58" width="108" height="61">
    <path d="M 12,${cy} A ${R},${R} 0 0,1 ${bx.toFixed(1)},${by.toFixed(1)}" stroke="#388bfd" stroke-width="7" fill="none"/>
    <path d="M ${bx.toFixed(1)},${by.toFixed(1)} A ${R},${R} 0 0,1 ${rx2.toFixed(1)},${ry2.toFixed(1)}" stroke="#484f58" stroke-width="7" fill="none"/>
    <path d="M ${rx2.toFixed(1)},${ry2.toFixed(1)} A ${R},${R} 0 0,1 88,${cy}" stroke="#f85149" stroke-width="7" fill="none"/>
    <line x1="${cx}" y1="${cy}" x2="${nx}" y2="${ny}" stroke="${nc}" stroke-width="2.5" stroke-linecap="round"/>
    <circle cx="${cx}" cy="${cy}" r="3.5" fill="#e6edf3"/>
    <text x="${cx}" y="${cy+9}" text-anchor="middle" fill="#e6edf3" font-size="11" font-weight="bold">${rsi}</text>
    <text x="9" y="${cy+12}" fill="#388bfd" font-size="7">0</text>
    <text x="82" y="${cy+12}" fill="#f85149" font-size="7">100</text>
  </svg>`;
}

const GRID_COLOR='#21262d', TICK_COLOR='#6e7681', TIP_BG='#1c2128', TIP_BORDER='#30363d';
const axisX = e => Object.assign({ticks:{color:TICK_COLOR,maxTicksLimit:6,font:{size:9}},grid:{color:GRID_COLOR}},e);
const axisY = e => Object.assign({position:'right',ticks:{color:TICK_COLOR,font:{size:9}},grid:{color:GRID_COLOR}},e);
const tipBase = () => ({backgroundColor:TIP_BG,borderColor:TIP_BORDER,borderWidth:1,titleColor:TICK_COLOR,bodyColor:'#e6edf3'});

// ── Build card HTML ───────────────────────────────────────────────────────────
function buildCard(s) {
  const pctSign  = s.pct >= 0 ? '+' : '';
  const pctClass = s.pct >= 0 ? 'up' : 'down';
  const maColor  = s.ma_above ? '#3fb950' : '#f85149';
  const maBadge  = (s.ma25 && s.ma75)
    ? `<span class="ma-badge" style="color:${maColor}">${s.ma_above?'▲':'▼'} MA25 ${s.ma_above?'>':'<'} MA75</span>` : '';
  let crossBadges = '';
  if (s.gc) crossBadges += '<span class="badge badge-gc">🌟 GC</span>';
  if (s.dc) crossBadges += '<span class="badge badge-dc">💀 DC</span>';
  const statusLabels = {bullish:'🟢 強気',bearish:'🔴 弱気',neutral:'🟡 中立'};
  const statusBadge  = `<span class="badge-status badge-${s.status}">${statusLabels[s.status]||'🟡 中立'}</span>`;
  const volFire  = s.vratio >= 1.5 ? ' <span class="vol-fire">🔥</span>' : '';
  const volColor = s.vratio >= 1.5 ? '#f0883e' : '#8b949e';
  const volBold  = s.vratio >= 1.5 ? 700 : 400;
  const sentLabel = sent => {
    const m={positive:['sent-positive','POS'],negative:['sent-negative','NEG'],neutral:['sent-neutral','NEU']};
    const [cls,lbl]=m[sent]||m.neutral;
    return `<span class="sent-badge ${cls}">${lbl}</span>`;
  };
  const newsHTML = (s.news && s.news.length)
    ? s.news.map(n=>`<div class="news-item">${sentLabel(n.sentiment)}<a href="${n.link}" target="_blank" rel="noopener noreferrer">${n.title}</a></div>`).join('')
    : '<div class="no-news">No news available</div>';
  const macdDiff  = ((s.macd||0)-(s.signal||0)).toFixed(4);
  const macdColor = (s.macd||0) > (s.signal||0) ? '#3fb950' : '#f85149';
  const extraBadge = s._extra ? '<span class="extra-badge">＋追加</span>' : '';

  const hasCharts = s.prices && s.prices.length > 0;

  return `
    <button class="remove-btn" onclick="hideStock('${s.ticker}')" title="削除">×</button>
    <div class="status-bar ${s.status}"></div>
    <div class="card-header">
      <div class="ticker-row">
        <span class="ticker">${s.ticker}</span>
        ${statusBadge}${crossBadges}${maBadge}${extraBadge}
      </div>
      <div class="company-name">${s.name}</div>
    </div>
    <div class="price-row">
      <span class="price">$${(s.price||0).toLocaleString('en-US',{minimumFractionDigits:2})}</span>
      <span class="pct ${pctClass}">${pctSign}${s.pct}%</span>
    </div>
    <div class="vol-row">
      <span>Vol: <b>${fmtVol(s.volume||0)}</b>${volFire}</span>
      <span style="color:#484f58">·</span>
      <span>Avg10: ${fmtVol(s.avgvol||0)}</span>
      <span style="color:#484f58">·</span>
      <span style="color:${volColor};font-weight:${volBold}">${(s.vratio||0).toFixed(1)}×</span>
    </div>
    <div class="summary-stats">
      ${s.ma25 ? `<div class="stat"><span class="stat-val">$${s.ma25}</span><span class="stat-lbl">MA25</span></div>` : ''}
      ${s.ma75 ? `<div class="stat"><span class="stat-val">$${s.ma75}</span><span class="stat-lbl">MA75</span></div>` : ''}
      <div class="stat"><span class="stat-val" style="color:${macdColor}">${macdDiff}</span><span class="stat-lbl">MACD Diff</span></div>
    </div>
    <div class="divider"></div>
    ${hasCharts ? `
    <div class="charts-row">
      <div class="gauge-wrap">
        <div class="gauge-label">RSI(14)</div>
        ${rsiGaugeSVG(s.rsi||50)}
        <div class="gauge-status">${(s.rsi||50)>=70?'⚠️ Overbought':(s.rsi||50)<=30?'⚠️ Oversold':'Normal'}</div>
      </div>
      <div class="price-chart-wrap"><canvas id="pc-${s.ticker}"></canvas></div>
    </div>
    <div class="macd-wrap">
      <div class="macd-label">MACD (12/26/9) — Line &amp; Signal</div>
      <div class="macd-chart-wrap"><canvas id="mc-${s.ticker}"></canvas></div>
    </div>
    <div class="divider"></div>` : ''}
    <div class="news-section">
      <div class="news-label">Latest News</div>
      ${newsHTML}
    </div>`;
}

// ── Render all cards ──────────────────────────────────────────────────────────
let ioRef = null;

function getVisibleStocks() {
  const all = [...STOCKS, ...extraStocks].filter(s => !hiddenSet.has(s.ticker));
  if (sortMode === 'up')   return [...all].sort((a,b) => b.pct - a.pct);
  if (sortMode === 'down') return [...all].sort((a,b) => a.pct - b.pct);
  return [...all].sort((a,b) => Math.abs(b.pct) - Math.abs(a.pct));
}

function renderAll() {
  if (ioRef) ioRef.disconnect();

  const visible = getVisibleStocks();
  document.getElementById('stock-count').textContent = visible.length + ' stocks';

  // Heatmap
  renderHeatmap(visible);

  // Cards
  const grid = document.getElementById('cards');
  grid.innerHTML = '';
  visible.forEach(s => {
    const card = document.createElement('div');
    card.className = 'card';
    card.id = `card-${s.ticker}`;
    card.dataset.pct = s.pct;
    card.dataset.ticker = s.ticker;
    card.innerHTML = buildCard(s);
    grid.appendChild(card);
  });

  // Lazy chart rendering
  ioRef = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const ticker = entry.target.dataset.ticker;
      const s = [...STOCKS, ...extraStocks].find(x => x.ticker === ticker);
      if (s) { renderPriceChart(s); renderMacdChart(s); }
      ioRef.unobserve(entry.target);
    });
  }, { rootMargin: '300px 0px' });

  grid.querySelectorAll('.card').forEach(c => ioRef.observe(c));
}

// ── Charts ────────────────────────────────────────────────────────────────────
function renderPriceChart(s) {
  const cv = document.getElementById(`pc-${s.ticker}`);
  if (!cv || cv._rendered || !s.prices?.length) return;
  cv._rendered = true;
  const datasets = [
    {label:'Price',data:s.prices,borderColor:'#58a6ff',borderWidth:1.5,pointRadius:0,tension:0.2,fill:false,order:3},
    {label:'MA25',data:s.ma25d,borderColor:'#d4a017',borderWidth:1.2,pointRadius:0,tension:0.3,fill:false,order:2},
    {label:'MA75',data:s.ma75d,borderColor:'#8b949e',borderWidth:1,borderDash:[4,2],pointRadius:0,tension:0.3,fill:false,order:1},
  ];
  if (s.gm?.length) datasets.push({label:'GC',type:'scatter',data:s.gm.map(p=>({x:p.x,y:p.y})),pointStyle:'triangle',pointRadius:8,borderColor:'#d4a017',backgroundColor:'#d4a017',order:0});
  if (s.dm?.length) datasets.push({label:'DC',type:'scatter',data:s.dm.map(p=>({x:p.x,y:p.y})),pointStyle:'triangle',pointRotation:180,pointRadius:8,borderColor:'#8b949e',backgroundColor:'#8b949e',order:0});
  new Chart(cv, {
    type:'line', data:{labels:s.dates,datasets},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:false},tooltip:Object.assign(tipBase(),{mode:'index',intersect:false,callbacks:{label:ctx=>`${ctx.dataset.label}: $${ctx.parsed.y??''}`}})},
      scales:{x:axisX(),y:axisY()}},
  });
}

function renderMacdChart(s) {
  const cv = document.getElementById(`mc-${s.ticker}`);
  if (!cv || cv._rendered || !s.macd_d?.length) return;
  cv._rendered = true;
  new Chart(cv, {
    type:'line',
    data:{labels:s.dates,datasets:[
      {label:'MACD',data:s.macd_d,borderColor:'#58a6ff',borderWidth:1.5,pointRadius:0,tension:0.2,fill:false,order:1},
      {label:'Signal',data:s.sig_d,borderColor:'#f0883e',borderWidth:1.2,borderDash:[3,2],pointRadius:0,tension:0.2,fill:false,order:2},
    ]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:false},tooltip:Object.assign(tipBase(),{mode:'index',intersect:false})},
      scales:{x:axisX({ticks:{display:false}}),y:axisY({ticks:{maxTicksLimit:3,font:{size:8}}})}},
  });
}

// ── Sort ──────────────────────────────────────────────────────────────────────
function setSort(mode) {
  sortMode = mode;
  LS.set('wl_sort', mode);
  ['abs','up','down'].forEach(m => {
    document.getElementById(`sort-${m}`).classList.toggle('active', m === mode);
  });
  renderAll();
}

// ── Hide / Restore ────────────────────────────────────────────────────────────
function hideStock(ticker) {
  hiddenSet.add(ticker);
  LS.set('wl_hidden', [...hiddenSet]);
  renderAll();
}

// ── Add Ticker Modal ──────────────────────────────────────────────────────────
function openAddModal() {
  document.getElementById('add-modal').classList.add('open');
  document.getElementById('add-input').value = '';
  document.getElementById('add-err').classList.remove('show');
  document.getElementById('add-spinner').classList.remove('show');
  setTimeout(() => document.getElementById('add-input').focus(), 100);
}
function closeAddModal() {
  document.getElementById('add-modal').classList.remove('open');
}

// JS-side indicator calculations for browser-added stocks
function jsEMA(arr, span) {
  const alpha = 2 / (span + 1);
  let v = arr[0]; const out = [v];
  for (let i = 1; i < arr.length; i++) { v = arr[i]*alpha + v*(1-alpha); out.push(v); }
  return out;
}
function jsRSI(closes, n=14) {
  const gains=[], losses=[];
  for (let i=1; i<closes.length; i++) { const d=closes[i]-closes[i-1]; gains.push(Math.max(d,0)); losses.push(Math.max(-d,0)); }
  const alpha=1/n; let ag=gains.slice(0,n).reduce((a,b)=>a+b)/n, al=losses.slice(0,n).reduce((a,b)=>a+b)/n;
  for (let i=n; i<gains.length; i++) { ag=ag*(1-alpha)+gains[i]*alpha; al=al*(1-alpha)+losses[i]*alpha; }
  return al===0 ? 100 : 100-100/(1+ag/al);
}
function jsMA(closes, n) { return closes.map((_,i) => i<n-1?null:closes.slice(i-n+1,i+1).reduce((a,b)=>a+b)/n); }

async function doAddTicker() {
  const sym = document.getElementById('add-input').value.trim().toUpperCase();
  const errEl = document.getElementById('add-err');
  const spinEl = document.getElementById('add-spinner');
  errEl.classList.remove('show');

  if (!sym) { errEl.textContent='ティッカーを入力してください'; errEl.classList.add('show'); return; }

  // Already in list: just unhide
  if ([...STOCKS,...extraStocks].find(s=>s.ticker===sym)) {
    hiddenSet.delete(sym);
    LS.set('wl_hidden',[...hiddenSet]);
    closeAddModal(); renderAll(); return;
  }

  spinEl.classList.add('show');
  try {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=1d&range=6mo`;
    const res = await fetch(url, {headers:{Accept:'application/json'}});
    const data = await res.json();
    const result = data.chart?.result?.[0];
    if (!result) throw new Error('銘柄が見つかりません');

    const meta = result.meta;
    const rawClose  = result.indicators.quote[0].close;
    const rawVol    = result.indicators.quote[0].volume;
    const timestamps = result.timestamp;

    // Filter nulls
    const valid = rawClose.map((c,i)=>({c,v:rawVol[i]||0,t:timestamps[i]})).filter(x=>x.c!=null);
    const closes = valid.map(x=>x.c);
    const vols   = valid.map(x=>x.v);
    const dates  = valid.map(x=>new Date(x.t*1000).toLocaleDateString('en-US',{month:'2-digit',day:'2-digit'}));

    const N = 60;
    const c60 = closes.slice(-N), v60 = vols.slice(-N), d60 = dates.slice(-N);
    const cur = closes.at(-1), prev = closes.at(-2)||cur;
    const pct = (cur-prev)/prev*100;
    const cvol = vols.at(-1)||0, avgvol = vols.slice(-11,-1).reduce((a,b)=>a+b,0)/10;

    const rsi = jsRSI(closes);
    const emaF = jsEMA(closes,12), emaS = jsEMA(closes,26);
    const macdLine = emaF.map((v,i)=>v-emaS[i]);
    const sigLine  = jsEMA(macdLine,9);
    const ma25arr  = jsMA(closes,25), ma75arr = jsMA(closes,75);

    const toN = (arr,dec=2) => arr.slice(-N).map(v=>v==null?null:+v.toFixed(dec));

    const s = {
      ticker: sym,
      name:   meta.longName || meta.shortName || sym,
      price:  +cur.toFixed(2),
      pct:    +pct.toFixed(2),
      volume: cvol, avgvol: +avgvol.toFixed(0),
      vratio: avgvol ? +(cvol/avgvol).toFixed(2) : 1,
      rsi:    +rsi.toFixed(1),
      macd:   +macdLine.at(-1).toFixed(4),
      signal: +sigLine.at(-1).toFixed(4),
      ma25:   ma25arr.at(-1) ? +ma25arr.at(-1).toFixed(2) : null,
      ma75:   ma75arr.at(-1) ? +ma75arr.at(-1).toFixed(2) : null,
      ma_above: !!(ma25arr.at(-1) && ma75arr.at(-1) && ma25arr.at(-1) > ma75arr.at(-1)),
      gc: false, dc: false,
      status: 'neutral',
      news: [], dates: d60,
      prices: toN(c60), ma25d: toN(ma25arr.slice(-N)), ma75d: toN(ma75arr.slice(-N)),
      macd_d: toN(macdLine.slice(-N),4), sig_d: toN(sigLine.slice(-N),4),
      gm: [], dm: [], _extra: true,
    };
    s.status = (() => {
      let sc=0;
      if(s.rsi>55)sc++;else if(s.rsi<45)sc--;
      if(s.ma25&&s.ma75){sc+=s.ma_above?1:-1;}
      sc+=s.pct>0.5?1:s.pct<-0.5?-1:0;
      return sc>=2?'bullish':sc<=-2?'bearish':'neutral';
    })();

    extraStocks.push(s);
    LS.set('wl_extra', extraStocks);
    closeAddModal(); renderAll();
  } catch(e) {
    errEl.textContent = e.message || '取得に失敗しました';
    errEl.classList.add('show');
  } finally {
    spinEl.classList.remove('show');
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
// Restore sort button state
document.getElementById(`sort-${sortMode}`)?.classList.add('active');
['abs','up','down'].filter(m=>m!==sortMode).forEach(m=>document.getElementById(`sort-${m}`)?.classList.remove('active'));

renderAll();
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
