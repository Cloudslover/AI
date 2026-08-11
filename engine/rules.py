"""engine/rules.py

The multi-condition plan generator. Instead of emitting one forced entry, the
engine produces a set of *conditional* trade plans — the way a discretionary
ICT/SMC trader thinks:

  plan: Immediate Buy          -> entry now if confluence is already strong
  plan: Buy Pullback at OB     -> IF price returns to the bullish order block
  plan: Breakout Buy           -> IF a 15m candle closes above the swing high
  plan: Reversal Sell          -> IF buyside liquidity is swept + bearish CHOCH
  plan: FVG Retest             -> IF price retraces into an unfilled fair value gap

Every plan carries: human-readable condition, trigger level, entry, stop-loss,
take-profit ladder, risk:reward, confidence %, and the reasons it was created.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

from .scorer import ScoreBreakdown, _mapped_confidence


@dataclass(frozen=True)
class Plan:
    id: str
    type: str
    action: str                      # BUY | SELL
    condition: str                   # human-readable IF statement
    trigger_level: Optional[float]   # level that must be reached / broken
    entry: Optional[float]
    stop_loss: Optional[float]
    take_profits: list = field(default_factory=list)
    risk_reward: float = 0.0
    confidence_pct: int = 0
    confidence_label: str = "LOW"
    reasons: list = field(default_factory=list)
    status: str = "active"           # active | waiting
    primary: bool = True             # set later by the authorization policy
    authorization_reason: str = "not evaluated"
    execution_mode: str = "immediate"  # immediate | conditional
    source_timeframe: Optional[str] = None
    fill_probability: Optional[float] = None
    fill_samples: int = 0
    fill_horizon_hours: Optional[float] = None

    def __post_init__(self) -> None:
        # Defensive copies make the frozen record deeply immutable at its
        # collection boundaries; callers receive fresh lists from ``as_dict``.
        object.__setattr__(self, "take_profits", tuple(self.take_profits))
        object.__setattr__(self, "reasons", tuple(self.reasons))

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "action": self.action,
            "condition": self.condition,
            "trigger_level": round(self.trigger_level, 2) if self.trigger_level else None,
            "entry": round(self.entry, 2) if self.entry else None,
            "stop_loss": round(self.stop_loss, 2) if self.stop_loss else None,
            "take_profits": [round(tp, 2) for tp in self.take_profits],
            "risk_reward": round(self.risk_reward, 2),
            "confidence": self.confidence_pct,
            "confidence_label": self.confidence_label,
            "reasons": list(self.reasons),
            "status": self.status,
            "primary": self.primary,
            "authorization_reason": self.authorization_reason,
            "execution_mode": self.execution_mode,
            "source_timeframe": self.source_timeframe,
            "fill_probability": (round(self.fill_probability, 4)
                                 if self.fill_probability is not None else None),
            "fill_samples": self.fill_samples,
            "fill_horizon_hours": self.fill_horizon_hours,
        }


def _tp_rr_for(plan_type: str, default_rr: float,
               tp_rr_by_type: Optional[dict]) -> float:
    """Per-setup take-profit distance in R (decision A2). Falls back to the
    engine default when no measured profile exists yet."""
    if tp_rr_by_type and plan_type in tp_rr_by_type:
        try:
            v = float(tp_rr_by_type[plan_type])
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    return default_rr


def _rr(entry: float, sl: float, tps: list[float]) -> float:
    risk = abs(entry - sl)
    if risk <= 0 or not tps:
        return 0.0
    reward = sum(abs(tp - entry) for tp in tps[:2]) / len(tps[:2])
    return round(reward / risk, 2)


def _confidence(score: ScoreBreakdown) -> tuple[int, str]:
    return score.confidence_pct, score.confidence


def _sl_buffer(price: float, atr: float, side: str, min_pct: float = 0.3) -> float:
    """Structural stop: at least ATR * 1.5 but never less than min_pct% away."""
    raw = max(atr * 1.5, price * min_pct / 100)
    if side == "BUY":
        return round(price - raw, 2)
    return round(price + raw, 2)


def _structure_target(f: dict, side: str, kind: str) -> tuple[Optional[float], str, Optional[str]]:
    """Pick the nearest valid LTF/HTF structure level for a conditional plan.

    ``engine.mtf`` carries unbroken order blocks and unfilled FVGs down from
    1W/1D/4H/1H.  They compete with the execution-frame level by distance, so
    an HTF object is used only when it is practically relevant to current
    price rather than merely present somewhere on the chart.
    """
    price = float(f.get("price") or 0)
    tf = str(f.get("timeframe") or "execution")
    bullish = side == "BUY"
    local_key = f"nearest_{'bull' if bullish else 'bear'}_{'ob' if kind == 'order_block' else 'fvg'}"
    local = f.get(local_key)
    label_side = "bullish" if bullish else "bearish"
    label_kind = "Order Block" if kind == "order_block" else "FVG"
    candidates: list[tuple[float, str, Optional[str]]] = []
    if local:
        candidates.append((float(local), f"{tf} {label_side} {label_kind}", tf))

    for obj in f.get("htf_structure") or []:
        if obj.get("kind") != kind or obj.get("side") != label_side:
            continue
        try:
            level = float(obj.get("level"))
        except (TypeError, ValueError):
            continue
        candidates.append((level, f"{obj.get('timeframe', 'HTF')} {label_side} {label_kind}",
                           obj.get("timeframe")))

    if bullish:
        candidates = [c for c in candidates if 0 < c[0] < price]
    else:
        candidates = [c for c in candidates if c[0] > price]
    if not candidates:
        return None, "", None
    level, label, source_tf = min(candidates, key=lambda c: abs(c[0] - price))
    return level, label, source_tf


def build_plans(f: dict, bull: ScoreBreakdown, bear: ScoreBreakdown,
                min_confidence: int = 55, default_rr: float = 2.0,
                max_plans: int = 8, calibration: dict | None = None,
                primary_types: set | None = None,
                tp_rr_by_type: dict | None = None,
                fill_stats_by_type: dict | None = None,
                regime: str = "") -> list[Plan]:
    price = f["price"]
    atr = f.get("atr") or price * 0.003
    plans: list[Plan] = []

    def _is_primary(plan_type: str) -> bool:
        """Generation is policy-agnostic; authorization happens after all
        setup families have been generated and calibrated."""
        return True

    # ── 1. Immediate entries (strong confluence right now) ───────────────
    if bull.confidence_pct >= min_confidence:
        rr = _tp_rr_for("Immediate Buy", default_rr, tp_rr_by_type)
        sl = _sl_buffer(price, atr, "BUY")
        tps = [round(price + (price - sl) * rr, 2),
               round(price + (price - sl) * rr * 1.5, 2)]
        plans.append(Plan(
            id="imm_buy", type="Immediate Buy", action="BUY",
            condition=f"Enter now — {bull.confidence_pct}% confluence at {price:,.2f}",
            trigger_level=None, entry=price, stop_loss=sl, take_profits=tps,
            risk_reward=_rr(price, sl, tps), confidence_pct=bull.confidence_pct,
            confidence_label=bull.confidence, reasons=bull.fired,
            primary=_is_primary("Immediate Buy"),
        ))
    if bear.confidence_pct >= min_confidence:
        rr = _tp_rr_for("Immediate Sell", default_rr, tp_rr_by_type)
        sl = _sl_buffer(price, atr, "SELL")
        tps = [round(price - (sl - price) * rr, 2),
               round(price - (sl - price) * rr * 1.5, 2)]
        plans.append(Plan(
            id="imm_sell", type="Immediate Sell", action="SELL",
            condition=f"Enter now — {bear.confidence_pct}% confluence at {price:,.2f}",
            trigger_level=None, entry=price, stop_loss=sl, take_profits=tps,
            risk_reward=_rr(price, sl, tps), confidence_pct=bear.confidence_pct,
            confidence_label=bear.confidence, reasons=bear.fired,
            primary=_is_primary("Immediate Sell"),
        ))

    # ── 2. Buy pullback into bullish OB / FVG / discount zone ────────────
    ob_level, ob_source, ob_tf = _structure_target(f, "BUY", "order_block")
    fvg_level, fvg_source, fvg_tf = _structure_target(f, "BUY", "fvg")
    pull_level = None
    source_tf = None
    if ob_level:
        pull_level, source, source_tf = ob_level, ob_source, ob_tf
    elif fvg_level:
        pull_level, source, source_tf = fvg_level, fvg_source, fvg_tf
    elif f.get("premium_discount") == "discount" and f.get("swing_low"):
        pull_level = max(f["swing_low"], price * 0.985)
        source = "execution-TF discount zone / swing low"
        source_tf = f.get("timeframe")
    if pull_level and pull_level < price:
        rr = _tp_rr_for("Buy Pullback", default_rr, tp_rr_by_type)
        sl = _sl_buffer(pull_level, atr, "BUY")
        tps = [round(pull_level + (pull_level - sl) * rr, 2),
               round(price + (price - sl) * rr * 1.2, 2)]
        conf = min(95, bull.confidence_pct + 8)
        label, _ = _mapped_confidence(conf)
        plans.append(Plan(
            id="buy_pullback", type="Buy Pullback", action="BUY",
            condition=(f"IF price pulls back to {source} near {pull_level:,.2f} AND "
                       f"{f.get('timeframe', 'execution TF')} prints CHOCH up / bullish rejection"),
            trigger_level=pull_level, entry=round(pull_level, 2), stop_loss=sl,
            take_profits=tps, risk_reward=_rr(pull_level, sl, tps),
            confidence_pct=conf, confidence_label=label,
            reasons=list(bull.fired) + [f"Pullback target = {source}"],
            status="waiting", primary=_is_primary("Buy Pullback"),
            execution_mode="conditional", source_timeframe=source_tf,
        ))

    # ── 3. Sell pullback into bearish OB / FVG ───────────────────────────
    ob_s, ob_s_source, ob_s_tf = _structure_target(f, "SELL", "order_block")
    fvg_s, fvg_s_source, fvg_s_tf = _structure_target(f, "SELL", "fvg")
    pull_s = None
    source_s_tf = None
    if ob_s:
        pull_s, source_s, source_s_tf = ob_s, ob_s_source, ob_s_tf
    elif fvg_s:
        pull_s, source_s, source_s_tf = fvg_s, fvg_s_source, fvg_s_tf
    elif f.get("premium_discount") == "premium" and f.get("swing_high"):
        pull_s = min(f["swing_high"], price * 1.015)
        source_s = "execution-TF premium zone / swing high"
        source_s_tf = f.get("timeframe")
    if pull_s and pull_s > price:
        rr = _tp_rr_for("Sell Pullback", default_rr, tp_rr_by_type)
        sl = _sl_buffer(pull_s, atr, "SELL")
        tps = [round(pull_s - (sl - pull_s) * rr, 2),
               round(price - (sl - price) * rr * 1.2, 2)]
        conf = min(95, bear.confidence_pct + 8)
        label, _ = _mapped_confidence(conf)
        plans.append(Plan(
            id="sell_pullback", type="Sell Pullback", action="SELL",
            condition=(f"IF price rallies to {source_s} near {pull_s:,.2f} AND "
                       f"{f.get('timeframe', 'execution TF')} prints CHOCH down / bearish rejection"),
            trigger_level=pull_s, entry=round(pull_s, 2), stop_loss=sl,
            take_profits=tps, risk_reward=_rr(pull_s, sl, tps),
            confidence_pct=conf, confidence_label=label,
            reasons=list(bear.fired) + [f"Pullback target = {source_s}"],
            status="waiting", primary=_is_primary("Sell Pullback"),
            execution_mode="conditional", source_timeframe=source_s_tf,
        ))

    # ── 4. Breakout buy above swing high / BOS level ─────────────────────
    swing_high = f.get("swing_high")
    if swing_high and swing_high > price and price > (swing_high * 0.985):
        rr = _tp_rr_for("Breakout Buy", default_rr, tp_rr_by_type)
        entry = round(swing_high * 1.0005, 2)
        sl = _sl_buffer(swing_high, atr, "BUY")
        tps = [round(entry + (entry - sl) * rr, 2),
               round(entry + (entry - sl) * rr * 1.5, 2)]
        conf = min(92, max(bull.confidence_pct + 5, 60))
        label, _ = _mapped_confidence(conf)
        plans.append(Plan(
            id="breakout_buy", type="Breakout Buy", action="BUY",
            condition=f"IF a candle CLOSES above swing high {swing_high:,.2f} (BOS confirmation) with volume",
            trigger_level=swing_high, entry=entry, stop_loss=sl,
            take_profits=tps, risk_reward=_rr(entry, sl, tps),
            confidence_pct=conf, confidence_label=label,
            reasons=bull.fired + [f"Breakout above {swing_high:,.2f}",
                                  "requires close + volume confirmation"],
            status="waiting", primary=_is_primary("Breakout Buy"),
            execution_mode="conditional", source_timeframe=f.get("timeframe"),
        ))

    # ── 5. Reversal sell after buyside liquidity sweep ───────────────────
    sweep = f.get("sweep") or {}
    if sweep.get("side") == "buyside":
        rr = _tp_rr_for("Sweep Reversal Sell", default_rr, tp_rr_by_type)
        entry = price
        sl = _sl_buffer(price, atr, "SELL")
        tps = [round(price - (sl - price) * rr, 2),
               round(price - (sl - price) * rr * 1.5, 2)]
        conf = min(90, max(bear.confidence_pct + 10, 62))
        label, _ = _mapped_confidence(conf)
        plans.append(Plan(
            id="reversal_sell", type="Sweep Reversal Sell", action="SELL",
            condition=(f"IF buyside liquidity was swept at {sweep.get('level')} AND "
                       f"price shows bearish CHOCH / rejection"),
            trigger_level=sweep.get("level"), entry=entry, stop_loss=sl,
            take_profits=tps, risk_reward=_rr(entry, sl, tps),
            confidence_pct=conf, confidence_label=label,
            reasons=list(bear.fired) + ["Buyside stop hunt detected"],
            status=("active" if f.get("event_kind") == "choch_down" else "waiting"),
            primary=_is_primary("Sweep Reversal Sell"),
            execution_mode=("immediate" if f.get("event_kind") == "choch_down" else "conditional"),
            source_timeframe=f.get("timeframe"),
        ))
    elif sweep.get("side") == "sellside":
        rr = _tp_rr_for("Sweep Reversal Buy", default_rr, tp_rr_by_type)
        entry = price
        sl = _sl_buffer(price, atr, "BUY")
        tps = [round(price + (price - sl) * rr, 2),
               round(price + (price - sl) * rr * 1.5, 2)]
        conf = min(90, max(bull.confidence_pct + 10, 62))
        label, _ = _mapped_confidence(conf)
        plans.append(Plan(
            id="reversal_buy", type="Sweep Reversal Buy", action="BUY",
            condition=(f"IF sellside liquidity was swept at {sweep.get('level')} AND "
                       f"price shows bullish CHOCH / rejection"),
            trigger_level=sweep.get("level"), entry=entry, stop_loss=sl,
            take_profits=tps, risk_reward=_rr(entry, sl, tps),
            confidence_pct=conf, confidence_label=label,
            reasons=list(bull.fired) + ["Sellside stop hunt detected"],
            status=("active" if f.get("event_kind") == "choch_up" else "waiting"),
            primary=_is_primary("Sweep Reversal Buy"),
            execution_mode=("immediate" if f.get("event_kind") == "choch_up" else "conditional"),
            source_timeframe=f.get("timeframe"),
        ))

    # ── 6. FVG retest (unfilled gap in trade direction) ──────────────────
    if fvg_level and fvg_level < price and bull.confidence_pct >= 45:
        rr = _tp_rr_for("FVG Retest Buy", default_rr, tp_rr_by_type)
        sl = _sl_buffer(fvg_level, atr, "BUY")
        tps = [round(fvg_level + (fvg_level - sl) * rr, 2),
               round(price + (price - sl) * rr * 1.1, 2)]
        conf = min(88, bull.confidence_pct + 5)
        label, _ = _mapped_confidence(conf)
        plans.append(Plan(
            id="fvg_retest_buy", type="FVG Retest Buy", action="BUY",
            condition=(f"IF price retraces into {fvg_source or 'unfilled bullish FVG'} at "
                       f"{fvg_level:,.2f} and holds"),
            trigger_level=fvg_level, entry=round(fvg_level, 2), stop_loss=sl,
            take_profits=tps, risk_reward=_rr(fvg_level, sl, tps),
            confidence_pct=conf, confidence_label=label,
            reasons=list(bull.fired) + ["Unfilled bullish fair value gap"],
            status="waiting", primary=_is_primary("FVG Retest Buy"),
            execution_mode="conditional", source_timeframe=fvg_tf,
        ))
    if fvg_s and fvg_s > price and bear.confidence_pct >= 45:
        rr = _tp_rr_for("FVG Retest Sell", default_rr, tp_rr_by_type)
        sl = _sl_buffer(fvg_s, atr, "SELL")
        tps = [round(fvg_s - (sl - fvg_s) * rr, 2),
               round(price - (sl - price) * rr * 1.1, 2)]
        conf = min(88, bear.confidence_pct + 5)
        label, _ = _mapped_confidence(conf)
        plans.append(Plan(
            id="fvg_retest_sell", type="FVG Retest Sell", action="SELL",
            condition=(f"IF price rallies into {fvg_s_source or 'unfilled bearish FVG'} at "
                       f"{fvg_s:,.2f} and rejects"),
            trigger_level=fvg_s, entry=round(fvg_s, 2), stop_loss=sl,
            take_profits=tps, risk_reward=_rr(fvg_s, sl, tps),
            confidence_pct=conf, confidence_label=label,
            reasons=list(bear.fired) + ["Unfilled bearish fair value gap"],
            status="waiting", primary=_is_primary("FVG Retest Sell"),
            execution_mode="conditional", source_timeframe=fvg_s_tf,
        ))

    # Apply the calibration profile (self-improvement) before filtering:
    # boost positive-expectancy plan types, dampen negative ones, drop filtered.
    # Profiles are keyed by plan_type or plan_type::regime (decision B3).
    if calibration:
        from .calibration_hook import apply_calibration
        kept: list[Plan] = []
        for p in plans:
            conf, filtered = apply_calibration(p.confidence_pct, p.type, calibration,
                                               regime=regime)
            if filtered:
                continue
            if conf != p.confidence_pct:
                label, _ = _mapped_confidence(conf)
                p = replace(p, confidence_pct=conf, confidence_label=label)
            kept.append(p)
        plans = kept

    # Execution probability is distinct from analytical confidence. Immediate
    # candidates are executable now (1.0); waiting plans use measured historical
    # trigger/fill frequency when enough backtest evidence exists.
    with_fill: list[Plan] = []
    for p in plans:
        fill = 1.0 if p.execution_mode == "immediate" else None
        fill_samples = 0
        fill_horizon = None
        if p.execution_mode == "conditional" and fill_stats_by_type:
            raw = fill_stats_by_type.get(p.type)
            stats = raw if isinstance(raw, dict) else {}
            if isinstance(raw, dict):
                raw = raw.get("fill_probability")
                fill_samples = int(stats.get("fill_samples") or 0)
                fill_horizon = stats.get("fill_horizon_hours")
            try:
                fill = max(0.0, min(1.0, float(raw))) if raw is not None else None
            except (TypeError, ValueError):
                fill = None
        with_fill.append(replace(p, fill_probability=fill,
                                 fill_samples=fill_samples,
                                 fill_horizon_hours=fill_horizon))
    plans = with_fill

    # Apply setup authorization only after generation/calibration. Research on
    # every family remains visible and continues to feed the learning loop.
    from .policy import SetupFamilyPolicy
    policy = SetupFamilyPolicy.from_types(primary_types)
    plans = list(policy.authorize(plans))

    # Filter to the research display threshold, sort by analytical confidence,
    # then cap output volume. Authorization never changes the score.
    plans = [p for p in plans if p.confidence_pct >= min_confidence]
    plans.sort(key=lambda p: p.confidence_pct, reverse=True)
    return plans[:max_plans]
