"""engine/execution.py — realistic fill / slippage model for the simulator.

Applied as a post-grade adjustment to the backtester's GradedPlan when
EXECUTION_MODEL is set to ``"simple"``.  The default is ``"none"`` (no slip)
so the existing backtest numbers and the graduation gate stay stable; set
``EXECUTION_MODEL=simple`` in ``.env`` to enable realistic fills.

Slippage = half-spread + market impact (size / volatility dependent), applied
one-sided to the entry fill.  The stop / take-profit *touch* logic is unchanged
(it uses the price path); only the realised R is reduced by the worse fill.

Example (BUY, entry 100, SL 99, TP 102, 1R risk):
  no slip        ->  +2.00R   (plan)
  0.05 slip     ->  +1.95R   (fill 100.05, same TP)
  1.50 slip     ->  -1.00R   (slippage exceeds the 1.0 risk budget -> instant loss)
"""

from __future__ import annotations

# One-sided half-spread as a fraction of price, per symbol.  Retail-ish
# spreads for the execution timeframe; widen for lower-liquidity instruments.
SPREADS: dict[str, float] = {
    "BTCUSDT": 0.00020,     # 0.02% half-spread
    "ETHUSDT": 0.00035,     # 0.035%
    "XAUUSD":  0.00060,     # 0.06% (tokenised gold / PAXG)
}

# Market-impact coefficient: slip grows with relative size and with volatility.
IMPACT_K = 0.40


def slip_amount(symbol: str, side: str, entry: float, volume: float,
                avg_volume: float, atr_pct: float, model: str = "simple") -> float:
    """One-sided slip in price units (positive).  ``"none"`` -> 0."""
    if model != "simple":
        return 0.0
    spread_half = entry * SPREADS.get(symbol, 0.001)
    size_ratio = volume / max(avg_volume, 1.0)
    impact = IMPACT_K * max(0.0, size_ratio - 1.0) * (atr_pct / 100.0) * entry
    return spread_half + impact


def realized_rr(side: str, entry: float, sl: float, tp: float, fill_entry: float,
                outcome: str) -> float:
    """Realised R from the filled entry for a known outcome.

    R is measured against the *planned* risk (|entry - sl|).  A winner fills
    worse (less reward); a loser fills worse (more than -1R).
    """
    plan_risk = abs(entry - sl)
    if plan_risk <= 0:
        return 0.0
    if outcome in ("FULL_WIN", "PARTIAL_WIN"):
        pnl = (tp - fill_entry) if side == "BUY" else (fill_entry - tp)
    else:                                  # LOSS — SL hit
        pnl = -(fill_entry - sl) if side == "BUY" else -(sl - fill_entry)
    return round(pnl / plan_risk, 3)


def adjust_for_slip(gp, plan: dict, df_row: dict, window: pd.DataFrame,
                    symbol: str, model: str) -> None:
    """Post-grade slippage adjustment on a GradedPlan (in place).

    ``df_row`` is the signal bar; ``window`` is the forward bars used for the
    SL/TP touch test (for avg-volume / ATR estimation).
    """
    from numpy import isnan

    if model == "none":
        return
    if gp.outcome in ("OPEN", "NOT_TRIGGERED"):
        return
    entry = plan.get("entry")
    sl = plan.get("stop_loss")
    side = (plan.get("action") or "BUY").upper()
    if entry is None or sl is None:
        return

    tps = plan.get("take_profits") or []
    tp1 = tps[0] if len(tps) > 0 else None
    tp2 = tps[1] if len(tps) > 1 else None
    tp_hit = tp2 if (gp.outcome == "FULL_WIN" and tp2 is not None) else tp1

    close = float(df_row.get("close", 0) or 0)
    avg_vol = float(window["volume"].mean()) if not window.empty else close
    h = window["high"] if not window.empty else pd.Series([close])
    l = window["low"] if not window.empty else pd.Series([close])
    atr_pct = float(((h - l).mean()) / close * 100) if close else 0.0
    vol = plan.get("volume", avg_vol)
    if isnan(vol) or vol <= 0:
        vol = avg_vol

    slip = slip_amount(symbol, side, entry, vol, avg_vol, atr_pct, model)
    fill_entry = entry + slip if side == "BUY" else entry - slip
    plan_risk = abs(entry - sl)
    if plan_risk <= 0:
        return

    # Extreme slip: slippage exceeds the planned risk budget -> the fill is too
    # far from the planned entry to be viable; treat as an instant loss of the
    # risk unit (a NEGATIVE_EDGE_STAND_ASIDE style rule: don't take a trade whose
    # market impact is larger than the risk you'd put on it).
    if slip >= plan_risk:
        gp.outcome = "LOSS"
        gp.rr_achieved = -1.0
        return

    if gp.outcome == "LOSS":
        pnl = -(fill_entry - sl) if side == "BUY" else -(sl - fill_entry)
    elif gp.outcome in ("FULL_WIN", "PARTIAL_WIN") and tp_hit is not None:
        pnl = (tp_hit - fill_entry) if side == "BUY" else (fill_entry - tp_hit)
    else:
        return
    gp.rr_achieved = round(pnl / plan_risk, 3)
