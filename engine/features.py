"""engine/features.py

Builds the "market snapshot" — a single labeled dict describing the current
state of every indicator family. This is exactly what the scoring engine and
the IF/THEN rule engine read, and what the LLM AI Brain consumes for its
plain-English narrative.

The snapshot is assembled in a fixed schema so it can be JSON-serialised,
stored, and compared across refreshes (for divergence-over-time features like
"confidence rising").
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .structure import MarketStructure


def _f(x, nd: int = 2) -> Optional[float]:
    try:
        v = float(x)
        if v != v:  # NaN
            return None
        return round(v, nd)
    except (TypeError, ValueError):
        return None


def build_snapshot(df: pd.DataFrame, ms: MarketStructure, divergence: dict,
                   equal_levels: dict) -> dict:
    """Assemble the feature snapshot from an indicator-enriched DataFrame and
    the market-structure result."""
    if df is None or df.empty:
        return {"empty": True}
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last
    price = float(last.close)

    # ── Trend ────────────────────────────────────────────────────────────
    ema20, ema50, ema200 = float(last.get("ema_20", price)), float(last.get("ema_50", price)), float(last.get("ema_200", price))
    bullish_alignment = ema20 > ema50 > ema200 and price > ema20
    bearish_alignment = ema20 < ema50 < ema200 and price < ema20
    supertrend_bull = bool(last.get("supertrend_bull", True))
    adx = _f(last.get("adx", 20), 1)
    adx_strong = (adx or 0) >= 25
    plus_di = _f(last.get("plus_di", 0), 1)
    minus_di = _f(last.get("minus_di", 0), 1)

    # ── Momentum ─────────────────────────────────────────────────────────
    rsi = _f(last.get("rsi", 50), 1)
    rsi_prev = _f(prev.get("rsi", 50), 1)
    macd_hist = _f(last.get("macd_hist", 0), 4)
    macd_hist_prev = _f(prev.get("macd_hist", 0), 4)
    macd_bull_cross = bool((last.get("macd_hist", 0) > 0) and (prev.get("macd_hist", 0) <= 0))
    macd_bear_cross = bool((last.get("macd_hist", 0) < 0) and (prev.get("macd_hist", 0) >= 0))
    wt1, wt2 = _f(last.get("wt1", 0), 2), _f(last.get("wt2", 0), 2)
    stoch_k = _f(last.get("stoch_k", 50), 1)
    roc = _f(last.get("roc", 0), 2)

    # ── Volatility ───────────────────────────────────────────────────────
    atr = float(last.get("atr", 0))
    atr_pct = _f(last.get("atr_pct", 0), 3)
    bb_width = _f(last.get("bb_width_pct", 0), 2)
    compress = bool(last.get("bb_compress", False))

    # ── Volume ───────────────────────────────────────────────────────────
    volume_ratio = _f(last.get("volume_ratio", 1), 2)
    above_vwap = bool(last.get("price_above_vwap", True))
    vwap = _f(last.get("vwap", price))
    poc = _f(last.get("poc"))
    obv_slope = _f(last.get("obv_slope", 0), 1)
    delta = _f(last.get("delta", 0))
    volume_spike = bool(volume_ratio and volume_ratio >= 1.8)
    volume_above_avg = bool(volume_ratio and volume_ratio >= 1.15)

    # ── Structure (from MarketStructure) ─────────────────────────────────
    last_event = ms.last_event
    event_kind = last_event.kind if last_event else None
    event_age = (len(df) - 1 - last_event.index) if last_event else None

    ob_bull = [ob for ob in ms.order_blocks if ob.side == "bullish" and not ob.broken]
    ob_bear = [ob for ob in ms.order_blocks if ob.side == "bearish" and not ob.broken]
    fvg_bull = [f for f in ms.fvgs if f.side == "bullish" and not f.filled]
    fvg_bear = [f for f in ms.fvgs if f.side == "bearish" and not f.filled]

    def nearest_level(levels, price, below=True):
        if not levels:
            return None
        if below:
            cands = [l for l in levels if l < price]
            return max(cands) if cands else None
        cands = [l for l in levels if l > price]
        return min(cands) if cands else None

    nearest_bull_ob = nearest_level([ob.bottom for ob in ob_bull], price, below=True)
    nearest_bear_ob = nearest_level([ob.top for ob in ob_bear], price, below=False)
    nearest_bull_fvg = nearest_level([f.bottom for f in fvg_bull], price, below=True)
    nearest_bear_fvg = nearest_level([f.top for f in fvg_bear], price, below=False)

    pd_zone = ms.premium_discount["zone"] if ms.premium_discount else "unknown"

    return {
        # meta
        "symbol": str(df.attrs.get("symbol", "")),
        "timeframe": str(df.attrs.get("timeframe", "")),
        "price": price,
        "bar_ts": int(last.ts),

        # trend
        "trend": "bullish" if bullish_alignment else "bearish" if bearish_alignment else "mixed",
        "ema_alignment_bull": bullish_alignment,
        "ema_alignment_bear": bearish_alignment,
        "supertrend_bull": supertrend_bull,
        "adx": adx,
        "adx_strong": adx_strong,
        "plus_di": plus_di,
        "minus_di": minus_di,

        # momentum
        "rsi": rsi,
        "rsi_prev": rsi_prev,
        "rsi_overbought": bool(rsi and rsi >= 70),
        "rsi_oversold": bool(rsi and rsi <= 30),
        "rsi_bullish": bool(rsi and rsi >= 50),
        "macd_hist": macd_hist,
        "macd_hist_rising": bool(macd_hist is not None and macd_hist_prev is not None and macd_hist > macd_hist_prev),
        "macd_bull_cross": macd_bull_cross,
        "macd_bear_cross": macd_bear_cross,
        "wt1": wt1,
        "wt2": wt2,
        "wt_bull": bool(wt1 is not None and wt2 is not None and wt1 > wt2),
        "wt_overbought": bool(wt1 is not None and wt1 > 53),
        "wt_oversold": bool(wt1 is not None and wt1 < -53),
        "stoch_k": stoch_k,
        "roc": roc,

        # divergence
        "rsi_divergence": {
            "bull": divergence.get("bull_div", 0),
            "bear": divergence.get("bear_div", 0),
            "bull_price_low": divergence.get("bull_price_low"),
            "bear_price_high": divergence.get("bear_price_high"),
        },

        # volatility
        "atr": _f(atr, 2),
        "atr_pct": atr_pct,
        "bb_width_pct": bb_width,
        "bb_compress": compress,

        # volume
        "volume_ratio": volume_ratio,
        "volume_spike": volume_spike,
        "volume_above_avg": volume_above_avg,
        "above_vwap": above_vwap,
        "vwap": vwap,
        "poc": poc,
        "obv_slope": obv_slope,
        "delta": delta,
        "close_vs_vwap_pct": _f((price / vwap - 1) * 100, 2) if vwap else None,

        # structure
        "event_kind": event_kind,
        "event_age": event_age,
        "trend_bias": ms.trend_bias,
        "swing_high": ms.last_swing_high,
        "swing_low": ms.last_swing_low,
        "nearest_bull_ob": nearest_bull_ob,
        "nearest_bear_ob": nearest_bear_ob,
        "nearest_bull_fvg": nearest_bull_fvg,
        "nearest_bear_fvg": nearest_bear_fvg,
        "fvg_bull_count": len(fvg_bull),
        "fvg_bear_count": len(fvg_bear),
        "premium_discount": pd_zone,
        "premium_discount_position": ms.premium_discount["position"] if ms.premium_discount else None,
        "liquidity_above": ms.liquidity_above[:6],
        "liquidity_below": ms.liquidity_below[:6],
        "equal_highs": equal_levels.get("equal_highs", []),
        "equal_lows": equal_levels.get("equal_lows", []),
        "sweep": ms.sweep,
    }
