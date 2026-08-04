"""engine/structure.py

ICT / Smart-Money-Concept structure detection on top of raw OHLCV.

Detects and labels (per candle, plus a 'latest snapshot' dict):
  - swing highs / swing lows (fractals)
  - BOS  (Break of Structure, trend continuation) and
    CHOCH (Change of Character, trend reversal) events
  - order blocks (bullish / bearish) with their zones and test status
  - fair value gaps (bullish / bearish), filled / unfilled
  - liquidity: buyside / sellside pools, sweep detection, equal highs/lows
  - premium / discount position relative to the last dealing range

All structure events are computed with only *closed* candles, so there is no
look-ahead. The engine then reasons over the most recent events.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .indicators import _fractals, find_equal_levels


# ──────────────────────────────────────────────────────────────────────────
# Data containers
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class SwingPoint:
    index: int
    kind: str            # "high" | "low"
    price: float
    ts: int              # epoch ms

@dataclass
class StructureEvent:
    kind: str            # "bos_up" | "bos_down" | "choch_up" | "choch_down"
    index: int
    price: float
    ts: int
    context: str = ""

@dataclass
class OrderBlock:
    side: str            # "bullish" | "bearish"
    index: int
    top: float
    bottom: float
    ts: int
    tested: bool = False
    broken: bool = False

@dataclass
class FVG:
    side: str            # "bullish" | "bearish"
    index: int
    top: float
    bottom: float
    ts: int
    filled: bool = False

@dataclass
class MarketStructure:
    swings: list[SwingPoint] = field(default_factory=list)
    events: list[StructureEvent] = field(default_factory=list)
    order_blocks: list[OrderBlock] = field(default_factory=list)
    fvgs: list[FVG] = field(default_factory=list)
    # Latest-state fields (convenience)
    last_event: Optional[StructureEvent] = None
    trend_bias: str = "neutral"          # "bullish" | "bearish" | "neutral"
    liquidity_above: list[float] = field(default_factory=list)
    liquidity_below: list[float] = field(default_factory=list)
    sweep: Optional[dict] = None         # {side, level, index, ts, recovered}
    premium_discount: Optional[dict] = None
    equal_levels: dict = field(default_factory=dict)
    last_swing_high: Optional[float] = None
    last_swing_low: Optional[float] = None
    swing_high_index: Optional[int] = None
    swing_low_index: Optional[int] = None

    def as_dict(self) -> dict:
        return {
            "trend_bias": self.trend_bias,
            "last_event": {
                "kind": self.last_event.kind,
                "price": self.last_event.price,
                "index": self.last_event.index,
            } if self.last_event else None,
            "last_swing_high": self.last_swing_high,
            "last_swing_low": self.last_swing_low,
            "liquidity_above": self.liquidity_above[:6],
            "liquidity_below": self.liquidity_below[:6],
            "sweep": self.sweep,
            "premium_discount": self.premium_discount,
            "equal_highs": self.equal_levels.get("equal_highs", []),
            "equal_lows": self.equal_levels.get("equal_lows", []),
            "order_blocks": [
                {"side": ob.side, "top": ob.top, "bottom": ob.bottom, "tested": ob.tested, "broken": ob.broken}
                for ob in self.order_blocks[-6:]
            ],
            "fvgs": [
                {"side": f.side, "top": f.top, "bottom": f.bottom, "filled": f.filled}
                for f in self.fvgs[-6:]
            ],
        }


# ──────────────────────────────────────────────────────────────────────────
# Detection
# ──────────────────────────────────────────────────────────────────────────

def detect_swings(df: pd.DataFrame, window: int = 2) -> list[SwingPoint]:
    hi_idx, lo_idx = _fractals(df, window)
    swings: list[SwingPoint] = []
    for i in hi_idx:
        swings.append(SwingPoint(index=int(i), kind="high", price=float(df.high.iloc[i]), ts=int(df.ts.iloc[i])))
    for i in lo_idx:
        swings.append(SwingPoint(index=int(i), kind="low", price=float(df.low.iloc[i]), ts=int(df.ts.iloc[i])))
    swings.sort(key=lambda s: s.index)
    return swings


def detect_events(df: pd.DataFrame, swings: list[SwingPoint]) -> list[StructureEvent]:
    """BOS/CHOCH detection over swing structure.

    Rule (simplified ICT): maintain a sequence of alternating swing highs and
    lows. A close beyond the most recent swing in the direction of the current
    micro-trend is a BOS; a close beyond it against the previous higher-timeframe
    swing sequence is a CHOCH. We implement the common heuristic:

      - Build ordered swing points, alternating high/low by construction.
      - Walk forward: when price closes above a prior swing high while the
        previous event was bullish -> bos_up; if the previous bias was bearish
        -> choch_up. Symmetric for the downside.
    """
    events: list[StructureEvent] = []
    if len(swings) < 3:
        return events
    closes = df.close.to_numpy()
    ts = df.ts.to_numpy()
    bias = "neutral"

    # Last two confirmed swing points define current bias seed.
    ordered = swings[-12:]
    for i in range(2, len(ordered)):
        s = ordered[i]
        prev = ordered[i - 1]
        if s.kind == "high":
            # breakout above a prior swing high
            ref_highs = [p.price for p in ordered[:i] if p.kind == "high" and p.index < s.index]
            if ref_highs:
                ref = max(ref_highs)
                if ref < s.price:
                    kind = "bos_up" if bias in ("neutral", "bullish") else "choch_up"
                    events.append(StructureEvent(kind, s.index, s.price, int(ts[s.index]),
                                                 context=f"above {ref:.2f}"))
                    bias = "bullish" if kind == "bos_up" else "bearish"
        else:
            ref_lows = [p.price for p in ordered[:i] if p.kind == "low" and p.index < s.index]
            if ref_lows:
                ref = min(ref_lows)
                if ref > s.price:
                    kind = "bos_down" if bias in ("neutral", "bearish") else "choch_down"
                    events.append(StructureEvent(kind, s.index, s.price, int(ts[s.index]),
                                                 context=f"below {ref:.2f}"))
                    bias = "bearish" if kind == "bos_down" else "bullish"

    # Additionally detect price (candle-close) breaks of the last swing level
    # that a fractal has not yet printed — this catches live breakouts.
    if len(swings) >= 2:
        last = swings[-1]
        closes_arr = closes
        idx = last.index
        if last.kind == "high" and len(closes_arr) > idx:
            above = np.where(closes_arr[idx + 1 :] > last.price)[0]
            if len(above):
                bi = int(above[0]) + idx + 1
                kind = "bos_up" if bias in ("neutral", "bullish") else "choch_up"
                events.append(StructureEvent(kind, bi, float(closes_arr[bi]), int(ts[bi]),
                                             context=f"close above swing high {last.price:.2f}"))
                bias = "bullish"
        elif last.kind == "low" and len(closes_arr) > idx:
            below = np.where(closes_arr[idx + 1 :] < last.price)[0]
            if len(below):
                bi = int(below[0]) + idx + 1
                kind = "bos_down" if bias in ("neutral", "bearish") else "choch_down"
                events.append(StructureEvent(kind, bi, float(closes_arr[bi]), int(ts[bi]),
                                             context=f"close below swing low {last.price:.2f}"))
                bias = "bearish"

    return events


def detect_order_blocks(df: pd.DataFrame, events: list[StructureEvent], window: int = 5) -> list[OrderBlock]:
    """Order blocks: the last opposite-color candle before a structure event.
    A bullish OB = the last down candle whose high/low is immediately below the
    price before a bos_up/choch_up event. Zone = [open, high] (bull) / [low, open] (bear)."""
    blocks: list[OrderBlock] = []
    closes = df.close.to_numpy()
    for ev in events:
        i = ev.index
        start = max(0, i - window)
        if ev.kind in ("bos_up", "choch_up"):
            base = next((j for j in range(i - 1, start - 1, -1) if df.close.iloc[j] < df.open.iloc[j]), None)
            if base is not None and closes[i] > df.high.iloc[base]:
                blocks.append(OrderBlock("bullish", base, float(df.high.iloc[base]), float(df.open.iloc[base]),
                                         int(df.ts.iloc[base])))
        elif ev.kind in ("bos_down", "choch_down"):
            base = next((j for j in range(i - 1, start - 1, -1) if df.close.iloc[j] > df.open.iloc[j]), None)
            if base is not None and closes[i] < df.low.iloc[base]:
                blocks.append(OrderBlock("bearish", base, float(df.open.iloc[base]), float(df.low.iloc[base]),
                                         int(df.ts.iloc[base])))
    # dedupe + status flags
    seen = set()
    unique: list[OrderBlock] = []
    lows, highs = df.low.to_numpy(), df.high.to_numpy()
    for ob in blocks:
        key = (ob.side, round(ob.top, 2), round(ob.bottom, 2))
        if key in seen:
            continue
        seen.add(key)
        after = df.iloc[ob.index + 1 :]
        if not after.empty:
            ob.tested = bool((after.low <= ob.top).any() if ob.side == "bullish" else (after.high >= ob.bottom).any())
            ob.broken = bool((after.low < ob.bottom).any() if ob.side == "bullish" else (after.high > ob.top).any())
        unique.append(ob)
    return unique


def detect_fvgs(df: pd.DataFrame, lookback: int = 200) -> list[FVG]:
    """3-candle fair value gaps. Bullish FVG: low[i+2] > high[i]. Bearish:
    high[i+2] < low[i]. A gap is 'filled' once price trades back through it."""
    data = df.tail(lookback).reset_index(drop=True)
    fvgs: list[FVG] = []
    highs, lows = data.high.to_numpy(), data.low.to_numpy()
    ts = data.ts.to_numpy()
    for i in range(1, len(data) - 1):
        if lows[i + 1] > highs[i - 1]:
            fvgs.append(FVG("bullish", int(i + 1), float(lows[i + 1]), float(highs[i - 1]), int(ts[i + 1])))
        elif highs[i + 1] < lows[i - 1]:
            fvgs.append(FVG("bearish", int(i + 1), float(lows[i - 1]), float(highs[i + 1]), int(ts[i + 1])))
    for f in fvgs:
        after = data.iloc[f.index + 1 :]
        if after.empty:
            continue
        if f.side == "bullish":
            f.filled = bool((after.low <= f.bottom).any())
        else:
            f.filled = bool((after.high >= f.top).any())
    return fvgs


def detect_liquidity(df: pd.DataFrame, swings: list[SwingPoint],
                     sweep_scan: int = 8) -> tuple[list[float], list[float], Optional[dict]]:
    """Buyside liquidity = recent swing highs above price; sellside = swing
    lows below price. A sweep is a candle that wicks beyond a level then closes
    back inside it (stop hunt / liquidity grab). Scans the last `sweep_scan`
    candles so a sweep that happened a few bars ago is still reported."""
    price = float(df.close.iloc[-1])
    bs = sorted({s.price for s in swings if s.kind == "high" and s.price > price}, reverse=True)
    ss = sorted({s.price for s in swings if s.kind == "low" and s.price < price}, reverse=True)

    sweep = None
    window = df.tail(min(sweep_scan, len(df))).reset_index(drop=True)
    for i in range(len(window) - 1, -1, -1):
        candle = window.iloc[i]
        prev_close = window.iloc[i - 1].close if i > 0 else candle.open
        for level in bs[:4]:
            if candle.high > level:
                recovered = candle.close < level
                # only flag if the previous candle did NOT already sit beyond
                already_beyond = prev_close >= level
                if not already_beyond or recovered:
                    sweep = {"side": "buyside", "level": float(level),
                             "recovered": bool(recovered), "bars_ago": len(window) - 1 - i}
                    return bs, ss, sweep
        for level in ss[:4]:
            if candle.low < level:
                recovered = candle.close > level
                already_beyond = prev_close <= level
                if not already_beyond or recovered:
                    sweep = {"side": "sellside", "level": float(level),
                             "recovered": bool(recovered), "bars_ago": len(window) - 1 - i}
                    return bs, ss, sweep
    return bs, ss, sweep


def detect_premium_discount(df: pd.DataFrame, swings: list[SwingPoint]) -> Optional[dict]:
    """Position within the last dealing range (most recent confirmed swing low
    -> swing high). 0 = deep discount, 1 = deep premium, 0.5 = equilibrium."""
    price = float(df.close.iloc[-1])
    recent = [s for s in swings if s.index >= len(df) - 120]
    highs = [s.price for s in recent if s.kind == "high"]
    lows = [s.price for s in recent if s.kind == "low"]
    if not highs or not lows:
        return None
    top, bottom = max(highs), min(lows)
    if top <= bottom:
        return None
    pos = (price - bottom) / (top - bottom)
    return {"top": top, "bottom": bottom, "position": round(pos, 3),
            "zone": "premium" if pos > 0.62 else "discount" if pos < 0.38 else "equilibrium"}


def analyze_structure(df: pd.DataFrame, lookback: int = 200) -> MarketStructure:
    """Full structure analysis over the last `lookback` candles."""
    data = df.tail(lookback).reset_index(drop=True)
    ms = MarketStructure()

    swings = detect_swings(data)
    ms.swings = swings
    ms.events = detect_events(data, swings)
    if ms.events:
        ms.last_event = ms.events[-1]

    ms.order_blocks = detect_order_blocks(data, ms.events)
    ms.fvgs = detect_fvgs(data)

    bs, ss, sweep = detect_liquidity(data, swings)
    ms.liquidity_above = bs
    ms.liquidity_below = ss
    ms.sweep = sweep

    ms.equal_levels = find_equal_levels(data)
    ms.premium_discount = detect_premium_discount(data, swings)

    highs = [s.price for s in swings if s.kind == "high"]
    lows = [s.price for s in swings if s.kind == "low"]
    ms.last_swing_high = highs[-1] if highs else None
    ms.last_swing_low = lows[-1] if lows else None
    ms.swing_high_index = [s.index for s in swings if s.kind == "high"][-1] if highs else None
    ms.swing_low_index = [s.index for s in swings if s.kind == "low"][-1] if lows else None

    if ms.last_event:
        ms.trend_bias = {"bos_up": "bullish", "choch_down": "bearish",
                         "bos_down": "bearish", "choch_up": "bullish"}.get(ms.last_event.kind, "neutral")
    else:
        ms.trend_bias = "neutral"
    return ms
