#!/usr/bin/env python3
"""US Stock Watchlist Dashboard Generator
Usage: python generate.py
Reads tickers.txt (1 ticker per line). Falls back to built-in list if not found.
"""

import os
import random
import base64
import io
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import yfinance as yf
import pandas as pd
from PIL import Image, ImageDraw

# ── Tickers ────────────────────────────────────────────────────────────────────

_DEFAULT_TICKERS = [
    'ARM', 'AMD', 'SOXL', 'LPTH', 'TECL', 'NBIS', 'SNDK', 'TSM', 'CRDO',
    'NVDA', 'NUGT', 'LITE', 'AMZN', 'MU', 'IREN', 'EWY', 'META', 'OSCR',
    'ZM', 'MSFT', 'QQQ', 'HOOD', 'GOOG', 'APP',
]

if os.path.exists('tickers.txt'):
    with open('tickers.txt') as _f:
        TICKERS = [l.strip().upper() for l in _f if l.strip() and not l.startswith('#')]
    print(f"Loaded {len(TICKERS)} tickers from tickers.txt")
else:
    TICKERS = _DEFAULT_TICKERS
    print(f"tickers.txt not found — using default {len(TICKERS)} tickers")

# ── Company Names ──────────────────────────────────────────────────────────────

NAMES = {
    'NVDA':'NVIDIA',        'AAPL':'Apple',            'MSFT':'Microsoft',
    'GOOGL':'Alphabet',     'AMZN':'Amazon',           'META':'Meta Platforms',
    'AVGO':'Broadcom',      'TSLA':'Tesla',            'ORCL':'Oracle',
    'AMD':'AMD',            'INTC':'Intel',            'NFLX':'Netflix',
    'PLTR':'Palantir',      'QCOM':'Qualcomm',         'APP':'AppLovin',
    'MU':'Micron',          'SNDK':'Sandisk',          'NBIS':'Nebius',
    'ARM':'Arm Holdings',   'TSM':'TSMC',              'LITE':'Lumentum',
    'CRDO':'Credo Technology','LPTH':'LightPath',      'GS':'Goldman Sachs',
    'KO':'Coca-Cola',       'NU':'Nu Holdings',        'OSCR':'Oscar Health',
    'SPY':'S&P 500 ETF',    'QQQ':'Nasdaq ETF',        'IWM':'Russell 2000 ETF',
    'VT':'Vanguard All-World ETF','SOXL':'Semiconductor Bull 3X',
    'SLV':'Silver Trust',   'COPX':'Copper Miners ETF','GLD':'Gold Shares',
}

# ── Touch Icon ─────────────────────────────────────────────────────────────────

def make_touch_icon():
    S = 180
    img = Image.new('RGB', (S, S), (22, 27, 34))
    d   = ImageDraw.Draw(img)
    green = (63, 185, 80)
    white = (230, 237, 243)

    bar_w, gap = 16, 8
    heights = [38, 22, 50, 34, 62, 46, 80]
    x0, base_y = 14, 155

    for i, h in enumerate(heights):
        lx = x0 + i * (bar_w + gap)
        d.rectangle([lx, base_y - h, lx + bar_w, base_y], fill=green)

    cx = [x0 + i * (bar_w + gap) + bar_w // 2 for i in range(len(heights))]
    pts = list(zip(cx, [base_y - h for h in heights]))
    for i in range(len(pts) - 1):
        d.line([pts[i], pts[i + 1]], fill=white, width=7)
    ax, ay = pts[-1]
    d.polygon([(ax, ay - 12), (ax + 12, ay + 6), (ax - 12, ay + 6)], fill=white)
    return img

icon_img = make_touch_icon()
icon_img.save('apple-touch-icon.png')
icon_img.save('favicon.png')

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

def fetch_ticker(sym):
    tk = yf.Ticker(sym)
    hist = tk.history(period='6mo')
    if len(hist) < 30:
        return sym, None, 'skip'

    close = hist['Close']
    vol   = hist['Volume']

    cur    = float(close.iloc[-1])
    prev   = float(close.iloc[-2])
    pct    = (cur - prev) / prev * 100
    cvol   = int(vol.iloc[-1])
    avgvol = float(vol.tail(11).iloc[:-1].mean())
    vratio = cvol / avgvol if avgvol else 1.0

    rsi_s           = calc_rsi(close)
    rsi             = float(rsi_s.iloc[-1]) if pd.notna(rsi_s.iloc[-1]) else 50.0
    macd_s, sig_s, _ = calc_macd(close)
    ma25            = close.rolling(25).mean()
    ma75            = close.rolling(75).mean()
    _, _, recent_gc, recent_dc = detect_crosses(ma25, ma75, 5)
    ma25_last = float(ma25.iloc[-1]) if pd.notna(ma25.iloc[-1]) else None
    ma75_last = float(ma75.iloc[-1]) if pd.notna(ma75.iloc[-1]) else None
    ma_above  = bool(ma25_last and ma75_last and ma25_last > ma75_last)
    status    = overall_status(rsi, ma25_last, ma75_last, pct)

    # 会社名・52週高値・予想PER（辞書になければ API）
    name = NAMES.get(sym)
    w52h = None
    fwd_pe = None
    try:
        info   = tk.info
        if not name:
            name = info.get('shortName') or sym
        raw52h = info.get('fiftyTwoWeekHigh')
        w52h   = round(float(raw52h), 2) if raw52h else None
        raw_pe = info.get('forwardPE')
        fwd_pe = round(float(raw_pe), 1) if raw_pe else None
    except Exception:
        if not name:
            name = sym

    w52h_pct = round((cur - w52h) / w52h * 100, 1) if w52h else None

    N    = 60
    c60  = close.tail(N)
    dates = c60.index.strftime('%m/%d').tolist()

    return sym, {
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
        'w52h':     w52h,
        'w52h_pct': w52h_pct,
        'fwd_pe':   fwd_pe,
        'gc':       recent_gc,
        'dc':       recent_dc,
        'status':   status,
        'news':     [],
        'dates':    dates,
        'prices':   to_list(c60, 2),
        'ma25d':    to_list(ma25.tail(N), 2),
        'ma75d':    to_list(ma75.tail(N), 2),
        'macd_d':   to_list(macd_s.tail(N), 4),
        'sig_d':    to_list(sig_s.tail(N), 4),
    }, 'ok'

INDICES_DEF = [
    ('USD/JPY', 'USDJPY=X'),
    ('DOW',     '^DJI'),
    ('NDX',     '^NDX'),
    ('SOX',     '^SOX'),
    ('VIX',     '^VIX'),
]

def fetch_index(label, sym):
    tk  = yf.Ticker(sym)
    h   = tk.history(period='5d')
    if len(h) < 2:
        return {'label': label, 'price': None, 'pct': 0}
    cur  = float(h['Close'].iloc[-1])
    prev = float(h['Close'].iloc[-2])
    pct  = round((cur - prev) / prev * 100, 2)
    # 表示フォーマット
    if sym == 'USDJPY=X':
        price_str = f'{cur:.2f}'
    elif cur >= 1000:
        price_str = f'{cur:,.0f}'
    else:
        price_str = f'{cur:.2f}'
    return {'label': label, 'price': price_str, 'pct': pct}

results = {}
indices = []
with ThreadPoolExecutor(max_workers=8) as ex:
    # 銘柄
    futures = {ex.submit(fetch_ticker, sym): sym for sym in TICKERS}
    # 指数
    idx_futures = {ex.submit(fetch_index, lbl, sym): lbl for lbl, sym in INDICES_DEF}

    for fut in as_completed(futures):
        sym = futures[fut]
        try:
            s, data, status = fut.result()
            results[s] = (data, status)
            print(f"  {s:8s} {status}")
        except Exception as e:
            results[sym] = (None, f'ERROR: {e}')
            print(f"  {sym:8s} ERROR: {e}")

    for fut in as_completed(idx_futures):
        lbl = idx_futures[fut]
        try:
            indices.append(fut.result())
        except Exception as e:
            indices.append({'label': lbl, 'price': None, 'pct': 0})

# 指数を定義順に並べ直す
lbl_order = [lbl for lbl, _ in INDICES_DEF]
indices.sort(key=lambda x: lbl_order.index(x['label']) if x['label'] in lbl_order else 99)

stocks = [results[sym][0] for sym in TICKERS if results.get(sym, (None,))[0] is not None]

# セクター順でソート（デフォルト表示順）
SECTOR_ORDER = [
    # テック大型
    'NVDA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'AVGO', 'TSLA', 'ORCL',
    'AMD', 'INTC', 'NFLX', 'PLTR', 'QCOM', 'APP',
    # 半導体・ハード
    'MU', 'SNDK', 'NBIS', 'ARM', 'TSM', 'LITE', 'CRDO', 'LPTH',
    # 金融・その他
    'GS', 'KO', 'NU', 'OSCR',
    # ETF
    'SPY', 'QQQ', 'IWM', 'VT', 'SOXL',
    # コモディティ
    'SLV', 'COPX', 'GLD',
]
_sector_idx = {t: i for i, t in enumerate(SECTOR_ORDER)}
stocks.sort(key=lambda s: _sector_idx.get(s['ticker'], len(SECTOR_ORDER)))

QUOTES = [
    '休むも相場',
    '頭と尻尾はくれてやれ',
    '落ちるナイフは掴むな',
    '損小利大を心がけよ',
    '総悲観は買い',
    '買うは易し、売るは難し',
    '市場は常に正しい',
    'トレンドはあなたの友だ',
    '上げ百日、下げ三日',
    'もうはまだなり、まだはもうなり',
    '価格はすべてを織り込む',
    '良い投資家は退屈を楽しむ',
    '靴磨きの少年が株の話を始めたら天井',
    '相場に予測は禁物、対応あるのみ',
    '最大の敵は市場ではなく自分自身だ',
]
daily_quote = random.choice(QUOTES)

JST = timezone(timedelta(hours=9))
now_str = datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')
stocks_json  = json.dumps(stocks,  ensure_ascii=False)
indices_json = json.dumps(indices, ensure_ascii=False)

# ── HTML Template ──────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Watchlist">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="icon" type="image/png" href="favicon.png">
<title>Watchlist</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
/* ── Reset & Base ─────────────────────────────────────────────── */
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%;overflow-x:hidden}
body{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:13px;line-height:1.5;overflow-x:hidden;-webkit-overflow-scrolling:touch}
a{color:#58a6ff;text-decoration:none}
a:hover,a:focus{text-decoration:underline}
button{cursor:pointer;font-family:inherit;-webkit-tap-highlight-color:transparent;touch-action:manipulation}

/* ── Header ───────────────────────────────────────────────────── */
.header{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;padding-top:max(10px,env(safe-area-inset-top));padding-left:max(14px,env(safe-area-inset-left));padding-right:max(14px,env(safe-area-inset-right));border-bottom:1px solid #30363d;background:#161b22;position:-webkit-sticky;position:sticky;top:0;z-index:200;gap:8px}
.header-left{display:flex;flex-direction:column;gap:2px;min-width:0}
h1{font-size:17px;font-weight:700;color:#e6edf3;white-space:nowrap}
.gen-time{font-size:10px;color:#8b949e}
.header-right{display:flex;align-items:center;gap:6px;flex-shrink:0}
.update-link{display:inline-flex;align-items:center;gap:3px;padding:5px 9px;border-radius:6px;font-size:11px;font-weight:600;background:#1c2128;color:#e6edf3;border:1px solid #30363d;text-decoration:none;white-space:nowrap}
.update-link:hover{background:#2d333b;text-decoration:none}

/* ── Quote ────────────────────────────────────────────────────── */
.quote-section{padding:8px 14px 4px;display:flex;align-items:center;gap:6px}
.quote-mark{font-size:16px;color:#30363d;line-height:1;flex-shrink:0}
.quote-text{font-size:11px;color:#8b949e;font-style:italic;letter-spacing:.3px}

/* ── Memo ─────────────────────────────────────────────────────── */
.memo-section{padding:4px 14px 6px}
.memo-label{font-size:10px;color:#8b949e;letter-spacing:.5px;text-transform:uppercase;margin-bottom:4px}
.memo-box{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:7px 10px;color:#e6edf3;font-size:12px;line-height:1.5;font-family:inherit;min-height:32px;outline:none;transition:border-color .2s;word-break:break-word;white-space:pre-wrap}
.memo-box:focus{border-color:#58a6ff}
.memo-box:empty::before{content:'...';color:#484f58;pointer-events:none}

/* ── Heatmap ──────────────────────────────────────────────────── */
.heatmap-section{padding:10px 14px 6px}
.heatmap-section h2{font-size:10px;color:#8b949e;margin-bottom:7px;font-weight:600;text-transform:uppercase;letter-spacing:.6px}
.heatmap{display:flex;flex-wrap:wrap;gap:3px}
.hm-cell{display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:0;min-height:40px;border-radius:6px;font-size:11px;font-weight:700;padding:3px 5px;border:1px solid rgba(255,255,255,.08);transition:transform .12s;-webkit-tap-highlight-color:transparent;user-select:none;-webkit-user-select:none;text-decoration:none;touch-action:manipulation}
.heatmap:not(.idx-heatmap) .hm-cell{width:calc((100% - 30px) / 11);flex:none}
.hm-cell:hover,.hm-cell:active{transform:scale(1.1);z-index:2}
.hm-cell .hm-pct{font-size:9px;font-weight:400;margin-top:1px}
.idx-heatmap{flex-wrap:nowrap;margin-bottom:0}
.idx-heatmap .hm-cell{flex:1;min-width:0}
.idx-heatmap .hm-price{font-size:9px;font-weight:400;margin-top:1px;opacity:.85}
.idx-divider{height:1px;background:#30363d;margin:5px 0}

/* ── Sort Bar ─────────────────────────────────────────────────── */
.sort-bar{display:flex;align-items:center;gap:6px;padding:8px 14px 4px;flex-wrap:wrap}
.sort-label{font-size:10px;color:#8b949e}
.sort-btn{padding:7px 12px;border-radius:20px;font-size:11px;font-weight:600;border:1px solid #30363d;background:#1c2128;color:#8b949e;transition:all .12s;touch-action:manipulation}
.sort-btn.active{background:#1f6feb22;border-color:#1f6feb;color:#58a6ff}
.sort-btn:active{opacity:.7}

/* ── Cards ────────────────────────────────────────────────────── */
.cards-section{padding:6px 14px;padding-bottom:max(40px,calc(env(safe-area-inset-bottom) + 24px))}
.cards-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,360px),1fr));gap:12px}
.card{background:#161b22;border:1px solid #30363d;border-radius:10px;overflow:hidden;scroll-margin-top:50px}
.card:hover{border-color:#58a6ff44}

.status-bar{height:4px;width:100%}
.status-bar.bullish{background:linear-gradient(90deg,#238636,#2ea043)}
.status-bar.bearish{background:linear-gradient(90deg,#da3633,#f85149)}
.status-bar.neutral{background:linear-gradient(90deg,#9e6a03,#d29922)}
.card-header{padding:10px 12px 5px}
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
.gauge-wrap{display:flex;flex-direction:column;align-items:center;width:110px;flex-shrink:0}
.gauge-label{font-size:10px;color:#8b949e;margin-bottom:2px;text-transform:uppercase;letter-spacing:.5px}
.gauge-status{font-size:9px;color:#8b949e;margin-top:2px;text-align:center}
.price-chart-wrap{flex:1;min-height:120px;position:relative;min-width:0}
.macd-wrap{padding:2px 12px 8px}
.macd-label{font-size:10px;color:#8b949e;margin-bottom:3px;text-transform:uppercase;letter-spacing:.5px}
.macd-chart-wrap{height:60px;position:relative}
canvas{display:block}
.gauge-wrap svg{width:100%;max-width:108px;height:auto;aspect-ratio:100/66}


/* ── Tablet / Mobile ──────────────────────────────────────────── */
@media(min-width:601px) and (max-width:900px){
  .cards-grid{grid-template-columns:repeat(2,1fr)}
}
@media(max-width:600px){
  body{font-size:12px}
  .header{padding:8px 12px;padding-top:max(8px,env(safe-area-inset-top));padding-left:max(12px,env(safe-area-inset-left));padding-right:max(12px,env(safe-area-inset-right))}
  h1{font-size:15px}
  .heatmap-section{padding:8px 10px 5px}
  .hm-cell{min-height:37px;font-size:10px;padding:3px 4px;border-radius:5px}
  .heatmap:not(.idx-heatmap) .hm-cell{width:calc((100% - 18px) / 7);flex:none}
  .hm-cell .hm-pct{font-size:8px}
  .sort-bar{padding:6px 10px 3px;gap:5px}
  .cards-section{padding:5px 10px;padding-bottom:max(36px,calc(env(safe-area-inset-bottom) + 20px))}
  .cards-grid{grid-template-columns:1fr;gap:10px}
  .card{border-radius:8px}
  .price{font-size:20px}
  .ticker{font-size:16px}
  .charts-row{padding:7px 10px 5px}
  .gauge-wrap{width:100px}
  .price-chart-wrap{min-height:115px}
  .macd-chart-wrap{height:54px}
  .divider{margin:0 10px}
  .summary-stats,.vol-row,.price-row{padding-left:10px;padding-right:10px}
  .macd-wrap{padding:2px 10px 7px}
  .sort-btn{padding:8px 14px}
}
@media(max-width:375px){
  .hm-cell{font-size:9px}
  .ticker{font-size:15px}
  .price{font-size:18px}
  .gauge-wrap{width:90px}
}
/* ── Search ───────────────────────────────────────────────────── */
#search-btn{position:fixed;bottom:max(120px,calc(env(safe-area-inset-bottom) + 112px));right:16px;width:40px;height:40px;border-radius:8px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);color:#e6edf3;font-size:16px;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:background .2s;z-index:300;-webkit-tap-highlight-color:transparent}
#search-btn:hover{background:rgba(255,255,255,.16)}
#search-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:400;align-items:flex-start;justify-content:center;padding-top:80px}
#search-overlay.open{display:flex}
#search-box{background:#1c2128;border:1px solid #30363d;border-radius:10px;padding:12px 14px;display:flex;gap:8px;align-items:center;width:min(320px,90vw);box-shadow:0 8px 32px rgba(0,0,0,.6)}
#search-input{flex:1;background:none;border:none;outline:none;color:#e6edf3;font-size:16px;font-family:inherit;text-transform:uppercase}
#search-input::placeholder{color:#484f58;text-transform:none}
#search-go{padding:6px 12px;background:#238636;border:none;border-radius:6px;color:#fff;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap}
@keyframes shake{0%,100%{transform:translateX(0)}20%{transform:translateX(-6px)}40%{transform:translateX(6px)}60%{transform:translateX(-4px)}80%{transform:translateX(4px)}}
.shake{animation:shake .35s ease}

/* ── Scroll to top ────────────────────────────────────────────── */
#totop,#tobottom{position:fixed;right:16px;width:40px;height:40px;border-radius:8px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);color:#e6edf3;font-size:16px;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:opacity .25s,background .2s;z-index:300;-webkit-tap-highlight-color:transparent}
#totop{bottom:max(72px,calc(env(safe-area-inset-bottom) + 64px));opacity:0;pointer-events:none}
#tobottom{bottom:max(24px,calc(env(safe-area-inset-bottom) + 16px));opacity:0;pointer-events:none}
#totop.visible,#tobottom.visible{opacity:1;pointer-events:auto}
#totop:hover,#tobottom:hover{background:rgba(255,255,255,.16)}
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
    <a class="update-link" href="https://github.com/kirevantolix/dashboard/actions/workflows/update.yml" target="_blank" rel="noopener">🔄 更新</a>
  </div>
</div>

<!-- Quote of the day -->
<div class="quote-section">
  <span class="quote-mark">"</span>
  <span class="quote-text">QUOTE_PLACEHOLDER</span>
  <span class="quote-mark">"</span>
</div>

<!-- Memo -->
<div class="memo-section">
  <div class="memo-label">MEMO</div>
  <div class="memo-box" id="memo" contenteditable="true" spellcheck="false"></div>
</div>

<!-- Heatmap -->
<div class="heatmap-section">
  <h2>Heatmap — Daily Change</h2>
  <div class="heatmap idx-heatmap" id="idx-heatmap"></div>
  <div class="idx-divider"></div>
  <div class="heatmap" id="heatmap"></div>
</div>

<!-- Sort Bar + Cards -->
<div class="sort-bar">
  <span class="sort-label">並び替え:</span>
  <button class="sort-btn active" id="sort-sector" onclick="setSort('sector')">☰ セクター順</button>
  <button class="sort-btn" id="sort-up"     onclick="setSort('up')">▲ 値上がり</button>
  <button class="sort-btn" id="sort-down"   onclick="setSort('down')">▼ 値下がり</button>
  <button class="sort-btn" id="sort-rsi"    onclick="setSort('rsi')">▲ RSI</button>
</div>
<button id="search-btn" onclick="openSearch()" aria-label="検索">🔍</button>
<div id="search-overlay" onclick="closeSearch(event)">
  <div id="search-box">
    <input id="search-input" type="text" placeholder="ティッカー例: NVDA" autocomplete="off" autocorrect="off" autocapitalize="characters" spellcheck="false" style="text-transform:uppercase" onkeydown="if(event.key==='Enter')doSearch()">
    <button id="search-go" onclick="doSearch()">検索</button>
  </div>
</div>

<button id="totop" onclick="window.scrollTo({top:0,behavior:'smooth'})" aria-label="トップへ戻る">▲</button>
<button id="tobottom" onclick="window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'})" aria-label="一番下へ">▼</button>

<div class="cards-section">
  <div class="cards-grid" id="cards"></div>
</div>


<script>
const STOCKS  = STOCKS_JSON_PLACEHOLDER;
const INDICES = INDICES_JSON_PLACEHOLDER;
const GENERATED_AT = 'GENERATED_AT_PLACEHOLDER';

document.getElementById('gen-time').textContent = GENERATED_AT;

// ── Persistence ───────────────────────────────────────────────────────────────
const LS = {
  get: (k, def) => { try { return JSON.parse(localStorage.getItem(k) ?? 'null') ?? def; } catch { return def; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
let sortMode = LS.get('wl_sort', 'sector');
if (!['sector','up','down','rsi'].includes(sortMode)) sortMode = 'sector';

// ── Heatmap ───────────────────────────────────────────────────────────────────
function pctToColor(pct) {
  const t = Math.min(Math.abs(pct), 5) / 5;
  return pct >= 0
    ? `rgb(${Math.round(20+t*10)},${Math.round(56+t*100)},${Math.round(20+t*10)})`
    : `rgb(${Math.round(100+t*155)},${Math.round(20+(1-t)*36)},${Math.round(20+(1-t)*36)})`;
}

function renderIndexHeatmap() {
  const hm = document.getElementById('idx-heatmap');
  hm.innerHTML = '';
  INDICES.forEach(ix => {
    const cell = document.createElement('div');
    cell.className = 'hm-cell';
    cell.style.background = pctToColor(ix.pct);
    cell.style.color = Math.abs(ix.pct) > 2 ? '#fff' : '#e6edf3';
    const sign = ix.pct >= 0 ? '+' : '';
    cell.innerHTML = `<span>${ix.label}</span><span class="hm-price">${ix.price ?? '—'}</span><span class="hm-pct">${sign}${ix.pct}%</span>`;
    hm.appendChild(cell);
  });
}

function renderHeatmap(stocks) {
  const hm = document.getElementById('heatmap');
  hm.innerHTML = '';
  stocks.forEach(s => {
    const a = document.createElement('a');
    a.className = 'hm-cell';
    a.href = '#';
    a.dataset.ticker = s.ticker;
    a.style.background = pctToColor(s.pct);
    a.style.color = Math.abs(s.pct) > 2 ? '#fff' : '#e6edf3';
    a.title = `${s.name}  ${s.pct >= 0 ? '+' : ''}${s.pct}%`;
    a.innerHTML = `<span>${s.ticker}</span><span class="hm-pct">${s.pct >= 0 ? '+' : ''}${s.pct}%</span>`;
    a.addEventListener('click', e => {
      e.preventDefault();
      const card = document.getElementById(`card-${s.ticker}`);
      if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
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
  return `<svg viewBox="0 0 100 66" width="100" height="66" style="display:block;width:100%;max-width:108px">
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
  const w52Label  = s.w52h_pct != null
    ? (s.w52h_pct >= 0 ? '🏆' : `${s.w52h_pct}%`)
    : null;
  const w52Color  = s.w52h_pct == null ? '#8b949e'
    : s.w52h_pct >= -5  ? '#d4a017'
    : s.w52h_pct >= -10 ? '#3fb950'
    : '#8b949e';
  const hasCharts = s.prices && s.prices.length > 0;

  return `
    <div class="status-bar ${s.status}"></div>
    <div class="card-header">
      <div class="ticker-row">
        <span class="ticker">${s.ticker}</span>
        ${statusBadge}${crossBadges}${maBadge}
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
      ${w52Label ? `<div class="stat"><span class="stat-val" style="color:${w52Color}">${w52Label}</span><span class="stat-lbl">52W High</span></div>` : ''}
      <div class="stat"><span class="stat-val">${s.fwd_pe != null ? s.fwd_pe : 'N/A'}</span><span class="stat-lbl">Fwd PE</span></div>
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
    </div>` : ''}`;
}

// ── Render all cards ──────────────────────────────────────────────────────────
let ioRef = null;

function getVisibleStocks() {
  const all = [...STOCKS];
  if (sortMode === 'up')   return [...all].sort((a,b) => b.pct - a.pct);
  if (sortMode === 'down') return [...all].sort((a,b) => a.pct - b.pct);
  if (sortMode === 'rsi')  return [...all].sort((a,b) => (b.rsi||0) - (a.rsi||0));
  return all; // sector order = STOCKS array order
}

function renderAll() {
  if (ioRef) ioRef.disconnect();

  const visible = getVisibleStocks();
  document.getElementById('stock-count').textContent = visible.length + ' stocks';

  renderIndexHeatmap();
  renderHeatmap(visible);

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

  ioRef = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const ticker = entry.target.dataset.ticker;
      const s = STOCKS.find(x => x.ticker === ticker);
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
    {label:'Price', data:s.prices, borderColor:'#58a6ff', borderWidth:1.5, pointRadius:0, tension:0.2, fill:false, order:3},
    {label:'MA25',  data:s.ma25d,  borderColor:'#d4a017', borderWidth:1.2, pointRadius:0, tension:0.3, fill:false, order:2},
    {label:'MA75',  data:s.ma75d,  borderColor:'#8b949e', borderWidth:1,   borderDash:[4,2], pointRadius:0, tension:0.3, fill:false, order:1},
  ];
  const pc = new Chart(cv, {
    type:'line', data:{labels:s.dates, datasets},
    options:{responsive:true, maintainAspectRatio:false, animation:false,
      plugins:{legend:{display:false}, tooltip:Object.assign(tipBase(),{mode:'index',intersect:false,callbacks:{label:ctx=>`${ctx.dataset.label}: $${ctx.parsed.y??''}`}})},
      scales:{x:axisX(), y:axisY()}},
  });
  cv.addEventListener('touchend', () => { pc.tooltip.setActiveElements([], {}); pc.update('none'); }, {passive:true});
}

function renderMacdChart(s) {
  const cv = document.getElementById(`mc-${s.ticker}`);
  if (!cv || cv._rendered || !s.macd_d?.length) return;
  cv._rendered = true;
  const mc = new Chart(cv, {
    type:'line',
    data:{labels:s.dates, datasets:[
      {label:'MACD',   data:s.macd_d, borderColor:'#58a6ff', borderWidth:1.5, pointRadius:0, tension:0.2, fill:false, order:1},
      {label:'Signal', data:s.sig_d,  borderColor:'#f0883e', borderWidth:1.2, borderDash:[3,2], pointRadius:0, tension:0.2, fill:false, order:2},
    ]},
    options:{responsive:true, maintainAspectRatio:false, animation:false,
      plugins:{legend:{display:false}, tooltip:Object.assign(tipBase(),{mode:'index',intersect:false})},
      scales:{x:axisX({ticks:{display:false}}), y:axisY({ticks:{maxTicksLimit:3,font:{size:8}}})}},
  });
  cv.addEventListener('touchend', () => { mc.tooltip.setActiveElements([], {}); mc.update('none'); }, {passive:true});
}

// ── Sort ──────────────────────────────────────────────────────────────────────
function setSort(mode) {
  sortMode = mode;
  LS.set('wl_sort', mode);
  ['sector','up','down','rsi'].forEach(m => {
    document.getElementById(`sort-${m}`).classList.toggle('active', m === mode);
  });
  renderAll();
}

// ── Init ──────────────────────────────────────────────────────────────────────
// ページロード時にハッシュを消してトップに戻る
history.replaceState(null, '', window.location.pathname);
window.scrollTo(0, 0);

document.getElementById(`sort-${sortMode}`)?.classList.add('active');
['sector','up','down'].filter(m=>m!==sortMode).forEach(m=>document.getElementById(`sort-${m}`)?.classList.remove('active'));

renderAll();

// Memo
const memoEl = document.getElementById('memo');
memoEl.textContent = localStorage.getItem('wl_memo') || '';
memoEl.addEventListener('input', () => localStorage.setItem('wl_memo', memoEl.textContent));

// 検索
function openSearch() {
  const ov = document.getElementById('search-overlay');
  ov.classList.add('open');
  setTimeout(() => document.getElementById('search-input').focus(), 50);
}
function closeSearch(e) {
  if (e.target === document.getElementById('search-overlay')) {
    document.getElementById('search-overlay').classList.remove('open');
  }
}
function doSearch() {
  const q = document.getElementById('search-input').value.trim().toUpperCase();
  document.getElementById('search-overlay').classList.remove('open');
  if (!q) return;
  const card = document.getElementById(`card-${q}`);
  if (card) {
    card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } else {
    const box = document.getElementById('search-box');
    box.classList.remove('shake');
    void box.offsetWidth;
    box.classList.add('shake');
    document.getElementById('search-overlay').classList.add('open');
  }
  document.getElementById('search-input').value = '';
}

// トップへ戻るボタン
const toTopBtn = document.getElementById('totop');
const toBotBtn = document.getElementById('tobottom');
window.addEventListener('scroll', () => {
  const scrolled = window.scrollY > 300;
  toTopBtn.classList.toggle('visible', scrolled);
  toBotBtn.classList.toggle('visible', scrolled);
}, {passive: true});
</script>
</body>
</html>
"""

HTML = HTML.replace('STOCKS_JSON_PLACEHOLDER',  stocks_json)
HTML = HTML.replace('INDICES_JSON_PLACEHOLDER', indices_json)
HTML = HTML.replace('GENERATED_AT_PLACEHOLDER', now_str)
HTML = HTML.replace('QUOTE_PLACEHOLDER', daily_quote)

with open('dashboard.html', 'w', encoding='utf-8') as f:
    f.write(HTML)

kb = len(HTML) // 1024
print(f"\n✅  Generated dashboard.html  ({kb} KB, {len(stocks)} stocks)")
