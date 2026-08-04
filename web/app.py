"""web/app.py

CryptoBrain dashboard — a single-page Flask app showing the live brain output:
best signal, multi-condition plans, feature snapshot, score breakdown, and
market context. No frontend build step; inline CSS/JS only.

Endpoints
  GET /            dashboard HTML
  GET /api/scan    JSON brain output for ?symbol=&tf=
  GET /api/health  health check
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, jsonify, render_template_string, request

from config import SYMBOL, TIMEFRAME, BARS, MIN_CONFIDENCE, DEFAULT_RISK_REWARD, DASHBOARD_HOST, DASHBOARD_PORT
from data.binance_client import BinanceClient
from engine.signal_engine import analyze_frame
from output.signal_schema import validate_output

_CACHE: dict = {"payload": None, "ts": 0, "ttl": 45}


def build_payload(symbol: str, tf: str) -> dict:
    now = time.time()
    if _CACHE["payload"] and _CACHE["payload"].get("signal", {}).get("asset") == symbol \
            and now - _CACHE["ts"] < _CACHE["ttl"]:
        return _CACHE["payload"]
    client = BinanceClient()
    df = client.klines(symbol, tf, BARS)
    out = analyze_frame(df, symbol=symbol, timeframe=tf,
                        min_confidence=MIN_CONFIDENCE, default_rr=DEFAULT_RISK_REWARD)
    payload = out.as_json()
    payload["market_context"] = client.market_context(symbol)
    payload["validation"] = validate_output(payload)
    _CACHE.update(payload=payload, ts=now)
    return payload


HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CryptoBrain — AI Trading Brain</title>
<style>
  :root{--bg:#0b0f17;--card:#131a26;--line:#223045;--txt:#e6edf7;--mut:#8aa0bd;
        --green:#22c55e;--red:#ef4444;--amber:#f59e0b;--blue:#3b82f6}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--txt);
      font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;padding:24px}
  h1{font-size:20px;margin:0 0 4px} .sub{color:var(--mut);margin-bottom:20px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
  .card h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin:0 0 12px}
  .sig{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px}
  .pill{padding:4px 10px;border-radius:999px;font-weight:700;font-size:13px}
  .BUY{background:rgba(34,197,94,.15);color:var(--green);border:1px solid var(--green)}
  .SELL{background:rgba(239,68,68,.15);color:var(--red);border:1px solid var(--red)}
  .NOTRADE{background:rgba(139,160,189,.12);color:var(--mut)}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
  th{color:var(--mut);font-weight:500}
  .kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:13px}
  .kv b{color:var(--mut);font-weight:500}
  .plan{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-bottom:10px}
  .plan .h{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}
  .plan .c{color:var(--mut);margin-top:6px;font-size:12.5px}
  .badge{font-size:11px;padding:2px 8px;border-radius:6px;background:var(--line)}
  .bar{height:6px;border-radius:6px;background:#1b2740;margin-top:8px;overflow:hidden}
  .bar i{display:block;height:100%}
  .muted{color:var(--mut)} .mono{font-variant-numeric:tabular-nums}
  .rowbtn{background:var(--blue);border:none;color:#fff;padding:6px 12px;border-radius:8px;cursor:pointer;font:inherit}
  .rowbtn:hover{opacity:.9} input,select{background:#0e1524;border:1px solid var(--line);color:var(--txt);
      padding:6px 8px;border-radius:8px;font:inherit}
  .flex{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .ok{color:var(--green)} .err{color:var(--red)}
  #updated{color:var(--mut);font-size:12px}
</style></head><body>
<h1>🧠 CryptoBrain — AI Trading Brain</h1>
<div class="sub">multi-source indicator + structure + scoring engine · signals are risk-advice only</div>
<div class="flex" style="margin-bottom:18px">
  <input id="sym" value="{{symbol}}" size="10">
  <select id="tf">
    {% for t in ['1m','5m','15m','30m','1h','4h','1d'] %}<option value="{{t}}" {{'selected' if t==tf}}>{{t}}</option>{% endfor %}
  </select>
  <button class="rowbtn" onclick="load()">Scan</button>
  <span id="updated"></span>
</div>
<div id="app">Loading…</div>
<script>
async function load(){
  const sym=document.getElementById('sym').value.trim().toUpperCase()||'BTCUSDT';
  const tf=document.getElementById('tf').value;
  document.getElementById('app').innerHTML='Scanning…';
  try{
    const r=await fetch(`/api/scan?symbol=${sym}&tf=${tf}`);
    const d=await r.json();
    render(d); document.getElementById('updated').textContent=
      'updated ' + new Date().toLocaleTimeString();
  }catch(e){ document.getElementById('app').innerHTML='<div class="err">Error: '+e+'</div>'; }
}
const fmt=(v,n=2)=> v==null?'—':Number(v).toLocaleString(undefined,{minimumFractionDigits:n,maximumFractionDigits:n});
const cls=a=> a==='BUY'?'BUY':a==='SELL'?'SELL':'NOTRADE';
function render(d){
  const s=d.signal||{}, plans=d.plans||[], snap=d.snapshot||{};
  const f=snap.features||{}, sc=snap.scores||{}, ctx=d.market_context||{};
  const cf=sc.bull?.score??0, cs=sc.bear?.score??0;
  let html='';
  html+=`<div class="card" style="grid-column:1/-1">
    <div class="sig"><span class="pill ${cls(s.action)}">${s.action}</span>
      <b>${s.asset} · ${s.timeframe}</b>
      <span class="badge">${s.signal_id||''}</span>
      <span class="badge">${s.confidence}</span>
      ${s.risk_reward?`<span class="badge">RR ${s.risk_reward}</span>`:''}</div>
    <div class="kv" style="margin-bottom:10px">
      <b>Entry</b><span class="mono">${fmt(s.entry)}</span>
      <b>Stop loss</b><span class="mono">${fmt(s.stop_loss)}</span>
      <b>Take profit</b><span class="mono">${fmt(s.take_profit)}</span>
      <b>Reason</b><span>${s.reason||''}</span>
    </div>
    <div class="kv">
      <b>Funding</b><span>${ctx.funding_rate_pct!=null?ctx.funding_rate_pct+'%':'n/a (futures geo-blocked here)'}</span>
      <b>Open interest</b><span>${ctx.open_interest!=null?fmt(ctx.open_interest,0):'n/a'}</span>
      <b>L/S ratio</b><span>${ctx.long_short_ratio??'n/a'}</span>
      <b>24h change</b><span>${ctx.liq_24h_change_pct!=null?ctx.liq_24h_change_pct+'%':'n/a'}</span>
    </div></div>`;

  html+=`<div class="card"><h2>Conditional plans (${plans.length})</h2>`;
  if(!plans.length) html+=`<div class="muted">No plans — scores below threshold.</div>`;
  for(const p of plans){
    html+=`<div class="plan"><div class="h">
      <b class="${cls(p.action)}">${p.action} · ${p.type}</b>
      <span class="badge">${p.confidence}% ${p.confidence_label}</span></div>
      <div class="bar"><i style="width:${p.confidence}%;background:${p.confidence>=80?'var(--green)':p.confidence>=60?'var(--amber)':'var(--red)'}"></i></div>
      <div class="c">${p.condition}</div>
      <div class="c mono">entry ${fmt(p.entry)} · sl ${fmt(p.stop_loss)} · tp ${p.take_profits.map(fmt).join(', ')} · RR ${p.risk_reward}</div></div>`;
  }
  html+='</div>';

  const kvs=[
    ['Trend', f.trend, null], ['EMA stack', f.ema_alignment_bull?'Bullish aligned':f.ema_alignment_bear?'Bearish aligned':'mixed', null],
    ['Supertrend', f.supertrend_bull?'Bull':'Bear', null], ['ADX', fmt(f.adx,1), null],
    ['RSI', fmt(f.rsi,1), null], ['RSI div (bull/bear)', `${f.rsi_divergence?.bull??0}/${f.rsi_divergence?.bear??0}`, null],
    ['MACD hist', fmt(f.macd_hist,4), null], ['WaveTrend', `${fmt(f.wt1,2)} / ${fmt(f.wt2,2)}`, null],
    ['Volume ratio', fmt(f.volume_ratio,2), null], ['vs VWAP', f.above_vwap?'above':'below', null],
    ['Structure event', f.event_kind||'—', null], ['Bias', f.trend_bias, null],
    ['Bullish OB near', fmt(f.nearest_bull_ob), null], ['Bearish OB near', fmt(f.nearest_bear_ob), null],
    ['FVG bull/bear', `${f.fvg_bull_count}/${f.fvg_bear_count}`, null],
    ['Premium/Discount', f.premium_discount, null], ['ATR %', fmt(f.atr_pct,3), null],
    ['Sweep', f.sweep?`${f.sweep.side} @ ${fmt(f.sweep.level)}`:'none', null],
  ];
  html+=`<div class="card"><h2>Feature snapshot</h2><div class="kv">`+
    kvs.map(([k,v])=>`<b>${k}</b><span>${v}</span>`).join('')+`</div></div>`;

  html+=`<div class="card"><h2>Score breakdown</h2>
    <table><tr><th>Condition</th><th>Bull</th><th>Bear</th></tr>`;
  const bullC=sc.bull?.conditions||{}, bearC=sc.bear?.conditions||{};
  for(const k of Object.keys({...bullC,...bearC})){
    html+=`<tr><td>${k}</td><td>${bullC[k]??0}</td><td>${bearC[k]??0}</td></tr>`;
  }
  html+=`<tr><td><b>Total</b></td><td><b>${cf}</b></td><td><b>${cs}</b></td></tr></table>
    <div class="muted" style="margin-top:8px">${(sc.bull?.reasons||[]).concat(sc.bear?.reasons||[]).slice(0,6).map(r=>'• '+r).join('<br>')}</div></div>`;

  html+=`<div class="card" style="grid-column:1/-1"><h2>LLM / narrative & raw JSON</h2>
    <div id="llm" class="muted" style="white-space:pre-wrap">${(d.llm?.narrative||'').replace(/</g,'&lt;')||'Enable LLM_PROVIDER in .env for an AI narrative, or use the rule-based output.'}</div>
    <details style="margin-top:10px"><summary>show raw JSON</summary>
    <pre style="max-height:420px;overflow:auto;font-size:11px">${JSON.stringify(d,null,2).replace(/</g,'&lt;')}</pre></details></div>`;
  document.getElementById('app').innerHTML=`<div class="grid">${html}</div>`;
}
load(); setInterval(load, 45000);
</script></body></html>
"""


def make_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template_string(HTML, symbol=SYMBOL, tf=TIMEFRAME)

    @app.get("/api/scan")
    def api_scan():
        symbol = request.args.get("symbol", SYMBOL).upper()
        tf = request.args.get("tf", TIMEFRAME)
        try:
            return jsonify(build_payload(symbol, tf))
        except ConnectionError as exc:
            return jsonify({"error": str(exc)}), 502
        except Exception as exc:  # pragma: no cover
            return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True})

    return app


def serve(app: Flask, host: str = DASHBOARD_HOST, port: int = DASHBOARD_PORT) -> None:
    app.run(host=host, port=port, debug=False, threaded=True)
