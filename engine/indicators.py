"""engine/indicators.py

A dependency-light technical indicator suite used by the CryptoBrain engine.

All functions are pure (DataFrame in -> DataFrame out with extra columns) so
they are easy to unit-test and safe to reuse in backtests. Where an indicator
is inherently sequential (Supertrend, WaveTrend), it is implemented with an
explicit loop over arrays to avoid look-ahead bias.

Indicators provided
-------------------
Trend      : EMA, SMA, Supertrend, ADX(+DI/-DI), MACD
Momentum   : RSI (Wilder), Stochastic, WaveTrend (LazyBear-style), ROC
Volatility : ATR, Bollinger Bands, compression/expansion flags
Volume     : volume ratio, OBV, VWAP (session-anchored), volume profile (POC),
             volume spike detection
Divergence : RSI swing divergence (bullish/bearish, active/confirmed)
Structure  : fractal swings, equal-high/equal-low clusters (used by structure.py)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ──────────────────────────────────────────────────────────────────────────
# Trend
# ──────────────────────────────────────────────────────────────────────────

def ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def sma(s: pd.Series, period: int) -> pd.Series:
    return s.rolling(period).mean()


def add_moving_averages(df: pd.DataFrame, ema_periods=(9, 20, 50, 100, 200), sma_periods=(20, 50, 200)) -> pd.DataFrame:
    out = df.copy()
    for p in ema_periods:
        out[f"ema_{p}"] = ema(out.close, p)
    for p in sma_periods:
        out[f"sma_{p}"] = sma(out.close, p)
    return out


def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """ADX with +DI / -DI (Wilder smoothing)."""
    out = df.copy()
    up = out.high.diff()
    down = -out.low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = np.maximum(
        out.high - out.low,
        np.maximum((out.high - out.close.shift()).abs(), (out.low - out.close.shift()).abs()),
    )
    atr = pd.Series(tr, index=out.index).ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=out.index).ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=out.index).ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    out["adx"] = dx.ewm(alpha=1 / period, adjust=False).mean()
    out["plus_di"] = plus_di
    out["minus_di"] = minus_di
    return out


def add_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
    out = df.copy()
    out["macd"] = ema(out.close, fast) - ema(out.close, slow)
    out["macd_signal"] = ema(out.macd, signal)
    out["macd_hist"] = out.macd - out.macd_signal
    return out


def add_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """Supertrend with explicit arrays (no look-ahead bias)."""
    out = df.copy()
    hl2 = (out.high + out.low) / 2
    atr = true_range(out).ewm(alpha=1 / period, adjust=False).mean()
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    fu, fl = upper.to_numpy(copy=True), lower.to_numpy(copy=True)
    close = out.close.to_numpy()
    bull = np.ones(len(out), dtype=bool)
    st = np.zeros(len(out))
    for i in range(1, len(out)):
        fu[i] = upper.iloc[i] if (upper.iloc[i] < fu[i - 1] or close[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lower.iloc[i] if (lower.iloc[i] > fl[i - 1] or close[i - 1] < fl[i - 1]) else fl[i - 1]
        bull[i] = (close[i] >= fl[i]) if bull[i - 1] else (close[i] > fu[i])
        st[i] = fl[i] if bull[i] else fu[i]
    out["supertrend"] = st
    out["supertrend_bull"] = bull
    return out


# ──────────────────────────────────────────────────────────────────────────
# Momentum
# ──────────────────────────────────────────────────────────────────────────

def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    out = df.copy()
    delta = out.close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out["rsi"] = 100 - 100 / (1 + rs)
    out["rsi"] = out["rsi"].fillna(50.0)
    return out


def add_stochastic(df: pd.DataFrame, k=14, d=3, smooth=3) -> pd.DataFrame:
    out = df.copy()
    ll = out.low.rolling(k).min()
    hh = out.high.rolling(k).max()
    raw_k = 100 * (out.close - ll) / (hh - ll).replace(0, np.nan)
    out["stoch_k"] = raw_k.rolling(smooth).mean()
    out["stoch_d"] = out.stoch_k.rolling(d).mean()
    return out


def add_wavetrend(df: pd.DataFrame, channel_len=10, avg_len=21) -> pd.DataFrame:
    """LazyBear WaveTrend (WT1/WT2). Overbought > 53, oversold < -53."""
    out = df.copy()
    esa = ema(out.close, channel_len)
    de = ema((out.close - esa).abs(), channel_len)
    ci = (out.close - esa) / (0.015 * de.replace(0, np.nan))
    tci = ema(ci, avg_len)
    out["wt1"] = tci
    out["wt2"] = sma(tci, 4)
    out["wt_cross_up"] = (out.wt1 > out.wt2) & (out.wt1.shift(1) <= out.wt2.shift(1))
    out["wt_cross_dn"] = (out.wt1 < out.wt2) & (out.wt1.shift(1) >= out.wt2.shift(1))
    return out


def add_roc(df: pd.DataFrame, period: int = 10) -> pd.DataFrame:
    out = df.copy()
    out["roc"] = out.close.pct_change(period) * 100
    return out


# ──────────────────────────────────────────────────────────────────────────
# Volatility
# ──────────────────────────────────────────────────────────────────────────

def true_range(df: pd.DataFrame) -> pd.Series:
    return pd.concat(
        [df.high - df.low, (df.high - df.close.shift()).abs(), (df.low - df.close.shift()).abs()],
        axis=1,
    ).max(axis=1)


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    out = df.copy()
    tr = true_range(out)
    out["atr"] = tr.ewm(alpha=1 / period, adjust=False).mean()
    out["atr_pct"] = out.atr / out.close * 100
    return out


def add_bollinger(df: pd.DataFrame, period: int = 20, mult: float = 2.0) -> pd.DataFrame:
    out = df.copy()
    mid = sma(out.close, period)
    std = out.close.rolling(period).std()
    out["bb_mid"] = mid
    out["bb_upper"] = mid + mult * std
    out["bb_lower"] = mid - mult * std
    out["bb_width_pct"] = (out.bb_upper - out.bb_lower) / mid.replace(0, np.nan) * 100
    out["bb_compress"] = out.bb_width_pct < out.bb_width_pct.rolling(50).quantile(0.2)
    return out


# ──────────────────────────────────────────────────────────────────────────
# Volume
# ──────────────────────────────────────────────────────────────────────────

def add_volume_features(df: pd.DataFrame, volume_ma=20) -> pd.DataFrame:
    out = df.copy()
    out["volume_ma"] = sma(out.volume, volume_ma)
    out["volume_ratio"] = out.volume / out.volume_ma.replace(0, np.nan)
    out["obv"] = (np.sign(out.close.diff().fillna(0)) * out.volume).cumsum()
    out["obv_slope"] = out.obv.diff(10)
    out["delta"] = out.close - out.open
    out["body"] = (out.close - out.open).abs()
    return out


def add_session_vwap(df: pd.DataFrame, session_hours: int | None = None) -> pd.DataFrame:
    """VWAP anchored on the daily session (UTC). Bars are grouped by calendar
    date derived from the epoch-millisecond 'ts' column; each session's VWAP
    runs from the first bar of the session forward.

    Parameters
    ----------
    session_hours : optional fixed session length in hours (e.g. 4 for a 4h
        anchored VWAP). When None, a calendar-day session is used.
    """
    out = df.copy()
    if "ts" not in out.columns:
        return out
    ts = pd.to_datetime(out["ts"], unit="ms", utc=True)
    if session_hours is None:
        anchor = ts.dt.date.astype(str)
    else:
        epoch_hours = (ts.astype("int64") // 10**6 // 3600_000)
        anchor = (epoch_hours // session_hours).astype(str)
    out["session"] = anchor
    tp = (out.high + out.low + out.close) / 3
    pv = tp * out.volume
    out["vwap"] = pv.groupby(anchor).cumsum() / out.volume.groupby(anchor).cumsum().replace(0, np.nan)
    out["price_above_vwap"] = out.close > out.vwap
    return out


def add_volume_profile(df: pd.DataFrame, bins: int = 24, lookback: int = 200) -> pd.DataFrame:
    """Approximate volume profile: distribute each bar's volume uniformly
    between its high and low across a fixed price grid, then find the POC and
    high-volume nodes. Operates on the trailing `lookback` bars.
    """
    out = df.copy()
    data = out.tail(lookback).reset_index(drop=True)
    lo, hi = float(data.low.min()), float(data.high.max())
    if hi <= lo or bins < 2:
        out["poc"] = np.nan
        out["high_volume_nodes"] = np.nan
        return out
    edges = np.linspace(lo, hi, bins + 1)
    width = edges[1] - edges[0]
    profile = np.zeros(bins)
    for _, row in data.iterrows():
        if row.high <= row.low or row.volume <= 0:
            continue
        top = min(int((row.high - lo) / width), bins - 1)
        bot = max(int((row.low - lo) / width), 0)
        if top < bot:
            top, bot = bot, top
        span = max(top - bot, 1)
        profile[bot : top + 1] += row.volume / span
    poc_idx = int(np.argmax(profile))
    poc = edges[poc_idx] + width / 2
    hvn_mask = profile > np.percentile(profile[profile > 0] if (profile > 0).any() else [0], 70)
    hvn = [float(edges[i] + width / 2) for i in np.where(hvn_mask)[0]]
    out["poc"] = np.nan
    out["high_volume_nodes"] = np.nan
    out.iloc[-1, out.columns.get_loc("poc")] = poc
    out.iloc[-1, out.columns.get_loc("high_volume_nodes")] = hvn
    return out


# ──────────────────────────────────────────────────────────────────────────
# Divergence (RSI price/swing divergences)
# ──────────────────────────────────────────────────────────────────────────

def _fractals(df: pd.DataFrame, window: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """Fractal swing highs/lows: index arrays of pivot highs and pivot lows."""
    h, l = df.high.to_numpy(), df.low.to_numpy()
    highs, lows = [], []
    for i in range(window, len(df) - window):
        if h[i] == max(h[i - window : i + window + 1]) and h[i] > h[i - window]:
            highs.append(i)
        if l[i] == min(l[i - window : i + window + 1]) and l[i] < l[i - window]:
            lows.append(i)
    return np.array(highs, dtype=int), np.array(lows, dtype=int)


def find_rsi_divergence(df: pd.DataFrame, lookback: int = 80, min_swing: float = 0.15) -> dict:
    """Detect RSI swing divergence on the last `lookback` bars.

    Returns a dict with keys:
      bull_div  : 0 none, 1 active (unconfirmed), 2 confirmed
      bear_div  : same
      bull_price_low / bull_rsi_low : reference levels of the last bullish setup
      bear_price_high / bear_rsi_high : reference levels of the last bearish setup
    """
    result = {
        "bull_div": 0, "bear_div": 0,
        "bull_price_low": None, "bull_rsi_low": None,
        "bear_price_high": None, "bear_rsi_high": None,
    }
    if df is None or len(df) < 40 or "rsi" not in df.columns:
        return result
    data = df.tail(lookback).reset_index(drop=True)
    prices, rsis = data.close.to_numpy(), data.rsi.to_numpy()
    hi_idx, lo_idx = _fractals(data)
    if len(lo_idx) < 2:
        return result

    def pct(a, b):
        return abs(a - b) / b * 100 if b else 0.0

    # Bullish divergence: price makes lower low, RSI makes higher low.
    for j in range(len(lo_idx) - 1, 0, -1):
        i1, i2 = lo_idx[j - 1], lo_idx[j]
        if pct(prices[i1], prices[i2]) < min_swing or pct(rsis[i1], rsis[i2]) < 1.5:
            continue
        if prices[i2] < prices[i1] and rsis[i2] > rsis[i1]:
            confirmed = i2 <= len(data) - 3 and prices[i2] == data.low.tail(len(data) - i2).min()
            result["bull_div"] = 2 if confirmed else 1
            result["bull_price_low"] = float(prices[i2])
            result["bull_rsi_low"] = float(rsis[i2])
            break

    if len(hi_idx) >= 2:
        for j in range(len(hi_idx) - 1, 0, -1):
            i1, i2 = hi_idx[j - 1], hi_idx[j]
            if pct(prices[i1], prices[i2]) < min_swing or pct(rsis[i1], rsis[i2]) < 1.5:
                continue
            if prices[i2] > prices[i1] and rsis[i2] < rsis[i1]:
                confirmed = i2 <= len(data) - 3 and prices[i2] == data.high.tail(len(data) - i2).max()
                result["bear_div"] = 2 if confirmed else 1
                result["bear_price_high"] = float(prices[i2])
                result["bear_rsi_high"] = float(rsis[i2])
                break
    return result


def find_equal_levels(df: pd.DataFrame, lookback: int = 120, tolerance_pct: float = 0.12) -> dict:
    """Cluster swing highs/lows that are within `tolerance_pct` of each other —
    the classic 'equal highs' / 'equal lows' liquidity pools."""
    result = {"equal_highs": [], "equal_lows": []}
    data = df.tail(lookback).reset_index(drop=True)
    hi_idx, lo_idx = _fractals(data)
    h = data.high.to_numpy()[hi_idx]
    l = data.low.to_numpy()[lo_idx]

    def clusters(values):
        groups = []
        for v in sorted(values):
            placed = False
            for g in groups:
                if abs(g[0] - v) / v * 100 <= tolerance_pct:
                    g.append(v)
                    placed = True
                    break
            if not placed:
                groups.append([v])
        return [float(np.mean(g)) for g in groups if len(g) >= 2]

    result["equal_highs"] = clusters(h.tolist())
    result["equal_lows"] = clusters(l.tolist())
    return result


# ──────────────────────────────────────────────────────────────────────────

def add_all_indicators(df: pd.DataFrame, session_hours: int | None = None) -> pd.DataFrame:
    """Convenience: run the whole suite. `session_hours` optionally fixes the
    VWAP anchor length (e.g. 24 for daily-anchored on any timeframe)."""
    out = df.copy()
    out = add_moving_averages(out)
    out = add_rsi(out)
    out = add_macd(out)
    out = add_atr(out)
    out = add_bollinger(out)
    out = add_supertrend(out)
    out = add_adx(out)
    out = add_stochastic(out)
    out = add_wavetrend(out)
    out = add_roc(out)
    out = add_volume_features(out)
    out = add_session_vwap(out, session_hours=session_hours)
    return out
