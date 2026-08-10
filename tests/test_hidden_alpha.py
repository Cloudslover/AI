"""Tests for the hidden alpha layer (engine/hidden_alpha.py).

Four technologies: latent regime probabilities (HMM-style), order-flow CVD +
absorption, Bayesian fractional Kelly sizing, and 8D state fingerprints with
similarity search.  Fully offline with deterministic synthetic frames.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ── deterministic synthetic frames ────────────────────────────────────────
def clean_trend(n: int = 400, drift: float = 0.005, seed: int = 7) -> pd.DataFrame:
    """Clean drift + noise series (no engineered sweeps)."""
    rng = np.random.default_rng(seed)
    c = np.zeros(n)
    c[0] = 100.0
    for i in range(1, n):
        c[i] = c[i - 1] * (1 + rng.normal(drift, 0.004))
    return pd.DataFrame({"ts": np.arange(n) * 900_000, "open": c,
                         "high": c * 1.004, "low": c * 0.996,
                         "close": c, "volume": np.full(n, 100.0)})

def range_frame(n: int = 400, seed: int = 1) -> pd.DataFrame:
    """White noise around a fixed mean: returns are MA(1) with ac(lag1) ~ -0.5,
    the textbook mean-reverting signature."""
    rng = np.random.default_rng(seed)
    close = 100.0 + rng.normal(0, 0.8, n)
    return pd.DataFrame({"ts": np.arange(n) * 900_000, "open": close,
                         "high": close + 0.4, "low": close - 0.4,
                         "close": close, "volume": np.full(n, 100.0)})

def expansion_frame(n: int = 400, seed: int = 9) -> pd.DataFrame:
    """First half normal, second half a 5x-volatility expansion with wide bars."""
    base = clean_trend(n=n, drift=0.0, seed=5)
    c = base["close"].astype(float).to_numpy().copy()
    rng = np.random.default_rng(seed)
    c[-n // 2:] = c[-n // 2 - 1] * np.cumprod(1 + rng.normal(0, 0.02, n // 2))
    h = c.copy()
    l = c.copy()
    h[-n // 2:] = c[-n // 2:] * 1.02
    l[-n // 2:] = c[-n // 2:] * 0.98
    h[:n // 2] = c[:n // 2] * 1.004
    l[:n // 2] = c[:n // 2] * 0.996
    return pd.DataFrame({"ts": base["ts"], "open": c, "high": h, "low": l,
                         "close": c, "volume": np.full(n, 100.0)})

def _probs(r: dict) -> dict:
    return {k: r[k] for k in ("bull_trend", "bear_trend", "mean_reverting",
                              "volatile_expansion")}

# ── 1. latent regime probabilities ────────────────────────────────────────
def test_regime_bull_dominant():
    from engine.hidden_alpha import regime_probabilities
    r = regime_probabilities(clean_trend(drift=+0.005))
    assert r["dominant"] == "bull_trend"
    assert r["bull_trend"] >= 0.5

def test_regime_bear_dominant():
    from engine.hidden_alpha import regime_probabilities
    r = regime_probabilities(clean_trend(drift=-0.005, seed=3))
    assert r["dominant"] == "bear_trend"
    assert r["bear_trend"] >= 0.5

def test_regime_mean_reverting_dominant():
    from engine.hidden_alpha import regime_probabilities
    r = regime_probabilities(range_frame())
    assert r["dominant"] == "mean_reverting"
    assert r["mean_reverting"] >= 0.5

def test_regime_volatile_expansion_dominant_and_lift():
    from engine.hidden_alpha import regime_probabilities
    calm = regime_probabilities(clean_trend(drift=0.0, seed=5))
    exp = regime_probabilities(expansion_frame())
    assert exp["dominant"] == "volatile_expansion"
    assert exp["volatile_expansion"] >= 0.5
    assert calm["volatile_expansion"] < 0.05
    assert exp["volatile_expansion"] > 10 * calm["volatile_expansion"]

def test_regime_probabilities_sum_to_one_and_deterministic():
    from engine.hidden_alpha import regime_probabilities
    df = clean_trend()
    r1 = regime_probabilities(df)
    r2 = regime_probabilities(df)
    assert r1 == r2
    assert round(sum(_probs(r1).values()), 4) == 1.0
    assert set(_probs(r1)) == {"bull_trend", "bear_trend", "mean_reverting",
                               "volatile_expansion"}
    assert r1["dominant"] in _probs(r1)

def test_regime_short_frame_neutral():
    from engine.hidden_alpha import regime_probabilities
    r = regime_probabilities(clean_trend(n=10))
    assert round(sum(_probs(r).values()), 4) == 1.0
    assert r["dominant"] == "mean_reverting"   # neutral fallback

# ── 2. order flow / microstructure ────────────────────────────────────────
def _flow_frame() -> pd.DataFrame:
    """50 slightly-down bars, 5 heavy sell bars, then (LAST bar) a wide-range
    absorption candle: huge volume, tiny body, close >= open."""
    n = 56
    ts = np.arange(n) * 900_000
    o = np.full(n, 100.0)
    h = np.full(n, 101.0)
    l = np.full(n, 99.0)
    c = np.full(n, 99.99)                        # close < open: sell-side bars
    v = np.full(n, 1000.0)
    for i in range(50, 55):                      # heavy sell bars
        o[i], h[i], l[i], c[i] = 100.0, 100.5, 97.5, 98.0
        v[i] = 1000.0
    # last bar: absorption — huge volume, tiny body, close >= open
    o[55], h[55], l[55], c[55], v[55] = 100.0, 100.3, 99.9, 100.05, 5000.0
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": l,
                         "close": c, "volume": v})

def test_cvd_negative_on_sell_pressure():
    from engine.hidden_alpha import cvd_analysis
    a = cvd_analysis(_flow_frame())
    assert a["available"] is True
    assert a["cvd"] < 0
    assert a["buy_pressure"] < 0.5 < a["sell_pressure"]
    assert a["delta_last"] > 0          # last bar = the bullish absorption candle

def test_absorption_detected_on_high_volume_narrow_bar():
    from engine.hidden_alpha import cvd_analysis
    a = cvd_analysis(_flow_frame())
    assert a["absorption"] is True
    assert a["absorption_direction"] == "bullish"
    assert a["volume_z"] >= 1.5

def test_no_absorption_on_normal_bars():
    from engine.hidden_alpha import cvd_analysis
    a = cvd_analysis(clean_trend())
    assert a["absorption"] is False
    assert a["absorption_direction"] is None

# ── 3. Bayesian fractional Kelly sizing ───────────────────────────────────
def test_kelly_math_known_values():
    from engine.hidden_alpha import kelly_size
    k = kelly_size(0.6, 2.0)            # edge 0.8, full Kelly 0.4
    assert k["edge"] == 0.8
    assert k["full_kelly"] == 0.4
    assert k["stand_aside"] is False
    assert k["suggested_risk_pct"] == 1.0    # 10% fractional, clamped to cap

def test_kelly_stand_aside_on_negative_edge():
    from engine.hidden_alpha import kelly_size
    k = kelly_size(0.4, 1.0)            # edge -0.2
    assert k["stand_aside"] is True
    assert k["suggested_risk_pct"] == 0.0
    assert k["full_kelly"] == 0.0

def test_kelly_insufficient_evidence():
    from engine.hidden_alpha import kelly_size
    k = kelly_size(None, None)
    assert k["suggested_risk_pct"] is None
    assert k["stand_aside"] is False          # unknown != negative edge

def test_bayesian_win_rate_weak_prior():
    from engine.hidden_alpha import bayesian_win_rate
    p, n = bayesian_win_rate(2, 0)       # 2-0 would be 100% raw; prior keeps it sane
    assert n == 2
    assert p == round((2 + 2) / (2 + 0 + 4), 4)   # 0.6667
    assert 0 < p < 1.0

def test_kelly_from_stats():
    from engine.hidden_alpha import kelly_from_stats
    k = kelly_from_stats(60, 40, 2.0, 1.0)
    assert k["n"] == 100
    assert k["win_rate"] == round(62 / 104, 4)    # beta posterior
    assert k["payoff"] == 2.0
    assert k["edge"] > 0
    assert k["stand_aside"] is False

def test_kelly_from_progress_aggregates():
    from engine.hidden_alpha import kelly_from_progress
    rows = [
        {"plan_type": "A", "wins": 30, "losses": 20, "win_r": 60.0, "loss_r": 20.0},
        {"plan_type": "B", "wins": 30, "losses": 20, "win_r": 60.0, "loss_r": 20.0},
    ]
    k = kelly_from_progress(rows)
    assert k["n"] == 100
    assert k["payoff"] == 2.0              # avg win R 2.0 / avg loss R 1.0
    assert k["plan_types"] == ["A", "B"]
    k2 = kelly_from_progress(rows, plan_types=["A"])
    assert k2["n"] == 50

# ── 4. 8D state fingerprints + similarity ─────────────────────────────────
def test_state_vector_shape_and_determinism():
    from engine.hidden_alpha import state_vector
    df = clean_trend()
    v1 = state_vector(df)
    v2 = state_vector(df)
    assert v1["available"] is True
    assert len(v1["vector"]) == 8
    assert len(v1["names"]) == 8
    assert v1 == v2
    assert all(np.isfinite(x) and -1.0 <= x <= 1.0 for x in v1["vector"])

def test_state_vectors_rows_finite():
    from engine.hidden_alpha import state_vectors
    sv = state_vectors(clean_trend())
    assert sv.shape[1] == 8
    assert sv.shape[0] == 400
    assert np.isfinite(sv.to_numpy()).all()

def test_similar_states_returns_matches_with_forward_stats():
    from engine.hidden_alpha import similar_states
    df = clean_trend()
    sim = similar_states(df, k=5, horizon=24)
    assert sim["available"] is True
    assert len(sim["matches"]) == 5
    m = sim["matches"][0]
    assert {"index", "distance", "forward_return_pct", "forward_vol_pct"} <= set(m)
    assert sim["stats"]["n"] == 5
    assert 0.0 <= sim["stats"]["win_rate_forward"] <= 1.0
    assert similar_states(df, k=5, horizon=24) == sim

# ── combined report ────────────────────────────────────────────────────────
def test_hidden_alpha_report_shape():
    from engine.hidden_alpha import hidden_alpha_report
    r = hidden_alpha_report(clean_trend(), "BTCUSDT", "15m", with_kelly=False)
    assert r["available"] is True
    assert r["symbol"] == "BTCUSDT" and r["timeframe"] == "15m"
    assert set(r) >= {"regime", "cvd", "state_vector", "similar_states"}
    assert r["regime"]["dominant"] == "bull_trend"

def test_hidden_alpha_report_short_frame():
    from engine.hidden_alpha import hidden_alpha_report
    r = hidden_alpha_report(clean_trend(n=10), "BTCUSDT", "15m", with_kelly=False)
    assert r["available"] is False
    assert "note" in r
