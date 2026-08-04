"""Tests that guard the dashboard's frontend JavaScript.

These catch the exact class of bug that broke the dashboard for the user:
a duplicate `const` declaration (SyntaxError) that makes the whole <script>
refuse to run, leaving the page stuck at "Loading…" forever — invisible to
server-side curl checks.

When `node` is available (CI has it), we:
  1. extract the <script> from the HTML template and run `node --check`
  2. execute render() with a synthetic payload under stubbed DOM/fetch,
     asserting every card is produced

If node is missing the tests skip (they never fail a machine without node).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "web" / "app.py"

NODE = shutil.which("node")


def _extract_js() -> str:
    src = APP.read_text()
    m = re.search(r'HTML = r?"""(.*?)"""', src, re.S)
    assert m, "HTML template not found"
    html = m.group(1)
    sm = re.search(r"<script>(.*?)</script>", html, re.S)
    assert sm, "script block not found"
    return sm.group(1)


def _synthetic_payload() -> dict:
    """A minimal but realistic payload for render()."""
    return {
        "signal": {"action": "BUY", "asset": "BTCUSDT", "timeframe": "15m",
                   "confidence": "MEDIUM", "signal_id": "BTCUSDT_20260804_0000",
                   "entry": 63000.0, "stop_loss": 62700.0, "take_profit": 63600.0,
                   "risk_reward": 2.0, "reason": "test"},
        "plans": [{"type": "Buy Pullback", "action": "BUY", "confidence": 70,
                   "confidence_label": "MEDIUM", "condition": "IF price pulls back",
                   "entry": 63000.0, "stop_loss": 62700.0, "take_profits": [63600.0],
                   "risk_reward": 2.0}],
        "snapshot": {"features": {"price": 63000.0, "trend": "bullish",
                                  "rsi": 58, "adx": 25, "volume_ratio": 1.5,
                                  "above_vwap": True, "premium_discount": "discount",
                                  "event_kind": "bos_up", "swing_high": 64000.0,
                                  "swing_low": 62000.0, "atr_pct": 0.2,
                                  "rsi_divergence": {"bull": 0, "bear": 0}},
                     "scores": {"bull": {"score": 60, "conditions": {"Trend": 15}},
                                "bear": {"score": 20, "conditions": {}}}},
        "mtf": {"htf_bias": "bullish", "ltf_bias": "neutral",
                "alignment": {"score": 40, "label": "aligned_bull"},
                "views": {"1d": {"available": True, "trend": "bull", "rsi": 60,
                                 "adx": 26, "event_kind": "bos_up",
                                 "premium_discount": "discount"},
                          "4h": {"available": True, "trend": "bull", "rsi": 58,
                                 "adx": 24, "event_kind": None,
                                 "premium_discount": "equilibrium"},
                          "1h": {"available": True, "trend": "bull", "rsi": 55,
                                 "adx": 22, "event_kind": None,
                                 "premium_discount": "equilibrium"},
                          "15m": {"available": True, "trend": "bull", "rsi": 54,
                                  "adx": 20, "event_kind": None,
                                  "premium_discount": "discount"},
                          "5m": {"available": False}},
                "key_levels": {"support": [62000.0], "resistance": [64000.0]}},
        "styles": {"market_offering": ["Day"], "stand_aside": [],
                   "styles": {"Scalp": {"available": False}, "Day": {"available": True,
                             "direction": "BUY", "confidence": 70, "horizon": "1 session",
                             "reason": "test"}, "Swing": {"available": False},
                             "Momentum": {"available": False}, "Position": {"available": False}}},
        "context": {"fear_greed": {"available": True, "value": 55},
                    "dominance": {"available": False}, "equities": {"available": False},
                    "macro": {"available": True, "events": []},
                    "cycle": {"available": True, "phase": "expansion"},
                    "geopolitics": {"available": True, "count": 0},
                    "social": {"available": True, "count": 0},
                    "risk_regime": {"regime": "neutral"}},
        "memory": {"status": "SAME", "reaffirms": 2, "changes": []},
        "market_context": {"futures": False},
        "lifecycle": {"status": "PENDING_REVIEW", "note": "awaiting"},
    }


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_dashboard_js_syntax():
    js = _extract_js()
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(js)
        path = f.name
    try:
        r = subprocess.run([NODE, "--check", path], capture_output=True, text=True)
        assert r.returncode == 0, f"JS syntax error:\n{r.stderr}"
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_dashboard_render_produces_all_cards():
    js = _extract_js()
    payload = _synthetic_payload()
    import json as _json
    harness = f"""
    const payload = {_json.dumps(payload)};
    const elements = {{}};
    function el(id){{ if(!elements[id]) elements[id]={{ innerHTML:'', value:'BTCUSDT',
      textContent:'', checked:true, disabled:false, style:{{}}, addEventListener:()=>{{}},
      querySelector:()=>null }}; return elements[id]; }}
    global.window = {{}};
    global.document = {{ getElementById: el, addEventListener: ()=>{{}} }};
    global.fetch = async (url) => ({{ json: async () => {{
      if(String(url).includes('/api/candles')) return {{ candles: [] }};
      return {{}};
    }} }});
    global.AbortController = class {{ constructor(){{ this.signal={{}}; }} abort(){{}} }};
    global.setInterval = () => 0; global.clearInterval = () => {{}};
    global.setTimeout = () => 0; global.clearTimeout = () => {{}};
    {js}
    const cards = ['LIVE SIGNAL','CANDLESTICK','MULTI-TIMEFRAME','WHAT THE MARKET OFFERS',
      'CONTEXT — WHAT AFFECTS PRICE','STATE MEMORY','HUMAN APPROVAL QUEUE','RECENT SIGNALS',
      'LEARNING','COACH','CONNECTIONS'];
    render(payload);
    const html = elements['app'].innerHTML;
    const missing = cards.filter(c => !html.includes(c));
    if (missing.length) {{ console.error('missing cards:', missing); process.exit(1); }}
    if (!html.length) {{ console.error('empty render'); process.exit(1); }}
    console.log('render OK, cards', cards.length);
    """
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(harness)
        path = f.name
    try:
        r = subprocess.run([NODE, path], capture_output=True, text=True)
        assert r.returncode == 0, f"render failed:\n{r.stdout}\n{r.stderr}"
    finally:
        Path(path).unlink(missing_ok=True)
