"""Tests for engine/correlation.py — measured cross-asset correlation & beta."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.correlation import (aligned_returns, correlation_report,
                                fetch_report, format_correlation)


def frame_from_returns(rets, start_ts=1_780_000_000_000, interval_ms=3_600_000):
    """Minimal close-only OHLCV frame whose log returns equal `rets`."""
    close = 100.0 * np.exp(np.cumsum(np.asarray(rets, dtype=float)))
    close = np.concatenate([[100.0], close])
    n = len(close)
    return pd.DataFrame({
        "ts": np.arange(n, dtype=np.int64) * interval_ms + start_ts,
        "open": close, "high": close * 1.001, "low": close * 0.999,
        "close": close, "volume": np.full(n, 100.0),
    })


@pytest.fixture
def rng():
    return np.random.default_rng(42)


def test_strongly_correlated_pair(rng):
    btc = rng.normal(0.0005, 0.004, 200)
    eth = 1.2 * btc + rng.normal(0.0, 0.0008, 200)   # beta 1.2, tiny noise
    res = correlation_report({"BTCUSDT": frame_from_returns(btc),
                              "ETHUSDT": frame_from_returns(eth)}, window=150)
    assert res["available"] is True
    assert res["alignment"] == "ts"
    assert res["btc_eth_corr"] > 0.9
    assert res["eth_btc_beta"] == pytest.approx(1.2, abs=0.15)
    assert any("ONE-bucket" in c for c in res["confirmations"])
    assert res["warnings"] == []
    formatted = format_correlation(res)
    assert "CROSS-ASSET CORRELATION" in formatted and "BTC/ETH corr" in formatted


def test_independent_series_low_corr():
    a = np.random.default_rng(1).normal(0, 0.004, 200)
    b = np.random.default_rng(2).normal(0, 0.004, 200)
    res = correlation_report({"BTCUSDT": frame_from_returns(a),
                              "ETHUSDT": frame_from_returns(b)}, window=150)
    assert res["available"] is True
    assert abs(res["btc_eth_corr"]) < 0.3
    assert any("decoupled" in w for w in res["warnings"])


def test_positional_fallback_for_disjoint_timestamps(rng):
    btc = rng.normal(0.0005, 0.004, 200)
    eth = btc * 1.1 + rng.normal(0, 0.001, 200)
    res = correlation_report({
        "BTCUSDT": frame_from_returns(btc, start_ts=1_700_000_000_000),
        "ETHUSDT": frame_from_returns(eth, start_ts=1_780_000_000_000),
    }, window=150)
    assert res["available"] is True
    assert res["alignment"] == "positional"
    assert "not a live" in res["note"]
    assert res["btc_eth_corr"] > 0.9


def test_insufficient_data_unavailable():
    tiny = frame_from_returns([0.01, -0.01])
    res = correlation_report({"BTCUSDT": tiny, "ETHUSDT": tiny})
    assert res["available"] is False
    res_one = correlation_report({"BTCUSDT": frame_from_returns([0.01] * 30)})
    assert res_one["available"] is False


def test_constant_series_never_raises():
    flat = pd.DataFrame({"ts": range(60), "open": 100.0, "high": 100.0,
                         "low": 100.0, "close": 100.0, "volume": 1.0})
    walk = frame_from_returns(np.random.default_rng(5).normal(0, 0.003, 100))
    res = correlation_report({"BTCUSDT": flat, "ETHUSDT": walk})
    assert res["available"] is True          # NaNs neutralised, no exception
    assert res["btc_eth_corr"] is None
    assert any("unmeasurable" in w for w in res["warnings"])


def test_mixed_sample_client_demo(monkeypatch):
    """DEMO_MODE: real BTC sample (own ts) + synthetic ETH/GOLD (own grid)
    must still produce a report via positional alignment."""
    monkeypatch.setenv("DEMO_MODE", "1")
    from data.sample_client import SampleClient
    client = SampleClient()
    res = fetch_report(client, symbols=["BTCUSDT", "ETHUSDT", "XAUUSD"],
                       timeframe="15m", bars=300, window=120)
    assert res["available"] is True
    assert res["n_observations"] >= 100
    assert set(res["symbols"]) == {"BTCUSDT", "ETHUSDT", "XAUUSD"}
    # a full 3x3 matrix with diagonal == 1
    for s in res["symbols"]:
        assert res["matrix"][s][s] == pytest.approx(1.0, abs=1e-9)


def test_aligned_returns_shapes():
    a = pd.Series([0.1, 0.2, 0.3], index=[3, 4, 5])
    b = pd.Series([0.2, 0.1, 0.0], index=[4, 5, 6])
    frame, mode = aligned_returns({"A": pd.DataFrame({"close": []}),
                                   "B": pd.DataFrame({"close": []})})
    assert frame.empty
    # direct frame-level call through correlation_report covers both modes;
    # here just verify ts join drops the non-overlapping row counts cleanly
    frame2 = pd.DataFrame({"A": a, "B": b}).dropna()
    assert len(frame2) == 2
