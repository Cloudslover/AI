"""Shared test fixtures: deterministic synthetic OHLCV so tests run offline."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def make_ohlcv(n: int = 400, seed: int = 7, start_ts: int = 1_780_000_000_000,
               interval_ms: int = 900_000, trend: float = 0.02) -> pd.DataFrame:
    """Deterministic random-walk OHLCV with an upward drift, plus an engineered
    sell-side liquidity sweep ON THE LAST CANDLE (wick below the most recent
    fractal swing low, then a recovered close) so structure tests have a
    realistic ICT setup to find."""
    rng = np.random.default_rng(seed)
    close = np.zeros(n)
    close[0] = 60_000.0
    for i in range(1, n):
        shock = rng.normal(trend * close[i - 1] / 100, close[i - 1] * 0.004)
        close[i] = max(500, close[i - 1] + shock)
    high = close * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.002, n)))
    high = np.maximum(high, np.maximum(close, low) * 1.001)
    low = np.minimum(low, np.minimum(close, high) * 0.999)

    # Engineered sweep on the final candle against the last fractal swing low.
    from engine.structure import detect_swings
    base = pd.DataFrame({"ts": np.arange(n, dtype=np.int64) * interval_ms + start_ts,
                         "high": high, "low": low, "close": close})
    swings = detect_swings(base)
    last_lows = [s for s in swings if s.kind == "low"]
    sl = last_lows[-1]
    open_last = close[-2]
    recovered_close = open_last + sl.price * 0.004          # recovery above wick
    last_low = sl.price * 0.996                             # wick below swing low
    last_high = max(open_last, recovered_close) * 1.002
    high[-1], low[-1], close[-1] = last_high, last_low, recovered_close

    volume = rng.uniform(50, 400, n)
    volume[-1] = volume[-1] * 3  # final volume spike
    ts = np.arange(n, dtype=np.int64) * interval_ms + start_ts
    return pd.DataFrame({
        "ts": ts, "open": np.round(close, 2), "high": np.round(high, 2),
        "low": np.round(low, 2), "close": np.round(close, 2),
        "volume": np.round(volume, 2),
    })


@pytest.fixture
def df():
    return make_ohlcv()


@pytest.fixture
def df_bearish(seed: int = 3):
    """Decisive downtrend for bearish tests."""
    rng = np.random.default_rng(seed)
    n = 400
    close = np.zeros(n)
    close[0] = 60_000.0
    for i in range(1, n):
        close[i] = max(500, close[i - 1] + rng.normal(-0.08 * close[i - 1] / 100, close[i - 1] * 0.003))
    high = close * (1 + np.abs(rng.normal(0, 0.0015, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.0015, n)))
    ts = np.arange(n, dtype=np.int64) * 900_000 + 1_780_000_000_000
    return pd.DataFrame({
        "ts": ts, "open": close, "high": high, "low": low, "close": close,
        "volume": rng.uniform(50, 400, n),
    })
