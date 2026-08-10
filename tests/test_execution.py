"""Tests for the execution / slippage model (engine/execution.py)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data.backtester import GradedPlan
from engine.execution import (IMPACT_K, SPREADS, adjust_for_slip, realized_rr,
                             slip_amount)


# ── slip_amount ────────────────────────────────────────────────────────────
def test_spread_only_no_impact_when_size_avg():
    slip = slip_amount("BTCUSDT", "BUY", 60000.0, 1000.0, 1000.0, 0.2)
    spread_half = 60000.0 * SPREADS["BTCUSDT"]          # 12.0
    assert slip == pytest.approx(spread_half, abs=1e-6)

def test_impact_grows_with_relative_size():
    small = slip_amount("BTCUSDT", "BUY", 60000.0, 500.0, 1000.0, 0.2)
    big   = slip_amount("BTCUSDT", "BUY", 60000.0, 2000.0, 1000.0, 0.2)
    assert big > small

def test_impact_grows_with_volatility():
    low  = slip_amount("BTCUSDT", "BUY", 60000.0, 2000.0, 1000.0, 0.1)
    high = slip_amount("BTCUSDT", "BUY", 60000.0, 2000.0, 1000.0, 0.4)
    assert high > low

def test_none_model_returns_zero():
    assert slip_amount("BTCUSDT", "BUY", 60000.0, 1000.0, 1000.0, 0.2,
                       model="none") == 0.0

def test_default_spread_for_unknown_symbol():
    slip = slip_amount("UNKNOWN", "BUY", 100.0, 100.0, 100.0, 0.2)
    assert slip == pytest.approx(100.0 * 0.001, abs=1e-6)   # default 0.1% half-spread


# ── realized_rr ────────────────────────────────────────────────────────────
def test_winner_fills_worse_than_plan():
    # BUY 100/99/102, plan +2.0R; fill at 100.05 -> +1.95R
    assert realized_rr("BUY", 100.0, 99.0, 102.0, 100.05, "FULL_WIN") == 1.95

def test_loser_fills_worse_than_minus_one():
    # BUY 100/99/102, SL hit, fill at 100.05 -> -1.05R
    assert realized_rr("BUY", 100.0, 99.0, 102.0, 100.05, "LOSS") == -1.05

def test_sell_winner():
    # SELL 100/101/98, fill at 99.95 -> +1.95R
    assert realized_rr("SELL", 100.0, 101.0, 98.0, 99.95, "FULL_WIN") == 1.95

def test_zero_risk_plan_returns_zero():
    assert realized_rr("BUY", 100.0, 100.0, 102.0, 100.05, "FULL_WIN") == 0.0


# ── adjust_for_slip (end-to-end on a GradedPlan) ──────────────────────────
def _make_window(avg_vol=1000.0, atr=0.2):
    """A forward window whose avg volume and ATR match the supplied values."""
    n = 20
    close = 100.0
    rows = {
        "open":  np.full(n, close),
        "high":  np.full(n, close * (1 + atr / 100 / 2)),
        "low":   np.full(n, close * (1 - atr / 100 / 2)),
        "close": np.full(n, close),
        "volume": np.full(n, avg_vol),
    }
    return pd.DataFrame(rows)

def test_adjust_winner_reduced():
    gp = GradedPlan(ts=0, plan_type="Sweep Reversal Buy", action="BUY",
                    confidence_pct=70, entry=100.0, trigger_level=None,
                    horizon_hours=1.0, outcome="FULL_WIN", rr_achieved=2.0,
                    max_favorable=2.0, max_adverse=0.0, regime="")
    plan = {"entry": 100.0, "stop_loss": 99.0, "take_profit": 102.0, "volume": 2000.0,
            "take_profits": [102.0]}
    df_row = {"close": 100.0}
    window = _make_window(avg_vol=1000.0, atr=0.2)
    adjust_for_slip(gp, plan, df_row, window, "BTCUSDT", "simple")
    # half-spread 0.02 + impact 0.4*1.0*(0.2/100)*100 = 0.08 -> slip 0.10
    # fill 100.10 -> reward 102-100.10 = 1.90 ; risk 1.0 -> 1.90R
    assert gp.rr_achieved == pytest.approx(1.90, abs=0.01)
    assert gp.outcome == "FULL_WIN"

def test_adjust_loser_more_negative():
    gp = GradedPlan(ts=0, plan_type="Sweep Reversal Buy", action="BUY",
                    confidence_pct=70, entry=100.0, trigger_level=None,
                    horizon_hours=1.0, outcome="LOSS", rr_achieved=-1.0,
                    max_favorable=0.0, max_adverse=1.0, regime="")
    plan = {"entry": 100.0, "stop_loss": 99.0, "volume": 2000.0,
            "take_profits": [102.0]}
    df_row = {"close": 100.0}
    window = _make_window(avg_vol=1000.0, atr=0.2)
    adjust_for_slip(gp, plan, df_row, window, "BTCUSDT", "simple")
    # fill 100.10, SL 99 -> loss 1.10 ; risk 1.0 -> -1.10R
    assert gp.rr_achieved == pytest.approx(-1.10, abs=0.01)
    assert gp.outcome == "LOSS"

def test_adjust_instant_loss_when_fill_at_stop():
    gp = GradedPlan(ts=0, plan_type="Sweep Reversal Buy", action="BUY",
                    confidence_pct=70, entry=100.0, trigger_level=None,
                    horizon_hours=1.0, outcome="FULL_WIN", rr_achieved=2.0,
                    max_favorable=2.0, max_adverse=0.0, regime="")
    plan = {"entry": 100.0, "stop_loss": 99.0, "take_profit": 102.0,
            "volume": 1_000_000.0, "take_profits": [102.0]}
    df_row = {"close": 100.0}
    window = _make_window(avg_vol=1000.0, atr=0.2)
    adjust_for_slip(gp, plan, df_row, window, "BTCUSDT", "simple")
    assert gp.outcome == "LOSS"
    assert gp.rr_achieved == -1.0

def test_adjust_no_op_for_none_model():
    gp = GradedPlan(ts=0, plan_type="Sweep Reversal Buy", action="BUY",
                    confidence_pct=70, entry=100.0, trigger_level=None,
                    horizon_hours=1.0, outcome="FULL_WIN", rr_achieved=2.0,
                    max_favorable=2.0, max_adverse=0.0, regime="")
    plan = {"entry": 100.0, "stop_loss": 99.0, "take_profit": 102.0,
            "volume": 1000.0, "take_profits": [102.0]}
    df_row = {"close": 100.0}
    window = _make_window()
    adjust_for_slip(gp, plan, df_row, window, "BTCUSDT", "none")
    assert gp.rr_achieved == 2.0
    assert gp.outcome == "FULL_WIN"

def test_adjust_open_outcome_unchanged():
    gp = GradedPlan(ts=0, plan_type="Sweep Reversal Buy", action="BUY",
                    confidence_pct=70, entry=100.0, trigger_level=None,
                    horizon_hours=1.0, outcome="OPEN", rr_achieved=0.0,
                    max_favorable=0.5, max_adverse=0.3, regime="")
    plan = {"entry": 100.0, "stop_loss": 99.0, "take_profit": 102.0,
            "volume": 1000.0, "take_profits": [102.0]}
    df_row = {"close": 100.0}
    window = _make_window()
    adjust_for_slip(gp, plan, df_row, window, "BTCUSDT", "simple")
    assert gp.outcome == "OPEN"
    assert gp.rr_achieved == 0.0
