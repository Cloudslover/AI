"""web/app.py

CryptoBrain — all-in-one dashboard ("watch everything, click to decide").

One page shows:
  • live signal + lifecycle badge + approve/reject/execute/close buttons
  • multi-condition plans with confidence bars
  • market context (funding / OI / L/S)
  • full feature snapshot + score breakdown
  • human approval queue (clickable Approve / Reject)
  • recent signal history (click a row → detail modal, decide from there)
  • learning dashboard (backtest win-rates + calibration profile)
  • coach panel (explain / mentor / personal feedback)
  • LLM narrative + raw JSON

Endpoints
  GET /             dashboard HTML
  GET /api/scan     live brain output (persisted, deduped by signal_id)
  GET /api/pending  signals awaiting human approval
  POST /api/review  approve/reject/execute/close a signal
  GET /api/history  recent scans with lifecycle status
  GET /api/signal   full detail + plans + decision trail for one scan
  GET /api/learning backtest stats + calibration profile + plan distribution
  GET /api/coach    explain + mentor + personal feedback
  GET /api/health   health check
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, jsonify, render_template_string, request

from config import SYMBOL, TIMEFRAME, BARS, MIN_CONFIDENCE, DEFAULT_RISK_REWARD, DASHBOARD_HOST, DASHBOARD_PORT
from data.binance_client import BinanceClient
from engine.signal_engine import analyze_frame
from output.signal_schema import validate_output

_CACHE: dict = {"payload": None, "ts": 0, "ttl": 40}


def _persist(payload: dict) -> tuple[int, str]:
    """Save the scan to the learning DB (deduped by signal_id) and return
    (scan_id, lifecycle_status)."""
    from data.database import SignalDB
    from engine.lifecycle import reviewable
    sig = payload.get("signal", {})
    with SignalDB() as db:
        existing = db.conn.execute(
            "SELECT id, status FROM scans WHERE signal_id=?", (sig.get("signal_id"),)
        ).fetchone()
        if existing:
            scan_id, status = existing["id"], existing["status"]
        else:
            scan_id = db.save_scan(payload)
            status = "PENDING_REVIEW" if reviewable(sig) else "CREATED"
    payload["scan_id"] = scan_id
    payload["lifecycle"] = {
        "status": status,
        "note": ("awaiting human approval — click Approve / Reject"
                 if status == "PENDING_REVIEW" else
                 "monitor-only signal (no action required)" if status == "CREATED" else
                 f"current state: {status}"),
    }
    return scan_id, status


def compute_payload(symbol: str, tf: str, save: bool = True, use_cache: bool = True) -> dict:
    if use_cache and _CACHE["payload"] and _CACHE["payload"].get("signal", {}).get("asset") == symbol \
            and time.time() - _CACHE["ts"] < _CACHE["ttl"]:
        return _CACHE["payload"]
    client = BinanceClient()
    df = client.klines(symbol, tf, BARS)
    calib = {}
    try:
        from data.database import SignalDB
        with SignalDB() as db:
            calib = db.load_calibration()
    except Exception:
        pass
    out = analyze_frame(df, symbol=symbol, timeframe=tf,
                        min_confidence=MIN_CONFIDENCE, default_rr=DEFAULT_RISK_REWARD,
                        calibration=calib)
    payload = out.as_json()
    payload["market_context"] = client.market_context(symbol)
    payload["validation"] = validate_output(payload)
    if save:
        _persist(payload)
    _CACHE.update(payload=payload, ts=time.time())
    return payload


def build_payload(symbol: str, tf: str) -> dict:
    return compute_payload(symbol, tf, save=True, use_cache=True)


HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CryptoBrain — All-in-One</title>
<style>
  :root{--bg:#0b0f17;--card:#131a26;--line:#223045;--txt:#e6edf7;--mut:#8aa0bd;
        --green:#22c55e;--red:#ef4444;--amber:#f59e0b;--blue:#3b82f6}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--txt);
      font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;padding:22px}
  h1{font-size:19px;margin:0} .sub{color:var(--mut);font-size:13px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(350px,1fr));gap:14px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
  .card h2{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin:0 0 10px}
  .pill{padding:3px 10px;border-radius:999px;font-weight:700;font-size:13px}
  .BUY{background:rgba(34,197,94,.15);color:var(--green);border:1px solid var(--green)}
  .SELL{background:rgba(239,68,68,.15);color:var(--red);border:1px solid var(--red)}
  .NOTRADE{background:rgba(139,160,189,.12);color:var(--mut)}
  .badge{font-size:11px;padding:2px 8px;border-radius:6px;background:var(--line);border:1px solid transparent}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th,td{text-align:left;padding:5px 7px;border-bottom:1px solid var(--line)}
  th{color:var(--mut);font-weight:500}
  .kv{display:grid;grid-template-columns:auto 1fr;gap:3px 12px;font-size:12.5px}
  .kv b{color:var(--mut);font-weight:500}
  .plan{border:1px solid var(--line);border-radius:10px;padding:9px 11px;margin-bottom:9px}
  .plan .h{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}
  .plan .c{color:var(--mut);margin-top:5px;font-size:12px}
  .bar{height:6px;border-radius:6px;background:#1b2740;margin-top:7px;overflow:hidden}
  .bar i{display:block;height:100%}
  .rowbtn{background:var(--blue);border:none;color:#fff;padding:5px 10px;border-radius:8px;cursor:pointer;font:inherit;font-size:12px}
  .rowbtn:hover{opacity:.9}
  .ok{background:rgba(34,197,94,.9);color:#04120a} .no{background:rgba(239,68,68,.9);color:#fff}
  input,select,textarea{background:#0e1524;border:1px solid var(--line);color:var(--txt);padding:6px 8px;border-radius:8px;font:inherit}
  .flex{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .muted{color:var(--mut)} .mono{font-variant-numeric:tabular-nums}
  .row{display:flex;justify-content:space-between;gap:10px;align-items:center;padding:6px 4px;border-bottom:1px solid var(--line);cursor:pointer;flex-wrap:wrap}
  .row:hover{background:#0e1524}
  .row .btns{display:flex;gap:6px}
  #modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:50;padding:30px;overflow:auto}
  #modal .box{background:var(--card);border:1px solid var(--line);border-radius:14px;max-width:760px;margin:auto;padding:20px}
  .err{color:var(--red)} .okc{color:var(--green)}
  .note{font-size:11px;color:var(--mut)}
</style></head><body>
<div class="flex" style="justify-content:space-between;margin-bottom:16px">
  <div><h1>🧠 CryptoBrain — All-in-One</h1>
  <div class="sub">watch everything · click to approve · the engine learns from you</div></div>
  <div class="flex">
    <input id="sym" value="{{symbol}}" size="10">
    <select id="tf">
      {% for t in ['1m','5m','15m','30m','1h','4h','1d'] %}<option value="{{t}}" {{'selected' if t==tf}}>{{t}}</option>{% endfor %}
    </select>
    <button class="rowbtn" onclick="load(true)">Refresh</button>
    <label class="note"><input type="checkbox" id="auto" checked> auto</label>
    <span id="updated" class="note"></span>
  </div>
</div>
<div id="app" class="grid">Loading…</div>
<div id="modal"><div class="box" id="mbody"></div></div>

<script>
const fmt=(v,n=2)=> v==null?'—':Number(v).toLocaleString(undefined,{minimumFractionDigits:n,maximumFractionDigits:n});
const cls=a=> a==='BUY'?'BUY':a==='SELL'?'SELL':'NOTRADE';
const stCls=s=> s==='APPROVED'?'var(--green)':s==='REJECTED'?'var(--red)':s==='EXECUTED'?'var(--blue)':s==='CLOSED'?'var(--amber)':'var(--amber)';
const esc=x=> String(x??'').replace(/&/g,'&amp;').replace(/</g,'&lt;');

function card(title, inner, span){ return `<div class="card" ${span?'style="grid-column:1/-1"':''}><h2>${title}</h2>${inner}</div>`; }

function render(d){
  const s=d.signal||{}, plans=d.plans||[], snap=d.snapshot||{}, f=snap.features||{}, sc=snap.scores||{}, ctx=d.market_context||{}, lc=d.lifecycle||{};
  const cf=sc.bull?.score??0, cs=sc.bear?.score??0;
  const sid=d.scan_id, st=lc.status||'';
  const decideBtns = st==='PENDING_REVIEW'
    ? `<div class="flex" style="margin-top:8px">
         <input id="note-${sid}" placeholder="note (optional)" style="flex:1">
         <button class="rowbtn ok" onclick="decide(${sid},'APPROVED')">✓ Approve</button>
         <button class="rowbtn no" onclick="decide(${sid},'REJECTED')">✗ Reject</button></div>`
    : (st==='APPROVED' ? `<div class="flex" style="margin-top:8px">
         <button class="rowbtn" onclick="decide(${sid},'EXECUTED')">▶ Mark executed</button>
         <button class="rowbtn no" onclick="decide(${sid},'SKIPPED')">Skip</button></div>`
       : (st==='EXECUTED' ? `<button class="rowbtn" style="background:var(--amber)" onclick="decide(${sid},'CLOSED')">✔ Close (record outcome)</button>` : ''));

  let html = card('LIVE SIGNAL', `
    <div class="flex" style="margin-bottom:6px">
      <span class="pill ${cls(s.action)}">${s.action}</span>
      <b>${s.asset} · ${s.timeframe}</b>
      <span class="badge">${s.signal_id||''}</span>
      <span class="badge">${s.confidence}</span>
      ${s.risk_reward?`<span class="badge">RR ${s.risk_reward}</span>`:''}
      <span class="badge" style="background:${stCls(st)}22;border-color:${stCls(st)}">${st||'—'}</span>
    </div>
    <div class="kv">
      <b>Entry</b><span class="mono">${fmt(s.entry)}</span>
      <b>Stop loss</b><span class="mono">${fmt(s.stop_loss)}</span>
      <b>Take profit</b><span class="mono">${fmt(s.take_profit)}</span>
      <b>Reason</b><span>${esc(s.reason)}</span>
      <b>Note</b><span>${esc(lc.note||'')}</span>
    </div>${decideBtns}`, true);

  html += card(`CONDITIONAL PLANS (${plans.length})`,
    plans.length ? plans.map(p=>`<div class="plan"><div class="h">
        <b class="${cls(p.action)}">${p.action} · ${p.type}</b>
        <span class="badge">${p.confidence}% ${p.confidence_label}</span></div>
        <div class="bar"><i style="width:${p.confidence}%;background:${p.confidence>=80?'var(--green)':p.confidence>=60?'var(--amber)':'var(--red)'}"></i></div>
        <div class="c">${esc(p.condition)}</div>
        <div class="c mono">entry ${fmt(p.entry)} · sl ${fmt(p.stop_loss)} · tp ${p.take_profits.map(fmt).join(', ')} · RR ${p.risk_reward}</div></div>`).join('')
      : '<div class="muted">No plans above threshold — best trade is no trade.</div>');

  const kvs=[
    ['Trend', f.trend, null], ['EMA stack', f.ema_alignment_bull?'Bull aligned':f.ema_alignment_bear?'Bear aligned':'mixed'],
    ['Supertrend', f.supertrend_bull?'Bull':'Bear'], ['ADX', fmt(f.adx,1)],
    ['RSI', fmt(f.rsi,1)], ['RSI div bull/bear', `${f.rsi_divergence?.bull??0}/${f.rsi_divergence?.bear??0}`],
    ['MACD hist', fmt(f.macd_hist,4)], ['WaveTrend', `${fmt(f.wt1,2)}/${fmt(f.wt2,2)}`],
    ['Volume ratio', fmt(f.volume_ratio,2)], ['vs VWAP', f.above_vwap?'above':'below'],
    ['Structure event', f.event_kind||'—'], ['Bias', f.trend_bias],
    ['Bull OB near', fmt(f.nearest_bull_ob)], ['Bear OB near', fmt(f.nearest_bear_ob)],
    ['FVG bull/bear', `${f.fvg_bull_count}/${f.fvg_bear_count}`],
    ['Premium/Discount', f.premium_discount], ['ATR %', fmt(f.atr_pct,3)],
    ['Sweep', f.sweep?`${f.sweep.side} @ ${fmt(f.sweep.level)}`:'none'],
  ];
  html += card('FEATURE SNAPSHOT', `<div class="kv">${kvs.map(([k,v])=>`<b>${k}</b><span>${v}</span>`).join('')}</div>`);

  html += card('SCORE BREAKDOWN', `<table><tr><th>Condition</th><th>Bull</th><th>Bear</th></tr>${
    [...new Set([...Object.keys(sc.bull?.conditions||{}),...Object.keys(sc.bear?.conditions||{})])]
      .map(k=>`<tr><td>${k}</td><td>${sc.bull?.conditions?.[k]??0}</td><td>${sc.bear?.conditions?.[k]??0}</td></tr>`).join('')
    }<tr><td><b>Total</b></td><td><b>${cf}</b></td><td><b>${cs}</b></td></tr></table>
    <div class="muted" style="margin-top:6px">${(sc.bull?.reasons||[]).concat(sc.bear?.reasons||[]).slice(0,6).map(r=>'• '+esc(r)).join('<br>')}</div>`);

  html += card('MARKET CONTEXT', `<div class="kv">
    <b>Funding</b><span>${ctx.funding_rate_pct!=null?ctx.funding_rate_pct+'%':'n/a'}</span>
    <b>Open interest</b><span>${ctx.open_interest!=null?fmt(ctx.open_interest,0):'n/a'}</span>
    <b>L/S ratio</b><span>${ctx.long_short_ratio??'n/a'}</span>
    <b>24h change</b><span>${ctx.liq_24h_change_pct!=null?ctx.liq_24h_change_pct+'%':'n/a'}</span>
    <b>Futures</b><span>${ctx.futures?'available':'geo-blocked from this network'}</span>
  </div>`);

  html += card('HUMAN APPROVAL QUEUE', '<div id="queue">loading…</div>');
  html += card('RECENT SIGNALS', '<div id="hist">loading…</div>');
  html += card('LEARNING — backtest & calibration', '<div id="learn">loading…</div>', true);
  html += card('🧑‍🏫 COACH', `<button class="rowbtn" onclick="coach()">Explain & mentor me</button>
    <div id="coach" class="muted" style="white-space:pre-wrap;margin-top:10px"></div>`, true);
  html += card('LLM NARRATIVE', `<div class="muted" style="white-space:pre-wrap">${esc(d.llm?.narrative)||'Enable LLM_PROVIDER in .env, or use rule-based output.'}</div>`);
  html += card('RAW JSON', `<details><summary>show</summary><pre style="max-height:380px;overflow:auto;font-size:11px">${esc(JSON.stringify(d,null,2))}</pre></details>`);

  document.getElementById('app').innerHTML = html;
  loadPending(); loadHistory(); loadLearning();
}

async function load(force){
  const sym=document.getElementById('sym').value.trim().toUpperCase()||'BTCUSDT';
  const tf=document.getElementById('tf').value;
  try{
    const r=await fetch(`/api/scan?symbol=${sym}&tf=${tf}`+(force?'&force=1':''));
    const d=await r.json();
    if(d.error){ document.getElementById('app').innerHTML='<div class="err">'+esc(d.error)+'</div>'; return; }
    render(d); document.getElementById('updated').textContent='updated '+new Date().toLocaleTimeString();
  }catch(e){ document.getElementById('app').innerHTML='<div class="err">Error: '+esc(e)+'</div>'; }
}

async function loadPending(){
  try{
    const d=await (await fetch('/api/pending')).json();
    const el=document.getElementById('queue'); if(!el) return;
    const q=d.pending||[];
    if(!q.length){ el.innerHTML='<span class="muted">All caught up — no signals waiting 🎉</span>'; return; }
    el.innerHTML=q.map(x=>`<div class="row">
      <span onclick="openModal(${x.id})">#${x.id} <b>${x.symbol}</b> ${x.timeframe} <span class="${cls(x.action)}">${x.action}</span> ${fmt(x.entry)} <span class="note">${esc((x.reason||'').slice(0,50))}</span></span>
      <span class="btns">
        <button class="rowbtn ok" onclick="decide(${x.id},'APPROVED')">✓</button>
        <button class="rowbtn no" onclick="decide(${x.id},'REJECTED')">✗</button>
        <button class="rowbtn" onclick="openModal(${x.id})">🔍</button>
      </span></div>`).join('');
  }catch(e){ const el=document.getElementById('queue'); if(el) el.innerHTML='<span class="err">'+esc(e)+'</span>'; }
}

async function loadHistory(){
  try{
    const d=await (await fetch('/api/history')).json();
    const el=document.getElementById('hist'); if(!el) return;
    const h=d.history||[];
    if(!h.length){ el.innerHTML='<span class="muted">No scans yet.</span>'; return; }
    el.innerHTML=h.map(x=>`<div class="row">
      <span onclick="openModal(${x.id})">#${x.id} <b>${x.symbol}</b> ${x.timeframe} <span class="${cls(x.action)}">${x.action}</span> ${x.confidence_label} @ ${fmt(x.entry)}</span>
      <span class="flex"><span class="badge" style="background:${stCls(x.status)}22;border-color:${stCls(x.status)}">${x.status}</span>
      ${x.status==='PENDING_REVIEW'?`<span class="btns"><button class="rowbtn ok" onclick="decide(${x.id},'APPROVED')">✓</button><button class="rowbtn no" onclick="decide(${x.id},'REJECTED')">✗</button></span>`:''}</span>
    </div>`).join('');
  }catch(e){ const el=document.getElementById('hist'); if(el) el.innerHTML='<span class="err">'+esc(e)+'</span>'; }
}

async function loadLearning(){
  try{
    const d=await (await fetch('/api/learning')).json();
    const el=document.getElementById('learn'); if(!el) return;
    const bt=d.backtest||{}, cal=d.calibration||{};
    let html='';
    const o=bt.overall||{};
    if(o.n){
      html+=`<div class="kv" style="margin-bottom:8px"><b>Graded</b><span>${o.n} plans</span>
        <b>Win-rate</b><span>${o.win_rate!=null?(o.win_rate*100).toFixed(1)+'%':'n/a'}</span>
        <b>Avg R</b><span>${o.avg_rr}</span><b>Wins/Losses</b><span>${o.wins}/${o.losses}</span></div>`;
      html+=`<table><tr><th>Plan type</th><th>n</th><th>Win%</th><th>AvgR</th></tr>`+
        (bt.by_type||[]).map(r=>`<tr><td>${esc(r.plan_type)}</td><td>${r.n}</td><td>${r.win_rate!=null?(r.win_rate*100).toFixed(0)+'%':'—'}</td><td>${r.avg_rr}</td></tr>`).join('')+`</table>`;
    } else {
      html+=`<span class="muted">No backtest data yet — run <code>python main.py backtest --save</code> then <code>python main.py learn</code>.</span>`;
    }
    const entries=Object.entries(cal||{});
    if(entries.length){
      html+=`<div style="margin-top:10px"><b>Calibration (applied to future signals)</b><table><tr><th>Plan</th><th>Mult</th><th>Exp R</th><th>Samples</th></tr>`+
        entries.map(([k,v])=>`<tr><td>${esc(k)}</td><td>${v.filtered?'<span class="err">FILTERED</span>':'×'+v.multiplier}</td><td>${v.expectancy!=null?v.expectancy.toFixed(2):'—'}</td><td>${v.samples}</td></tr>`).join('')+`</table></div>`;
    }
    el.innerHTML=html;
  }catch(e){ const el=document.getElementById('learn'); if(el) el.innerHTML='<span class="err">'+esc(e)+'</span>'; }
}

async function decide(id, decision, note){
  const n=document.getElementById('note-'+id); const noteTxt=(n&&n.value)||'';
  await fetch('/api/review',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({scan_id:id,decision:decision,note:noteTxt})});
  load(true); closeModal();
}

async function openModal(id){
  try{
    const d=await (await fetch('/api/signal?id='+id)).json();
    const s=d.scan||{}, plans=d.plans||[], decs=d.decisions||[];
    document.getElementById('mbody').innerHTML=`
      <div class="flex" style="justify-content:space-between"><h2 style="margin:0">Signal #${s.id} — ${s.symbol} ${s.timeframe} <span class="pill ${cls(s.action)}">${s.action}</span></h2>
      <button class="rowbtn" onclick="closeModal()">✕</button></div>
      <div class="kv" style="margin-top:12px">
        <b>Status</b><span>${s.status}</span><b>Confidence</b><span>${s.confidence_label}</span>
        <b>Entry</b><span class="mono">${fmt(s.entry)}</span><b>SL</b><span class="mono">${fmt(s.stop_loss)}</span>
        <b>TP</b><span class="mono">${fmt(s.take_profit)}</span><b>RR</b><span>${s.risk_reward}</span>
        <b>Created</b><span>${s.created_at||''}</span><b>Reason</b><span>${esc(s.reason)}</span>
      </div>
      <h3 style="margin:14px 0 6px">Lifecycle trail</h3>
      ${decs.length?decs.map(x=>`<div class="muted">${x.from_state} → <b>${x.to_state}</b> by ${x.reviewer} <span class="note">${esc(x.note||'')}</span></div>`).join(''):'<span class="muted">no decisions yet</span>'}
      <h3 style="margin:14px 0 6px">Plans</h3>
      ${plans.length?plans.map(p=>`<div class="plan"><div class="h"><b>${p.type}</b><span class="badge">${p.confidence}%</span></div><div class="c">${esc(p.condition)}</div><div class="c mono">entry ${fmt(p.entry)} · sl ${fmt(p.stop_loss)} · tp ${p.take_profits.map(fmt).join(', ')} · RR ${p.risk_reward}</div></div>`).join(''):'<span class="muted">none</span>'}
      <div class="flex" style="margin-top:12px">
        ${s.status==='PENDING_REVIEW'?`<button class="rowbtn ok" onclick="decide(${s.id},'APPROVED')">✓ Approve</button><button class="rowbtn no" onclick="decide(${s.id},'REJECTED')">✗ Reject</button>`:''}
        ${s.status==='APPROVED'?`<button class="rowbtn" onclick="decide(${s.id},'EXECUTED')">▶ Executed</button><button class="rowbtn no" onclick="decide(${s.id},'SKIPPED')">Skip</button>`:''}
        ${s.status==='EXECUTED'?`<button class="rowbtn" style="background:var(--amber)" onclick="decide(${s.id},'CLOSED')">✔ Close</button>`:''}
      </div>`;
    document.getElementById('modal').style.display='block';
  }catch(e){ alert('Error: '+e); }
}
function closeModal(){ document.getElementById('modal').style.display='none'; }
document.getElementById('modal').addEventListener('click', e=>{ if(e.target.id==='modal') closeModal(); });

async function coach(){
  const el=document.getElementById('coach'); if(!el) return;
  el.textContent='thinking…';
  const sym=document.getElementById('sym').value.trim().toUpperCase()||'BTCUSDT';
  const tf=document.getElementById('tf').value;
  try{
    const d=await (await fetch(`/api/coach?symbol=${sym}&tf=${tf}`)).json();
    el.textContent=(d.explain||[]).join('\n')+'\n\n'+d.mentor+'\n\n📈 YOUR FEEDBACK\n'+(d.feedback||[]).join('\n');
  }catch(e){ el.textContent='Error: '+e; }
}

load(true);
setInterval(()=>{ if(document.getElementById('auto').checked) load(); }, 30000);
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
        force = request.args.get("force") == "1"
        try:
            if force:
                _CACHE.clear()
            return jsonify(compute_payload(symbol, tf, save=True, use_cache=not force))
        except ConnectionError as exc:
            return jsonify({"error": str(exc)}), 502
        except Exception as exc:  # pragma: no cover
            return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

    @app.get("/api/pending")
    def api_pending():
        from data.database import SignalDB
        with SignalDB() as db:
            return jsonify({"pending": db.pending_reviews()})

    @app.post("/api/review")
    def api_review():
        body = request.get_json(silent=True) or {}
        scan_id = body.get("scan_id")
        decision = (body.get("decision") or "").upper()
        note = body.get("note", "")
        if decision not in ("APPROVED", "REJECTED", "EXECUTED", "CLOSED", "SKIPPED"):
            return jsonify({"error": f"bad decision {decision}"}), 400
        from data.database import SignalDB
        from engine.lifecycle import LifecycleError
        with SignalDB() as db:
            try:
                new = db.update_status(int(scan_id), decision, note=note,
                                       reviewer="dashboard")
            except (LifecycleError, TypeError, ValueError) as exc:
                return jsonify({"error": str(exc)}), 400
            if new is None:
                return jsonify({"error": f"scan #{scan_id} not found"}), 404
        return jsonify({"ok": True, "scan_id": scan_id, "status": new})

    @app.get("/api/history")
    def api_history():
        from data.database import SignalDB
        with SignalDB() as db:
            return jsonify({"history": db.latest_scans(limit=15)})

    @app.get("/api/signal")
    def api_signal():
        scan_id = request.args.get("id", type=int)
        from data.database import SignalDB
        with SignalDB() as db:
            scan = db.get_scan(scan_id)
            if scan is None:
                return jsonify({"error": "not found"}), 404
            plans = json.loads(scan.get("plans_json") or "[]")
            decisions = db.decision_history(scan_id)
        return jsonify({"scan": scan, "plans": plans, "decisions": decisions})

    @app.get("/api/learning")
    def api_learning():
        from data.database import SignalDB
        with SignalDB() as db:
            return jsonify({
                "backtest": db.backtest_stats(),
                "calibration": db.load_calibration(),
                "plan_stats": db.plan_stats(),
            })

    @app.get("/api/coach")
    def api_coach():
        symbol = request.args.get("symbol", SYMBOL).upper()
        tf = request.args.get("tf", TIMEFRAME)
        from brain.coach import explain_signal, mentor, personal_feedback
        from data.database import SignalDB
        payload = compute_payload(symbol, tf, save=False, use_cache=False)
        with SignalDB() as db:
            feedback = personal_feedback(db)
        return jsonify({
            "explain": explain_signal(payload),
            "mentor": mentor(payload),
            "feedback": feedback,
        })

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True})

    return app


def serve(app: Flask, host: str = DASHBOARD_HOST, port: int = DASHBOARD_PORT) -> None:
    app.run(host=host, port=port, debug=False, threaded=True)
