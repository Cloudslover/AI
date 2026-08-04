"""engine/scorer.py

Weighted condition scoring ("YES/NO + points" instead of binary), exactly as
described in the CryptoBrain design:

  Trend          +15
  Market structure (BOS/CHOCH) +15
  Order block / FVG confluence +20
  Liquidity (sweep / pool)     +15
  Volume                        +10
  RSI divergence                +10
  Momentum                      +10
  Location (premium/discount)    +5
                              ─────
                               100  -> confidence

Confidence mapping:  >=80 HIGH, >=60 MEDIUM, >=40 LOW, <40 NO TRADE.
The output keeps the per-condition breakdown so the reason string can cite
exactly which conditions fired.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScoreBreakdown:
    score: int = 0
    max_score: int = 100
    confidence: str = "NO TRADE"
    confidence_pct: int = 0
    conditions: dict = field(default_factory=dict)   # name -> points awarded
    fired: list = field(default_factory=list)        # human-readable reasons

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "max_score": self.max_score,
            "confidence_pct": self.confidence_pct,
            "confidence": self.confidence,
            "conditions": self.conditions,
            "reasons": self.fired,
        }


def _mapped_confidence(score: int) -> tuple[str, int]:
    if score >= 80:
        return "HIGH", score
    if score >= 60:
        return "MEDIUM", score
    if score >= 40:
        return "LOW", score
    return "NO TRADE", score


def score_bullish(f: dict) -> ScoreBreakdown:
    s = ScoreBreakdown()
    cond: dict[str, int] = {}
    fired: list[str] = []

    # Trend (+15)
    t = 0
    if f.get("trend") == "bullish":
        t += 8
    if f.get("supertrend_bull"):
        t += 4
    if f.get("adx_strong"):
        t += 3
    cond["Trend"] = t
    if t >= 10:
        fired.append("Bullish trend alignment (EMA stack + Supertrend)")

    # Market structure (+15)
    m = 0
    if f.get("event_kind") in ("bos_up", "choch_up"):
        m += 15
    elif f.get("trend_bias") == "bullish":
        m += 8
    cond["Market structure"] = m
    if m >= 12:
        fired.append(f"Bullish structure ({f.get('event_kind')})")

    # Order block / FVG confluence (+20)
    o = 0
    if f.get("nearest_bull_ob"):
        o += 10
    if f.get("fvg_bull_count"):
        o += 5
    if f.get("sweep") and f["sweep"].get("side") == "sellside":
        o += 5
    cond["OB/FVG"] = o
    if o >= 12:
        fired.append("Bullish order block / FVG confluence below price")

    # Liquidity (+15)
    lq = 0
    if f.get("sweep") and f["sweep"].get("side") == "sellside":
        lq += 10
    if f.get("liquidity_above"):
        lq += 5  # buyside targets available above
    cond["Liquidity"] = lq
    if lq >= 8:
        fired.append("Sell-side liquidity swept (stop hunt) + buyside targets above")

    # Volume (+10)
    v = 0
    if f.get("volume_spike"):
        v += 6
    elif f.get("volume_above_avg"):
        v += 3
    if f.get("above_vwap"):
        v += 4
    cond["Volume"] = v
    if v >= 7:
        fired.append("Volume expansion above VWAP")

    # RSI divergence (+10)
    d = f.get("rsi_divergence", {}) or {}
    dv = 0
    if d.get("bull") == 2:
        dv += 10
    elif d.get("bull") == 1:
        dv += 6
    cond["RSI divergence"] = dv
    if dv >= 6:
        fired.append("Bullish RSI divergence forming/confirmed")

    # Momentum (+10)
    mm = 0
    if f.get("rsi_bullish") and 40 <= (f.get("rsi") or 50) <= 68:
        mm += 4
    if f.get("macd_hist") is not None and f["macd_hist"] > 0 and f.get("macd_hist_rising"):
        mm += 4
    if f.get("wt_bull"):
        mm += 2
    cond["Momentum"] = mm
    if mm >= 6:
        fired.append("Momentum aligned (RSI>50, MACD histogram rising)")

    # Location (+5)
    loc = 0
    if f.get("premium_discount") == "discount":
        loc += 5
    elif f.get("premium_discount") == "equilibrium":
        loc += 2
    cond["Location"] = loc

    s.score = sum(cond.values())
    s.conditions = cond
    s.fired = fired
    s.confidence, s.confidence_pct = _mapped_confidence(s.score)
    return s


def score_bearish(f: dict) -> ScoreBreakdown:
    s = ScoreBreakdown()
    cond: dict[str, int] = {}
    fired: list[str] = []

    t = 0
    if f.get("trend") == "bearish":
        t += 8
    if not f.get("supertrend_bull", True):
        t += 4
    if f.get("adx_strong"):
        t += 3
    cond["Trend"] = t
    if t >= 10:
        fired.append("Bearish trend alignment")

    m = 0
    if f.get("event_kind") in ("bos_down", "choch_down"):
        m += 15
    elif f.get("trend_bias") == "bearish":
        m += 8
    cond["Market structure"] = m
    if m >= 12:
        fired.append(f"Bearish structure ({f.get('event_kind')})")

    o = 0
    if f.get("nearest_bear_ob"):
        o += 10
    if f.get("fvg_bear_count"):
        o += 5
    if f.get("sweep") and f["sweep"].get("side") == "buyside":
        o += 5
    cond["OB/FVG"] = o
    if o >= 12:
        fired.append("Bearish order block / FVG confluence above price")

    lq = 0
    if f.get("sweep") and f["sweep"].get("side") == "buyside":
        lq += 10
    if f.get("liquidity_below"):
        lq += 5
    cond["Liquidity"] = lq
    if lq >= 8:
        fired.append("Buyside liquidity swept + sellside targets below")

    v = 0
    if f.get("volume_spike"):
        v += 6
    elif f.get("volume_above_avg"):
        v += 3
    if not f.get("above_vwap", True):
        v += 4
    cond["Volume"] = v
    if v >= 7:
        fired.append("Volume expansion below VWAP")

    d = f.get("rsi_divergence", {}) or {}
    dv = 0
    if d.get("bear") == 2:
        dv += 10
    elif d.get("bear") == 1:
        dv += 6
    cond["RSI divergence"] = dv
    if dv >= 6:
        fired.append("Bearish RSI divergence forming/confirmed")

    mm = 0
    if not f.get("rsi_bullish", True) and 32 <= (f.get("rsi") or 50) <= 60:
        mm += 4
    if f.get("macd_hist") is not None and f["macd_hist"] < 0 and not f.get("macd_hist_rising"):
        mm += 4
    if not f.get("wt_bull", True):
        mm += 2
    cond["Momentum"] = mm
    if mm >= 6:
        fired.append("Momentum aligned (RSI<50, MACD histogram falling)")

    loc = 0
    if f.get("premium_discount") == "premium":
        loc += 5
    elif f.get("premium_discount") == "equilibrium":
        loc += 2
    cond["Location"] = loc

    s.score = sum(cond.values())
    s.conditions = cond
    s.fired = fired
    s.confidence, s.confidence_pct = _mapped_confidence(s.score)
    return s


def score_neutral(f: dict) -> ScoreBreakdown:
    """Both-side scores below threshold → NO TRADE."""
    bull = score_bullish(f)
    bear = score_bearish(f)
    s = ScoreBreakdown()
    s.confidence = "NO TRADE"
    s.confidence_pct = max(bull.confidence_pct, bear.confidence_pct)
    s.conditions = {"bull_score": bull.score, "bear_score": bear.score}
    s.fired = ["No side reaches the trade threshold — market is not offering a clean edge."]
    return s
