"""brain/styles.py — trading-style categorisation.

A human trader does not take random trades. They trade what the market is
offering right now: sometimes the 5m offers a clean scalp, sometimes the 4h
offers a swing, sometimes there is nothing at all (and the correct call is to
stand aside).

This module classifies the current market state into the classic styles:

    Scalp     (minutes)   fast momentum on the LTF, tight risk
    Day       (hours)     HTF bias + LTF trigger, one-session horizon
    Swing     (days)      structural moves off HTF liquidity / discount
    Momentum  (variable)  strong trend + volume expansion + breakout
    Position  (weeks+)    cycle + macro tailwind + deep-value location

Each style returns: available?, direction, confidence, horizon, reason,
entry/SL/TP when a matching plan exists, plus a per-style cooldown so the
engine does not spam the same setup every refresh.
"""
from __future__ import annotations

from dataclasses import dataclass, field

STYLE_COOLDOWN_MIN = {
    "Scalp": 15,
    "Day": 60,
    "Swing": 240,
    "Momentum": 60,
    "Position": 1440,
}
ORDER = ["Scalp", "Day", "Swing", "Momentum", "Position"]


@dataclass
class StyleSignal:
    style: str
    available: bool = False
    direction: str | None = None        # BUY | SELL | None
    confidence: int = 0
    confidence_label: str = "LOW"
    horizon: str = ""
    reason: str = ""
    entry: float | None = None
    stop_loss: float | None = None
    take_profits: list = field(default_factory=list)
    risk_reward: float = 0.0
    plan_id: str | None = None
    cooldown_min: int = 60
    status: str = "none"                # none | active | waiting
    since_ts: int | None = None

    def as_dict(self) -> dict:
        return {
            "style": self.style, "available": self.available,
            "direction": self.direction, "confidence": self.confidence,
            "confidence_label": self.confidence_label, "horizon": self.horizon,
            "reason": self.reason, "entry": self.entry, "stop_loss": self.stop_loss,
            "take_profits": self.take_profits, "risk_reward": self.risk_reward,
            "plan_id": self.plan_id, "cooldown_min": self.cooldown_min,
            "status": self.status, "since_ts": self.since_ts,
        }


def _label(c: int) -> str:
    return "HIGH" if c >= 80 else "MEDIUM" if c >= 60 else "LOW" if c >= 40 else "NONE"


def _plan_for(plans: list, styles: list[str]) -> dict | None:
    """Pick the first plan whose type matches any of the given style intents."""
    for p in plans:
        t = (p.get("type") or "").lower()
        for s in styles:
            s = s.lower()
            if (s == "scalp" and "immediate" in t) or \
               (s == "day" and ("pullback" in t or "fvg" in t)) or \
               (s == "swing" and ("sweep" in t or "reversal" in t)) or \
               (s == "momentum" and "breakout" in t) or \
               (s == "position" and "pullback" in t):
                return p
    return None


def classify_styles(mtf: dict, ctx: dict, frame: dict) -> dict:
    """Classify the current market into per-style signals.

    mtf   : output of engine.mtf.analyze_mtf
    ctx   : output of brain.context.collect
    frame : output of engine.signal_engine.analyze_frame (as_dict)
    """
    f = frame.get("snapshot", {}).get("features", {})
    plans = frame.get("plans", [])
    align = mtf.get("alignment", {})
    score = align.get("score", 0)
    htf = mtf.get("htf_bias", "neutral")
    ltf = mtf.get("ltf_bias", "neutral")
    htf_dir = "BUY" if htf == "bullish" else "SELL" if htf == "bearish" else None
    ltf_dir = "BUY" if ltf == "bullish" else "SELL" if ltf == "bearish" else None

    rsi = f.get("rsi") or 50
    atr_pct = f.get("atr_pct") or 0.2
    vol_ratio = f.get("volume_ratio") or 1.0
    adx = f.get("adx") or 15
    above_vwap = f.get("above_vwap", True)
    pd_zone = f.get("premium_discount", "unknown")
    event = f.get("event_kind")
    sweep = f.get("sweep")
    price = f.get("price") or 0.0

    regime = (ctx.get("risk_regime") or {}).get("regime", "neutral")
    fng = ctx.get("fear_greed", {})
    fng_val = fng.get("value", 50) if fng.get("available") else 50
    macro_imminent = (ctx.get("macro") or {}).get("high_impact_imminent", False)
    cycle_phase = (ctx.get("cycle") or {}).get("phase", "unknown")
    geo_elevated = (ctx.get("geopolitics") or {}).get("elevated", False)
    dom = (ctx.get("dominance") or {})

    styles: dict[str, StyleSignal] = {}
    for s in ORDER:
        styles[s] = StyleSignal(style=s, cooldown_min=STYLE_COOLDOWN_MIN.get(s, 60))

    # ── Scalp (LTF momentum, tight ATR, volume, not against HTF) ─────────
    sc = styles["Scalp"]
    if ltf_dir and atr_pct and 0.04 <= atr_pct <= 0.45 and vol_ratio >= 1.1:
        conflict = (htf == "bullish" and ltf_dir == "SELL") or \
                   (htf == "bearish" and ltf_dir == "BUY")
        if not conflict:
            sc.available = True
            sc.direction = ltf_dir
            sc.confidence = int(55 + min(20, abs(score) * 0.3) + (8 if vol_ratio >= 1.5 else 0))
            sc.confidence = min(sc.confidence, 88)
            sc.confidence_label = _label(sc.confidence)
            sc.horizon = "5m–15m (minutes)"
            sc.reason = (f"LTF momentum {ltf} + volume {vol_ratio:.1f}x + ATR {atr_pct:.2f}% "
                         f"{'above VWAP' if above_vwap else 'below VWAP'} — fast scalping conditions")
            p = _plan_for(plans, ["Scalp", "Momentum"])
            if p:
                sc.entry, sc.stop_loss = p.get("entry"), p.get("stop_loss")
                sc.take_profits = p.get("take_profits") or []
                sc.risk_reward = p.get("risk_reward") or 0
                sc.plan_id = p.get("id")
            sc.status = "active"

    # ── Day (HTF bias + LTF trigger + structure) ─────────────────────────
    dy = styles["Day"]
    if htf_dir and score >= 20 or (htf_dir and event in ("bos_up", "choch_up", "bos_down", "choch_down")):
        if htf_dir:
            dy.available = True
            dy.direction = htf_dir
            dy.confidence = int(60 + min(25, abs(score) * 0.35) + (10 if event else 0))
            dy.confidence = min(dy.confidence, 92)
            dy.confidence_label = _label(dy.confidence)
            dy.horizon = "1 session (hours)"
            dy.reason = (f"HTF bias {htf} aligned with LTF {ltf} "
                         f"{f'after {event}' if event else ''} — classic day-trade confluence")
            p = _plan_for(plans, ["Day"])
            if p:
                dy.entry, dy.stop_loss = p.get("entry"), p.get("stop_loss")
                dy.take_profits = p.get("take_profits") or []
                dy.risk_reward = p.get("risk_reward") or 0
                dy.plan_id = p.get("id")
            dy.status = "active"

    # ── Swing (HTF liquidity / discount / sweep) ─────────────────────────
    sw = styles["Swing"]
    bullish_setup = htf == "bullish" and (pd_zone in ("discount", "equilibrium") or
                                          (sweep and sweep.get("side") == "sellside"))
    bearish_setup = htf == "bearish" and (pd_zone in ("premium", "equilibrium") or
                                          (sweep and sweep.get("side") == "buyside"))
    if abs(score) >= 30 and (bullish_setup or bearish_setup):
        sw.available = True
        sw.direction = "BUY" if bullish_setup else "SELL"
        sw.confidence = int(62 + min(25, abs(score) * 0.4) +
                            (12 if (sweep and sweep.get("recovered")) else 0))
        sw.confidence = min(sw.confidence, 94)
        sw.confidence_label = _label(sw.confidence)
        sw.horizon = "days"
        sw.reason = (f"HTF {htf} + price in {pd_zone} zone "
                     f"{'+ liquidity sweep (stop hunt)' if sweep else ''} — swing structure")
        p = _plan_for(plans, ["Swing", "Position"])
        if p:
            sw.entry, sw.stop_loss = p.get("entry"), p.get("stop_loss")
            sw.take_profits = p.get("take_profits") or []
            sw.risk_reward = p.get("risk_reward") or 0
            sw.plan_id = p.get("id")
        sw.status = "active"

    # ── Momentum (ADX + volume spike + breakout) ─────────────────────────
    mo = styles["Momentum"]
    trend_dir = "BUY" if (score > 20 and above_vwap) else "SELL" if (score < -20 and not above_vwap) else None
    if adx >= 25 and vol_ratio >= 1.5 and trend_dir:
        mo.available = True
        mo.direction = trend_dir
        mo.confidence = int(58 + min(25, abs(score) * 0.35) + min(12, (vol_ratio - 1.5) * 8))
        mo.confidence = min(mo.confidence, 90)
        mo.confidence_label = _label(mo.confidence)
        mo.horizon = "1h–4h (trend)"
        mo.reason = (f"ADX {adx:.0f} (strong) + volume {vol_ratio:.1f}x "
                     f"{'above' if above_vwap else 'below'} VWAP — momentum expansion")
        p = _plan_for(plans, ["Momentum"])
        if p:
            mo.entry, mo.stop_loss = p.get("entry"), p.get("stop_loss")
            mo.take_profits = p.get("take_profits") or []
            mo.risk_reward = p.get("risk_reward") or 0
            mo.plan_id = p.get("id")
        mo.status = "active"

    # ── Position (cycle + macro + deep value) ────────────────────────────
    po = styles["Position"]
    macro_ok = not macro_imminent
    regime_ok = regime != "risk_off" or (fng_val <= 25)  # extreme fear can be contrarian value
    cycle_ok = cycle_phase in ("early-post-halving", "expansion") or (cycle_phase == "pre-halving" and fng_val <= 30)
    deep_value = (htf == "bullish" and pd_zone == "discount" and fng_val <= 40) or \
                 (htf == "bearish" and pd_zone == "premium" and fng_val >= 65)
    if htf_dir and abs(score) >= 40 and cycle_ok and deep_value and macro_ok and regime_ok:
        po.available = True
        po.direction = htf_dir
        po.confidence = int(60 + min(30, abs(score) * 0.45) + (10 if cycle_phase in ("early-post-halving", "expansion") else 0))
        po.confidence = min(po.confidence, 92)
        po.confidence_label = _label(po.confidence)
        po.horizon = "weeks–months"
        po.reason = (f"Cycle phase {cycle_phase} + {htf} HTF + deep-{pd_zone} location + "
                     f"fear&greed {fng_val} — position-level opportunity")
        p = _plan_for(plans, ["Position", "Swing"])
        if p:
            po.entry, po.stop_loss = p.get("entry"), p.get("stop_loss")
            po.take_profits = p.get("take_profits") or []
            po.risk_reward = p.get("risk_reward") or 0
            po.plan_id = p.get("id")
        po.status = "active"

    # Stand-aside reasons (honest "nothing to trade")
    aside = []
    if not any(s.available for s in styles.values()):
        if abs(score) < 20:
            aside.append("timeframes are mixed — no clean alignment")
        if not (adx >= 25):
            aside.append("no strong trend (ADX low)")
        if vol_ratio < 1.2:
            aside.append("volume is flat")
        if macro_imminent:
            aside.append("high-impact macro event within 48h — traders often stand aside")
        if geo_elevated:
            aside.append("geopolitical headlines elevated")

    return {
        "styles": {s: styles[s].as_dict() for s in ORDER},
        "stand_aside": aside,
        "market_offering": [s for s in ORDER if styles[s].available],
    }
