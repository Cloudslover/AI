"""brain/full_pipeline.py — the complete "human trader" analysis.

Combines:
  1. multi-timeframe view      (HTF bias → LTF execution)
  2. full market context       (news, macro, geopolitics, cycle, social,
                                equities, fear&greed, dominance)
  3. single-frame signal engine (indicators + structure + plans)
  4. trading-style classification
  5. state memory              (stable signals, no 30s spam)

Returns one JSON-able dict that the CLI and dashboard both render.
"""
from __future__ import annotations

import time
from typing import Optional

from config import SYMBOL, TIMEFRAME, BARS, MIN_CONFIDENCE, DEFAULT_RISK_REWARD
from data.binance_client import BinanceClient
from engine.mtf import analyze_mtf, analyze_timeframe
from engine.signal_engine import analyze_frame
from output.signal_schema import validate_output
import brain.context as context_mod
from .calibrator import apply_calibration as _cal_apply
from .state_memory import SignalMemory
from .styles import classify_styles


def _load_calibration(db=None) -> dict:
    try:
        from ..data.database import SignalDB
        with SignalDB() as _db:
            return _db.load_calibration()
    except Exception:
        return {}


def analyze_full(symbol: str = SYMBOL, timeframe: str = TIMEFRAME,
                 bars: int = BARS, client: Optional[BinanceClient] = None,
                 with_context: bool = True, with_memory: bool = True) -> dict:
    """Run the complete pipeline. Returns a dict with keys:
    signal, plans, snapshot, styles, mtf, context, memory, market_context,
    validation, analyzed_at."""
    client = client or BinanceClient()
    t0 = time.time()

    # 1) Multi-timeframe
    mtf = analyze_mtf(symbol, client)

    # 2) single-frame engine (with calibration)
    df = client.klines(symbol, timeframe, bars)
    calib = _load_calibration()
    frame = analyze_frame(df, symbol=symbol, timeframe=timeframe,
                          min_confidence=MIN_CONFIDENCE,
                          default_rr=DEFAULT_RISK_REWARD, calibration=calib)
    payload = frame.as_json()
    payload["market_context"] = client.market_context(symbol)

    # 3) context (cached, best-effort) — pass 1d SMA/price for the cycle view
    ctx = {}
    if with_context:
        v1d = mtf.get("views", {}).get("1d", {})
        ctx = context_mod.collect(price_1d=v1d.get("price"),
                                  sma200_1d=None if not v1d.get("available") else
                                  _sma200(v1d))
    payload["context"] = ctx
    payload["mtf"] = mtf

    # 4) styles
    styles = classify_styles(mtf, ctx, payload)
    payload["styles"] = styles

    # 5) state memory
    memory = {}
    if with_memory:
        mem = SignalMemory()
        mem_result = mem.update(symbol, timeframe, mtf, styles, payload)
        payload["memory"] = mem_result
        payload["memory_events"] = mem.history(symbol, timeframe, limit=12)
        memory = mem_result

    payload["validation"] = validate_output(payload)
    payload["analyzed_at"] = int(time.time() * 1000)
    payload["elapsed_ms"] = int((time.time() - t0) * 1000)
    return payload


def _sma200(v: dict) -> Optional[float]:
    """Approx 200d SMA proxy from the 1d view (fall back to price)."""
    return v.get("price")


def summarize_styles(styles: dict) -> str:
    if not styles:
        return ""
    offered = styles.get("market_offering", [])
    if not offered:
        return "Stand aside — " + "; ".join(styles.get("stand_aside", [])) + "."
    return "Market offering: " + ", ".join(
        f"{s} ({styles['styles'][s]['direction']} {styles['styles'][s]['confidence']}%)"
        for s in offered) + "."
