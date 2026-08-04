"""engine/mtf.py — multi-timeframe analysis, the way a human trader reads the
market: higher timeframes set the bias, lower timeframes time the entry.

    HTF (1d, 4h)  →  the "weather" / dominant bias
    MTF (1h)      →  the session context
    LTF (15m, 5m) →  the execution timeframe

Each timeframe is analyzed with the same indicator + structure engine, then
combined into an alignment score (-100..+100), a suggested bias, and a set of
key levels (support / resistance) carried down from the higher frames.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .indicators import add_all_indicators
from .structure import analyze_structure

# (timeframe, bars) — bars sized so each frame has enough history
TF_CONFIG = [("1d", 160), ("4h", 220), ("1h", 240), ("15m", 300), ("5m", 260)]
WEIGHTS = {"1d": 0.35, "4h": 0.25, "1h": 0.20, "15m": 0.12, "5m": 0.08}


def analyze_timeframe(df: pd.DataFrame, tf: str) -> dict:
    """Compact per-timeframe read: trend, momentum, volatility, structure."""
    if df is None or df.empty:
        return {"tf": tf, "available": False}
    ind = add_all_indicators(df)
    ms = analyze_structure(ind)
    last = ind.iloc[-1]
    price = float(last.close)
    ema20, ema50, ema200 = (float(last.get(f"ema_{p}", price)) for p in (20, 50, 200))
    alignment = "bull" if ema20 > ema50 > ema200 else "bear" if ema20 < ema50 < ema200 else "mixed"
    pd_zone = ms.premium_discount["zone"] if ms.premium_discount else "unknown"
    return {
        "tf": tf,
        "available": True,
        "price": price,
        "trend": alignment,
        "supertrend_bull": bool(last.get("supertrend_bull", True)),
        "rsi": float(last.get("rsi", 50)),
        "adx": float(last.get("adx", 15)),
        "atr_pct": float(last.get("atr_pct", 0)),
        "volume_ratio": float(last.get("volume_ratio", 1)),
        "event_kind": ms.last_event.kind if ms.last_event else None,
        "trend_bias": ms.trend_bias,
        "swing_high": ms.last_swing_high,
        "swing_low": ms.last_swing_low,
        "premium_discount": pd_zone,
        "pd_position": ms.premium_discount["position"] if ms.premium_discount else None,
        "sweep": ms.sweep,
        "equal_highs": ms.equal_levels.get("equal_highs", []),
        "equal_lows": ms.equal_levels.get("equal_lows", []),
    }


def _score(view: dict) -> float:
    """Per-frame directional score: bull +1, bear -1, mixed 0."""
    if not view.get("available"):
        return 0.0
    t = view.get("trend")
    if t == "bull":
        return 1.0
    if t == "bear":
        return -1.0
    return 0.0


def analyze_mtf(symbol: str, client, tfs: list | None = None,
                config: list | None = None,
                prefetched: dict | None = None) -> dict:
    """Fetch and analyze multiple timeframes in parallel, then combine into a
    consensus read.

    `prefetched` maps timeframe -> DataFrame already fetched by the caller
    (e.g. the execution timeframe), so it is not re-downloaded.
    """
    config = config or TF_CONFIG
    prefetched = prefetched or {}
    views: dict[str, dict] = {}

    def _one(tf: str, bars: int):
        if tf in prefetched:
            try:
                return tf, analyze_timeframe(prefetched[tf], tf)
            except Exception:
                return tf, {"tf": tf, "available": False}
        try:
            df = client.klines(symbol, tf, bars)
            return tf, analyze_timeframe(df, tf)
        except Exception:
            return tf, {"tf": tf, "available": False}

    with ThreadPoolExecutor(max_workers=len(config)) as ex:
        futures = [ex.submit(_one, tf, bars) for tf, bars in config]
        for fut in futures:
            tf, view = fut.result()
            views[tf] = view

    weighted = sum(_score(views.get(tf, {})) * WEIGHTS.get(tf, 0) for tf in WEIGHTS)
    alignment_score = round(weighted * 100, 1)

    htf_tfs = [t for t in ("1d", "4h") if views.get(t, {}).get("available")]
    mtd_tf = views.get("1h", {})
    ltf_tfs = [t for t in ("15m", "5m") if views.get(t, {}).get("available")]

    def _bias(tfs: list) -> str:
        s = sum(_score(views[t]) * WEIGHTS[t] for t in tfs)
        return "bullish" if s > 0.15 else "bearish" if s < -0.15 else "neutral"

    htf_bias = _bias(htf_tfs) if htf_tfs else "neutral"
    ltf_bias = _bias(ltf_tfs) if ltf_tfs else "neutral"

    if alignment_score >= 30:
        alignment = "aligned_bull"
    elif alignment_score <= -30:
        alignment = "aligned_bear"
    elif (htf_bias == "bullish") != (ltf_bias == "bullish") and htf_bias != "neutral":
        alignment = "counter_trend"
    else:
        alignment = "mixed"

    # Key levels carried down from the higher frames
    resistances, supports = [], []
    for tf in ("1d", "4h", "1h"):
        v = views.get(tf, {})
        if not v.get("available"):
            continue
        price = v["price"]
        if v.get("swing_high") and v["swing_high"] > price:
            resistances.append(v["swing_high"])
        if v.get("swing_low") and v["swing_low"] < price:
            supports.append(v["swing_low"])
    resistances = sorted({round(r, 2) for r in resistances}, reverse=True)[:3]
    supports = sorted({round(s, 2) for s in supports})[-3:]

    pivot = views.get("1d", {}).get("price")
    return {
        "symbol": symbol,
        "views": views,
        "htf_bias": htf_bias,
        "ltf_bias": ltf_bias,
        "alignment": {"score": alignment_score, "label": alignment},
        "key_levels": {"support": supports, "resistance": resistances},
        "pivot": pivot,
        "suggested_bias": "bullish" if htf_bias == "bullish" and ltf_bias != "bearish"
                          else "bearish" if htf_bias == "bearish" and ltf_bias != "bullish"
                          else htf_bias,
    }
