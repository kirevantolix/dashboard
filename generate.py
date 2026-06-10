import yfinance as yf
import pandas as pd
import json
import requests
import re
from datetime import datetime
from pathlib import Path

# ── 設定 ──────────────────────────────────────────────
WATCHLIST_FILE = "watchlist.txt"
OUTPUT_FILE = "dashboard.html"
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
MA_SHORT, MA_LONG = 25, 75
VOL_SPIKE_RATIO = 1.5
GC_DC_WINDOW = 5
CHART_DAYS = 90

# ── 感情分析キーワード ────────────────────────────────
POS_KEYWORDS = ["surge", "jump", "beat", "record", "gain", "rise", "rally", "soar",
                "growth", "profit", "upgrade", "buy", "strong", "bullish", "boost"]
NEG_KEYWORDS = ["drop", "fall", "miss", "loss", "decline", "cut", "sell", "weak",
                "bearish", "crash", "warn", "downgrade", "risk", "concern", "plunge"]

def sentiment(text):
    t = text.lower()
    pos = sum(1 for w in POS_KEYWORDS if w in t)
    neg = sum(1 for w in NEG_KEYWORDS if w in t)
    if pos > neg: return "positive"
    if neg > pos: return "negative"
    return "neutral"

# ── テクニカル指標 ────────────────────────────────────
def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, float('nan'))
    return (100 - 100 / (1 + rs)).iloc[-1]

def calc_macd(close):
    ema_fast = close.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def detect_cross(ma_short, ma_long, window=5):
    crosses = []
    for i in range(1, len(ma_short)):
        prev_diff = ma_short.iloc[i-1] - ma_long.iloc[i-1]
        curr_diff = ma_short.iloc[i] - ma_long.iloc[i]
        if prev_diff < 0 and curr_diff > 0:
            crosses.append({"idx": i, "type": "GC"})
        elif prev_diff > 0 and curr_diff < 0:
            crosses.append({"idx": i, "type": "DC"})
    recent = [c for c in crosses if c["idx"] >= len(ma_short) - window]
    latest = crosses[-1] if crosses else None
    return recent, latest

# ── ニュース取得 ──────────────────────────────────────
def fetch_news(ticker):
    try:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        r = requests.get(url, timeout=5)
        items = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', r.text)
        items = [i for i in items if ticker.upper() not in i.upper() or len(i) > 10]
        results = []
        for title in items[1:4]:
            results.append({"title": title, "sentiment": sentiment(title)})
        return results
    except:
        return []

# ── 銘柄データ取得 ────────────────────────────────────
def fetch_stock(ticker):
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="6mo")
        if hist.empty or len(hist) < MA_LONG:
            hist = tk.history(period="1y")
        if hist.empty:
            return None

        close = hist["Close"]
        volume = hist["Volume"]

        # 価格・騰落率
        current = close.iloc[-1]
        prev = close.iloc[-2]
        change = current - prev
        change_pct = change / prev * 100

        # 出来高
        vol_today = volume.iloc[-1]
        vol_avg10 = volume.rolling(10).mean().iloc[-1]
        vol_spike = vol_today > vol_avg10 * VOL_SPIKE_RATIO

        # RSI
        rsi = calc_rsi(close)

        # MACD
        macd_line, signal_line, histogram = calc_macd(close)

        # MA
        ma_short = close.rolling(MA_SHORT).mean()
        ma_long = close.rolling(MA_LONG).mean()
        ma_above = ma_short.iloc[-1] > ma_long.iloc[-1]

        # クロス検出
        recent_crosses, _ = detect_cross(ma_short.dropna(), ma_long.dropna())

        # チャート用データ（直近CHART_DAYS日）
        chart_close = close.tail(CHART_DAYS).tolist()
        chart_ma25 = ma_short.tail(CHART_DAYS).tolist()
        chart_ma75 = ma_long.tail(CHART_DAYS).tolist()
        chart_dates = [str(d.date()) for d in close.tail(CHART_DAYS).index]

        # MACD チャート用
        chart_macd = macd_line.tail(CHART_DAYS).tolist()
        chart_signal = signal_line.tail(CHART_DAYS).tolist()
        chart_hist = histogram.tail(CHART_DAYS).tolist()

        # クロスマーカー位置（チャート用インデックス）
        cross_markers = []
        offset = len(close) - CHART_DAYS
        for c in recent_crosses:
            chart_idx = c["idx"] - offset
            if 0 <= chart_idx < CHART_DAYS:
                cross_markers.append({"idx": chart_idx, "type": c["type"]})

        # 総合判定
        score = 0
        if change_pct > 0: score += 1
        if rsi < 70 and rsi > 30: score += 1
        if ma_above: score += 1
        if score >= 2: status = "bullish"
        elif score == 1: status = "neutral"
        else: status = "bearish"

        # 最新クロスバッジ
        badge = None
        if recent_crosses:
            badge = recent_crosses[-1]["type"]

        info = tk.fast_info
        name = ticker
        try:
            name = tk.info.get("shortName", ticker)
        except:
            pass

        return {
            "ticker": ticker,
            "name": name,
            "current": round(current, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "volume": int(vol_today),
            "vol_avg10": int(vol_avg10),
            "vol_spike": vol_spike,
            "rsi": round(rsi, 1),
            "macd_val": round(macd_line.iloc[-1], 3),
            "signal_val": round(signal_line.iloc[-1], 3),
            "hist_val": round(histogram.iloc[-1], 3),
            "ma_above": ma_above,
            "badge": badge,
            "status": status,
            "chart_close": chart_close,
            "chart_ma25": chart_ma25,
            "chart_ma75": chart_ma75,
            "chart_macd": chart_macd,
            "chart_signal": chart_signal,
            "chart_hist": chart_hist,
            "chart_dates": chart_dates,
            "cross_markers": cross_markers,
            "news": fetch_news(ticker),
        }
    except Exception as e:
        print(f"  ERROR {ticker}: {e}")
        return None

# ── メイン ────────────────────────────────────────────
def main():
    tickers = [t.strip() for t in Path(WATCHLIST_FILE).read_text().splitlines() if t.strip()]
    print(f"取得中... {len(tickers)}銘柄")
    stocks = []
    for t in tickers:
        print(f"  {t}...", end=" ", flush=True)
        d = fetch_stock(t)
        if d:
            stocks.append(d)
            print("✓")
        else:
            print("✗")

    # 騰落率絶対値でソート
    stocks.sort(key=lambda x: abs(x["change_pct"]), reverse=True)

    # HTML生成
    html = build_html(stocks)
    Path(OUTPUT_FILE).write_text(html, encoding="utf-8")
    print(f"\n✅ {OUTPUT_FILE} 生成完了")

def build_html(stocks):
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stocks_json = json.dumps(stocks, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Watchlist Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0d0d0f;
    --surface: #16161a;
    --surface2: #1e1e24;
    --border: #2a2a35;
    --text: #e8e8f0;
    --muted: #6b6b80;
    --green: #22c55e;
    --red: #ef4444;
    --gold: #f59e0b;
    --blue: #3b82f6;
    --purple: #a855f7;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'SF Pro Display', -apple-system, BlinkMacSystemFont, sans-serif; min-height: 100vh; }}

  /* ヘッダー */
  .header {{ padding: 20px 24px 12px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); }}
  .header h1 {{ font-size: 18px; font-weight: 700; letter-spacing: 0.05em; color: var(--text); }}
  .header-meta {{ font-size: 11px; color: var(--muted); }}

  /* ヒートマップ */
  .heatmap-section {{ padding: 16px 24px; }}
  .heatmap-title {{ font-size: 11px; color: var(--muted); letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 10px; }}
  .heatmap {{ display: flex; flex-wrap: wrap; gap: 4px; }}
  .heatmap-cell {{
    padding: 6px 10px; border-radius: 6px; font-size: 11px; font-weight: 600;
    cursor: default; transition: transform 0.1s;
    display: flex; flex-direction: column; align-items: center; gap: 1px;
  }}
  .heatmap-cell:hover {{ transform: scale(1.05); }}
  .heatmap-cell .hm-ticker {{ font-size: 10px; font-weight: 700; }}
  .heatmap-cell .hm-pct {{ font-size: 10px; }}

  /* カードグリッド */
  .cards-section {{ padding: 0 24px 40px; }}
  .cards-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }}

  /* カード */
  .card {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
    overflow: hidden; transition: border-color 0.2s;
  }}
  .card:hover {{ border-color: #3a3a50; }}
  .card.bullish {{ border-left: 3px solid var(--green); }}
  .card.bearish {{ border-left: 3px solid var(--red); }}
  .card.neutral {{ border-left: 3px solid var(--gold); }}

  /* カードヘッダー */
  .card-header {{ padding: 14px 16px 10px; display: flex; align-items: flex-start; justify-content: space-between; }}
  .card-title {{ display: flex; flex-direction: column; gap: 2px; }}
  .card-ticker {{ font-size: 15px; font-weight: 800; letter-spacing: 0.04em; }}
  .card-name {{ font-size: 11px; color: var(--muted); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .card-badges {{ display: flex; gap: 4px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }}
  .badge {{ padding: 3px 8px; border-radius: 20px; font-size: 10px; font-weight: 700; }}
  .badge-gc {{ background: rgba(245,158,11,0.2); color: var(--gold); border: 1px solid rgba(245,158,11,0.4); }}
  .badge-dc {{ background: rgba(100,100,120,0.3); color: #9ca3af; border: 1px solid rgba(100,100,120,0.4); }}
  .badge-status {{ font-size: 9px; }}
  .badge-fire {{ font-size: 13px; }}
  .ma-indicator {{ font-size: 10px; color: var(--muted); }}

  /* 価格エリア */
  .price-area {{ padding: 0 16px 10px; display: flex; align-items: baseline; gap: 10px; }}
  .price {{ font-size: 24px; font-weight: 800; font-variant-numeric: tabular-nums; }}
  .change {{ font-size: 13px; font-weight: 600; }}
  .up {{ color: var(--green); }}
  .down {{ color: var(--red); }}

  /* メトリクス */
  .metrics {{ padding: 0 16px 10px; display: flex; gap: 16px; }}
  .metric {{ display: flex; flex-direction: column; gap: 2px; }}
  .metric-label {{ font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }}
  .metric-value {{ font-size: 12px; font-weight: 600; }}

  /* RSIゲージ */
  .rsi-area {{ padding: 0 16px 10px; display: flex; align-items: center; gap: 12px; }}
  .rsi-gauge-wrap {{ position: relative; width: 64px; height: 36px; flex-shrink: 0; }}
  .rsi-gauge-wrap canvas {{ display: block; }}
  .rsi-val {{ position: absolute; bottom: 0; left: 50%; transform: translateX(-50%); font-size: 11px; font-weight: 700; white-space: nowrap; }}
  .rsi-info {{ display: flex; flex-direction: column; gap: 2px; }}
  .rsi-label {{ font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }}
  .rsi-status {{ font-size: 11px; font-weight: 600; }}
  .rsi-hot {{ color: var(--red); }}
  .rsi-cold {{ color: var(--blue); }}
  .rsi-normal {{ color: var(--muted); }}

  /* チャート */
  .chart-wrap {{ padding: 0 12px 8px; position: relative; height: 100px; }}
  .chart-label {{ font-size: 9px; color: var(--muted); padding: 0 4px 2px; text-transform: uppercase; letter-spacing: 0.06em; }}
  .macd-wrap {{ padding: 0 12px 10px; height: 60px; }}

  /* ニュース */
  .news-section {{ border-top: 1px solid var(--border); padding: 10px 16px 12px; }}
  .news-title {{ font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 6px; }}
  .news-item {{ display: flex; align-items: flex-start; gap: 6px; margin-bottom: 5px; }}
  .news-sentiment {{ padding: 1px 5px; border-radius: 3px; font-size: 9px; font-weight: 700; flex-shrink: 0; margin-top: 1px; }}
  .sent-positive {{ background: rgba(34,197,94,0.2); color: var(--green); }}
  .sent-negative {{ background: rgba(239,68,68,0.2); color: var(--red); }}
  .sent-neutral {{ background: rgba(107,107,128,0.2); color: var(--muted); }}
  .news-text {{ font-size: 11px; color: #c0c0d0; line-height: 1.4; }}



  @media (max-width: 600px) {{
    .header {{ padding: 14px 16px 10px; }}
    .heatmap-section, .cards-section {{ padding-left: 16px; padding-right: 16px; }}
    .cards-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>📊 Watchlist</h1>
    <div class="header-meta">更新: {generated_at}</div>
  </div>
</div>

<div class="heatmap-section">
  <div class="heatmap-title">騰落率ヒートマップ</div>
  <div class="heatmap" id="heatmap"></div>
</div>

<div class="cards-section">
  <div class="cards-grid" id="cardsGrid"></div>
</div>

<script>
const STOCKS = {stocks_json};

// ── ヒートマップ ──────────────────────────────────────
function buildHeatmap() {{
  const container = document.getElementById('heatmap');
  STOCKS.forEach(s => {{
    const pct = s.change_pct;
    const absMax = 10;
    const intensity = Math.min(Math.abs(pct) / absMax, 1);
    let bg, color;
    if (pct > 0) {{
      const g = Math.round(80 + intensity * 117);
      bg = `rgba(34,${{g}},94,${{0.15 + intensity * 0.55}})`;
      color = `rgb(34,${{g}},94)`;
    }} else {{
      const r = Math.round(180 + intensity * 75);
      bg = `rgba(${{r}},68,68,${{0.15 + intensity * 0.55}})`;
      color = `rgb(${{r}},68,68)`;
    }}
    const cell = document.createElement('div');
    cell.className = 'heatmap-cell';
    cell.style.background = bg;
    cell.style.color = color;
    cell.innerHTML = `<span class="hm-ticker">${{s.ticker}}</span><span class="hm-pct">${{pct > 0 ? '+' : ''}}${{pct.toFixed(1)}}%</span>`;
    container.appendChild(cell);
  }});
}}

// ── RSIゲージ描画 ─────────────────────────────────────
function drawRSIGauge(canvas, rsi) {{
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const cx = w / 2, cy = h - 2, r = h - 6;
  const startAngle = Math.PI, endAngle = 0;

  // 背景弧
  ctx.beginPath();
  ctx.arc(cx, cy, r, startAngle, endAngle);
  ctx.strokeStyle = '#2a2a35';
  ctx.lineWidth = 5;
  ctx.stroke();

  // 値弧
  const angle = Math.PI + (rsi / 100) * Math.PI;
  let color = '#6b6b80';
  if (rsi >= 70) color = '#ef4444';
  else if (rsi <= 30) color = '#3b82f6';
  ctx.beginPath();
  ctx.arc(cx, cy, r, startAngle, angle);
  ctx.strokeStyle = color;
  ctx.lineWidth = 5;
  ctx.lineCap = 'round';
  ctx.stroke();
}}

// ── カード生成 ────────────────────────────────────────
function buildCards() {{
  const grid = document.getElementById('cardsGrid');
  STOCKS.forEach((s, idx) => {{
    const card = document.createElement('div');
    card.className = `card ${{s.status}}`;

    const updown = s.change >= 0 ? 'up' : 'down';
    const sign = s.change >= 0 ? '+' : '';
    const maIcon = s.ma_above ? '↑MA上' : '↓MA下';
    const maColor = s.ma_above ? '#22c55e' : '#ef4444';

    let badges = '';
    if (s.badge === 'GC') badges += `<span class="badge badge-gc">🌟 GC</span>`;
    if (s.badge === 'DC') badges += `<span class="badge badge-dc">💀 DC</span>`;
    if (s.vol_spike) badges += `<span class="badge-fire">🔥</span>`;

    const statusEmoji = s.status === 'bullish' ? '🟢' : s.status === 'bearish' ? '🔴' : '🟡';
    const statusLabel = s.status === 'bullish' ? '強気' : s.status === 'bearish' ? '弱気' : '中立';

    const rsiClass = s.rsi >= 70 ? 'rsi-hot' : s.rsi <= 30 ? 'rsi-cold' : 'rsi-normal';
    const rsiLabel = s.rsi >= 70 ? '過熱' : s.rsi <= 30 ? '売られ過ぎ' : '通常';

    const volRatio = s.vol_avg10 > 0 ? (s.volume / s.vol_avg10).toFixed(1) : '-';

    const newsHtml = s.news.map(n => {{
      const sc = n.sentiment === 'positive' ? 'sent-positive' : n.sentiment === 'negative' ? 'sent-negative' : 'sent-neutral';
      const sl = n.sentiment === 'positive' ? 'POS' : n.sentiment === 'negative' ? 'NEG' : 'NEU';
      return `<div class="news-item"><span class="news-sentiment ${{sc}}">${{sl}}</span><span class="news-text">${{n.title}}</span></div>`;
    }}).join('');

    card.innerHTML = `
      <div class="card-header">
        <div class="card-title">
          <span class="card-ticker">${{s.ticker}}</span>
          <span class="card-name">${{s.name}}</span>
        </div>
        <div class="card-badges">
          ${{badges}}
          <span class="badge badge-status">${{statusEmoji}} ${{statusLabel}}</span>
          <span class="ma-indicator" style="color:${{maColor}}">${{maIcon}}</span>
        </div>
      </div>
      <div class="price-area">
        <span class="price">$${{s.current.toLocaleString()}}</span>
        <span class="change ${{updown}}">${{sign}}${{s.change}} (${{sign}}${{s.change_pct}}%)</span>
      </div>
      <div class="rsi-area">
        <div class="rsi-gauge-wrap">
          <canvas id="rsi-${{idx}}" width="64" height="36"></canvas>
          <span class="rsi-val">${{s.rsi}}</span>
        </div>
        <div class="rsi-info">
          <span class="rsi-label">RSI 14</span>
          <span class="rsi-status ${{rsiClass}}">${{rsiLabel}}</span>
        </div>
        <div class="metrics" style="margin-left:auto">
          <div class="metric">
            <span class="metric-label">出来高比</span>
            <span class="metric-value" style="color:${{s.vol_spike ? '#f59e0b' : 'inherit'}}">${{volRatio}}x</span>
          </div>
          <div class="metric">
            <span class="metric-label">MACD</span>
            <span class="metric-value" style="color:${{s.hist_val >= 0 ? '#22c55e' : '#ef4444'}}">${{s.hist_val > 0 ? '+' : ''}}${{s.hist_val}}</span>
          </div>
        </div>
      </div>
      <div class="chart-label">価格 / MA25 / MA75</div>
      <div class="chart-wrap"><canvas id="price-${{idx}}"></canvas></div>
      <div class="chart-label">MACD</div>
      <div class="macd-wrap"><canvas id="macd-${{idx}}"></canvas></div>
      ${{s.news.length > 0 ? `<div class="news-section"><div class="news-title">最新ニュース</div>${{newsHtml}}</div>` : ''}}
    `;
    grid.appendChild(card);
  }});

  // チャート描画
  STOCKS.forEach((s, idx) => {{
    drawRSIGauge(document.getElementById(`rsi-${{idx}}`), s.rsi);
    drawPriceChart(idx, s);
    drawMACDChart(idx, s);
  }});
}}

function drawPriceChart(idx, s) {{
  const ctx = document.getElementById(`price-${{idx}}`).getContext('2d');
  const labels = s.chart_dates;

  // クロスマーカー用ポイント配列
  const gcPoints = s.chart_close.map((v, i) => {{
    const m = s.cross_markers.find(c => c.idx === i && c.type === 'GC');
    return m ? v : null;
  }});
  const dcPoints = s.chart_close.map((v, i) => {{
    const m = s.cross_markers.find(c => c.idx === i && c.type === 'DC');
    return m ? v : null;
  }});

  new Chart(ctx, {{
    type: 'line',
    data: {{
      labels,
      datasets: [
        {{
          label: '価格', data: s.chart_close,
          borderColor: '#6b7cff', borderWidth: 1.5, pointRadius: 0, tension: 0.3,
          fill: {{ target: 'origin', above: 'rgba(107,124,255,0.04)' }}
        }},
        {{
          label: 'MA25', data: s.chart_ma25,
          borderColor: '#f59e0b', borderWidth: 1, pointRadius: 0, tension: 0.3,
          borderDash: []
        }},
        {{
          label: 'MA75', data: s.chart_ma75,
          borderColor: '#a855f7', borderWidth: 1, pointRadius: 0, tension: 0.3,
          borderDash: [4, 3]
        }},
        {{
          label: 'GC', data: gcPoints,
          borderColor: 'transparent', backgroundColor: '#f59e0b',
          pointRadius: 6, pointStyle: 'triangle', showLine: false
        }},
        {{
          label: 'DC', data: dcPoints,
          borderColor: 'transparent', backgroundColor: '#9ca3af',
          pointRadius: 6, pointStyle: 'triangle', rotation: 180, showLine: false
        }},
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: {{
        legend: {{ display: false }},
        annotation: {{}}
      }},
      scales: {{
        x: {{ display: false }},
        y: {{
          display: true, position: 'right',
          grid: {{ color: '#1e1e24' }},
          ticks: {{ color: '#6b6b80', font: {{ size: 9 }}, maxTicksLimit: 4,
            callback: v => '$' + v.toLocaleString() }}
        }}
      }}
    }}
  }});
}}

function drawMACDChart(idx, s) {{
  const ctx = document.getElementById(`macd-${{idx}}`).getContext('2d');
  const histColors = s.chart_hist.map(v => v >= 0 ? 'rgba(34,197,94,0.7)' : 'rgba(239,68,68,0.7)');

  new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: s.chart_dates,
      datasets: [
        {{
          type: 'bar', label: 'Histogram', data: s.chart_hist,
          backgroundColor: histColors, borderWidth: 0
        }},
        {{
          type: 'line', label: 'MACD', data: s.chart_macd,
          borderColor: '#3b82f6', borderWidth: 1.2, pointRadius: 0, tension: 0.3
        }},
        {{
          type: 'line', label: 'Signal', data: s.chart_signal,
          borderColor: '#f59e0b', borderWidth: 1, pointRadius: 0, tension: 0.3,
          borderDash: [3, 2]
        }},
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{
        x: {{ display: false }},
        y: {{ display: false }}
      }}
    }}
  }});
}}

// ── 初期化 ────────────────────────────────────────────
buildHeatmap();
buildCards();
</script>
</body>
</html>"""

if __name__ == "__main__":
    main()
