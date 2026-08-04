"""Tests for the indicator suite."""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine.indicators import (
    add_all_indicators, add_rsi, add_supertrend, find_rsi_divergence,
    find_equal_levels, add_session_vwap,
)


def test_columns_added(df):
    out = add_all_indicators(df)
    for col in ("rsi", "macd", "macd_hist", "atr", "atr_pct", "bb_upper", "bb_lower",
                "supertrend", "supertrend_bull", "adx", "plus_di", "minus_di",
                "stoch_k", "stoch_d", "wt1", "wt2", "volume_ratio", "obv",
                "vwap", "price_above_vwap", "ema_20", "ema_50", "ema_200"):
        assert col in out.columns, f"missing {col}"
    assert out["close"].notna().all()


def test_rsi_bounds(df):
    out = add_rsi(df)
    rsi = out["rsi"].dropna()
    assert rsi.between(0, 100).all()
    assert rsi.iloc[-1] != 50  # not just the default fill


def test_supertrend_boolean(df):
    out = add_supertrend(df)
    assert out["supertrend_bull"].isin([True, False]).all()
    # Supertrend line must alternate sides of price coherently
    bull = out[out["supertrend_bull"]]
    assert (bull["close"] >= bull["supertrend"] * 0.999).all() or len(bull) < 5


def test_session_vwap(df):
    out = add_session_vwap(df)
    assert out["vwap"].notna().tail(10).all()
    assert out["price_above_vwap"].isin([True, False]).all()


def test_rsi_divergence_detects_structure(df):
    div = find_rsi_divergence(df)
    assert set(div.keys()) >= {"bull_div", "bear_div"}
    assert div["bull_div"] in (0, 1, 2)


def test_equal_levels(df):
    eq = find_equal_levels(df)
    assert set(eq.keys()) == {"equal_highs", "equal_lows"}
    assert all(isinstance(x, float) for x in eq["equal_highs"] + eq["equal_lows"])


def test_no_lookahead_shape(df):
    out = add_all_indicators(df)
    # indicator values at bar i must not depend on bar i+1's data:
    # recompute on truncated frame and compare the last row.
    truncated = add_all_indicators(df.iloc[:-1])
    for col in ("rsi", "macd_hist", "atr", "ema_20", "supertrend"):
        assert np.isclose(out[col].iloc[-2], truncated[col].iloc[-1], rtol=1e-6), col
