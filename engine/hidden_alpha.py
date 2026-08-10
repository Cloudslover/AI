"""engine/hidden_alpha.py — the hidden alpha layer.

Four institutional-grade quantitative technologies, implemented in pure
numpy/pandas (no new dependencies), deterministic and fully testable:

  1. Latent regime probability estimation (HMM-style)
     Soft Gaussian classification over (trend, volatility, autocorrelation,
     bandwidth, joint vol+bw expansion) smoothed by a Markov transition prior
     -> P over four latent regimes: BULL_TREND, BEAR_TREND, MEAN_REVERTING,
     VOLATILE_EXPANSION.  Static hard regime labels fail when markets
     transition; this layer reports the *probability* of each latent state.

  2. Order flow & microstructure (CVD + absorption/exhaustion)
     Proxy cumulative volume delta (volume x directional body fraction),
     buy/sell pressure, institutional absorption (large volume absorbed on a
     narrow range) and exhaustion (large volume, long wick against the trend).

  3. Bayesian fractional Kelly position sizing
     Win rate = beta posterior (weak prior, so low-sample estimates stay
     neutral), payoff = avg win R / |avg loss R| from decided samples,
     f* = (p.b - (1-p)) / b, scaled by a fraction and clamped to a risk cap.
     Negative edge => stand aside (0.0 risk) — NEGATIVE_EDGE_STAND_ASIDE.
     Advisory by default: the enforced progression caps never change.

  4. High-dimensional state fingerprinting
     An 8D normalized vector (return z, vol z, volume z, skew z, bandwidth z,
     trend-slope z, CVD z, mean-reverting probability) plus historical
     similarity search with forward-return statistics — "have we been here
     before, and what happened next?"

Performance: the per-bar feature matrix is fully vectorized (pandas rolling)
and the Markov forward pass is one O(n) numpy loop, so the layer stays cheap
enough for per-window use inside the simulator grind.

Every public function guards on short/empty frames and returns neutral values
rather than raising, so the layer can never break the engine.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# ── tunables (local so the module stays self-contained) ───────────────────
WINDOW = 20          # trailing feature window (bars)
HISTORY = 100        # trailing history for z-score / ratio normalisation
PERSISTENCE = 0.65   # HMM-style transition prior (self-persistence)

REGIME_KEYS = ("bull_trend", "bear_trend", "mean_reverting", "volatile_expansion")

REGIME_LABELS = {
    "bull_trend": "Low-volatility directional upward drift",
    "bear_trend": "High-volatility downward pressure",
    "mean_reverting": "Negative return autocorrelation (sweep-reversal friendly)",
    "volatile_expansion": "High-volatility range breakout / volatility squeeze",
}

# emission means per latent regime over (trend, vol, ac, bw, exp).
# Features are tanh-saturated to [-1, 1] (see _emission_matrix).  The 5th
# dim is the JOINT vol+bw expansion factor, so a wide-bar volatility
# expansion cannot be confused with a high-vol bear trend.
EMISSION_MEANS: dict[str, np.ndarray] = {
    "bull_trend":         np.array([0.6, -0.3, 0.0, -0.2, 0.0]),
    "bear_trend":         np.array([-0.6, 0.4, 0.0, 0.3, 0.0]),
    "mean_reverting":     np.array([0.0, -0.3, -0.6, -0.3, 0.0]),
    "volatile_expansion": np.array([0.0, 0.8, 0.2, 0.8, 1.0]),
}
EMISSION_SIGMA = np.array([0.55, 0.55, 0.55, 0.55, 0.45])
_STATES = list(REGIME_KEYS)

# ── helpers ───────────────────────────────────────────────────────────────
def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    try:
        return float(a / b) if b else default
    except (TypeError, ValueError, ZeroDivisionError):
        return default

def _volume_delta(df: pd.DataFrame) -> np.ndarray:
    """Per-bar proxy delta: volume x directional body fraction in [-1, 1]."""
    o = df["open"].astype(float).to_numpy()
    h = df["high"].astype(float).to_numpy()
    l = df["low"].astype(float).to_numpy()
    c = df["close"].astype(float).to_numpy()
    v = df["volume"].astype(float).to_numpy()
    rng = h - l
    frac = np.zeros_like(c)
    pos = rng > 0
    frac[pos] = (c[pos] - o[pos]) / rng[pos]
    frac = np.clip(frac, -1.0, 1.0)
    return v * frac

def _zscore(x: np.ndarray) -> np.ndarray:
    """z-score of a trailing series; zeros when flat (std ~ 0)."""
    if x is None or len(x) < 2:
        return np.zeros_like(x, dtype=float) if x is not None else np.array([])
    x = np.asarray(x, dtype=float)
    sd = x.std()
    if sd == 0 or not np.isfinite(sd):
        return np.zeros_like(x)
    return (x - x.mean()) / sd

# ── 1. latent regime probabilities ────────────────────────────────────────
def _emission_matrix(df: pd.DataFrame, window: int = WINDOW,
                     history: int = HISTORY) -> np.ndarray:
    """(n, 5) emission features for every bar — vectorised rolling.

    All five features are tanh-saturated to [-1, 1] so a single anomalous bar
    cannot dominate the soft classifier:

      trend — saturating t-statistic of the window return vs the CURRENT bar
              volatility: strongly + in a steady uptrend, - in a downtrend,
              ~0 in a range.  (Normalising by the current vol keeps a
              random-walk vol expansion from looking like a trend.)

      vol   — RELATIVE volatility expansion vs the long baseline
              ((vol20 - vol_long) / vol_long): ~0 in a steady regime,
              strongly + when volatility expands.

      ac    — lag-1 return autocorrelation, scaled x2 and saturated;
              strongly - for mean-reverting price action.

      bw    — RELATIVE bandwidth expansion ((bw20 - bw_long) / bw_long), the
              range/volatility-compression counterpart of vol.

      exp   — JOINT vol+bw expansion factor (sum of both relative expansions),
              the distinctive signature of a volatility expansion / squeeze
              release.
    """
    n = len(df)
    em = np.zeros((n, 5))
    if n < window + 4:
        return em

    c = df["close"].astype(float)
    rets = c.pct_change()
    long = max(history, min(500, n))          # long baseline = the whole frame

    ret_win = rets.rolling(window).sum()
    vol20 = rets.rolling(window).std()

    # trend: window return vs CURRENT vol (so vol expansions don't fake a trend)
    trend = np.tanh(ret_win / (vol20.replace(0, np.nan) * np.sqrt(window)))

    vol_long = rets.rolling(long, min_periods=2).std()
    vol = np.tanh((vol20 - vol_long) / vol_long.replace(0, np.nan) * 1.2)

    def _ac(a: np.ndarray) -> float:
        if len(a) < 4:
            return 0.0
        x, y = a[:-1], a[1:]
        sx, sy = x.std(), y.std()
        if sx == 0 or sy == 0:
            return 0.0
        return float(((x - x.mean()) * (y - y.mean())).mean() / (sx * sy))

    ac = np.tanh(rets.rolling(window).apply(_ac, raw=True).fillna(0.0) * 2.0)

    rng = (df["high"].astype(float) - df["low"].astype(float)) / c
    bw20 = rng.rolling(window).mean()
    bw_long = rng.rolling(long, min_periods=2).mean()
    rel_bw = (bw20 - bw_long) / bw_long.replace(0, np.nan)
    bw = np.tanh(rel_bw * 1.2)

    rel_vol = (vol20 - vol_long) / vol_long.replace(0, np.nan)
    exp = np.tanh((rel_vol + rel_bw).clip(lower=-1.0))

    em[:, 0] = trend.fillna(0.0).to_numpy()
    em[:, 1] = vol.fillna(0.0).to_numpy()
    em[:, 2] = ac.fillna(0.0).to_numpy()
    em[:, 3] = bw.fillna(0.0).to_numpy()
    em[:, 4] = exp.fillna(0.0).to_numpy()
    return em

def _emission_scores(feat: np.ndarray) -> np.ndarray:
    """Unnormalised Gaussian emission scores for one feature vector."""
    scores = np.empty(len(_STATES), dtype=float)
    for k, key in enumerate(_STATES):
        d = feat - EMISSION_MEANS[key]
        scores[k] = float(np.exp(-0.5 * float(((d * d) / (EMISSION_SIGMA ** 2)).sum())))
    return scores

def _forward_probs(em: np.ndarray) -> np.ndarray:
    """Markov forward pass: (n, 4) smoothed regime probabilities."""
    n = len(em)
    out = np.zeros((n, len(_STATES)), dtype=float)
    probs = np.full(len(_STATES), 1.0 / len(_STATES))
    stationary = probs.copy()
    for t in range(n):
        if t > WINDOW:
            prior = PERSISTENCE * probs + (1.0 - PERSISTENCE) * stationary
            probs = prior * _emission_scores(em[t])
            s = probs.sum()
            if s > 0:
                probs = probs / s
        out[t] = probs
    return out

def regime_probabilities(df: pd.DataFrame, i: Optional[int] = None) -> dict:
    """Probability over the 4 latent regimes at bar ``i`` (default: last).

    Emissions are smoothed by a Markov persistence prior (forward pass), so
    the probabilities are stable across bars — a regime does not flicker on a
    single candle.  Probabilities always sum to 1.0.
    """
    if df is None or len(df) < WINDOW + 4:
        return _neutral_regime("insufficient data")
    n = len(df)
    idx = n - 1 if i is None else max(0, min(i, n - 1))
    probs = _forward_probs(_emission_matrix(df))[idx]
    result = {k: round(float(p), 4) for k, p in zip(_STATES, probs)}
    dom = _STATES[int(np.argmax(probs))]
    result["dominant"] = dom
    result["label"] = REGIME_LABELS[dom]
    return result

def _neutral_regime(reason: str) -> dict:
    p = 1.0 / len(_STATES)
    result = {k: p for k in _STATES}
    result["dominant"] = "mean_reverting"
    result["label"] = f"Neutral ({reason})"
    return result

# ── 2. order flow / microstructure ────────────────────────────────────────
def cvd_analysis(df: pd.DataFrame, i: Optional[int] = None,
                 history: int = HISTORY) -> dict:
    """Cumulative volume delta + absorption/exhaustion at bar ``i``."""
    if df is None or len(df) < 30:
        return {"available": False, "note": "insufficient data"}
    n = len(df)
    idx = n - 1 if i is None else max(0, min(i, n - 1))
    delta = _volume_delta(df)
    cvd = np.cumsum(delta)
    hist = cvd[max(0, idx - history):idx + 1]
    cvd_z = float(_zscore(hist)[-1]) if len(hist) > 2 else 0.0

    o = df["open"].astype(float).to_numpy()
    h = df["high"].astype(float).to_numpy()
    l = df["low"].astype(float).to_numpy()
    c = df["close"].astype(float).to_numpy()
    v = df["volume"].astype(float).to_numpy()
    rng = np.maximum(h - l, 1e-9)
    body_ratio = np.abs(c - o) / rng

    vol_hist = v[max(0, idx - history):idx + 1]
    vol_z = float(_zscore(vol_hist)[-1]) if len(vol_hist) > 2 else 0.0

    w = df.iloc[max(0, idx - WINDOW):idx + 1]
    buy_vol = float(w.loc[w["close"] >= w["open"], "volume"].sum())
    total = float(w["volume"].sum()) or 1e-9
    buy_pressure = round(buy_vol / total, 3)

    upper_wick = h[idx] - np.maximum(o[idx], c[idx])
    lower_wick = np.minimum(o[idx], c[idx]) - l[idx]
    body = abs(c[idx] - o[idx])

    absorption = bool(vol_z >= 1.5 and body_ratio[idx] <= 0.3)
    absorption_direction = None
    if absorption:
        absorption_direction = "bullish" if c[idx] >= o[idx] else "bearish"

    exhaustion = bool(vol_z >= 1.5 and body > 0
                      and (upper_wick >= 2 * body or lower_wick >= 2 * body))
    exhaustion_direction = None
    if exhaustion:
        exhaustion_direction = ("bearish" if upper_wick >= 2 * body
                                else "bullish")

    return {
        "available": True,
        "cvd": round(float(cvd[idx]), 2),
        "cvd_z": round(cvd_z, 3),
        "delta_last": round(float(delta[idx]), 2),
        "volume_z": round(vol_z, 3),
        "buy_pressure": buy_pressure,
        "sell_pressure": round(1 - buy_pressure, 3),
        "absorption": absorption,
        "absorption_direction": absorption_direction,
        "exhaustion": exhaustion,
        "exhaustion_direction": exhaustion_direction,
    }

# ── 3. Bayesian fractional Kelly sizing ───────────────────────────────────
def bayesian_win_rate(wins: int, losses: int,
                      prior_a: float = 2.0, prior_b: float = 2.0):
    """Beta-posterior win rate: (wins + a) / (n + a + b).

    The weak prior (a=b=2, mean 0.5) keeps low-sample estimates neutral
    instead of jumping to 100%/0% after a couple of trades.
    """
    n = int(wins) + int(losses)
    if n <= 0:
        return None, 0
    p = (wins + prior_a) / (n + prior_a + prior_b)
    return round(float(p), 4), n

def kelly_size(win_rate: Optional[float], payoff: Optional[float],
               fraction: float = 0.25, max_risk: float = 1.0) -> dict:
    """Fractional Kelly size as % of capital risked per trade.

    f* = (p.b - (1-p)) / b ;  edge = p.b - (1-p).
    Negative edge => stand aside (0.0 risk) — NEGATIVE_EDGE_STAND_ASIDE.
    Unknown edge (no samples) => no suggestion (None), never a forced block.
    """
    if win_rate is None or payoff is None or payoff <= 0:
        return {"edge": None, "full_kelly": None, "suggested_risk_pct": None,
                "stand_aside": False, "note": "insufficient evidence"}
    p = float(win_rate)
    b = float(payoff)
    edge = p * b - (1.0 - p)
    if edge <= 0:
        return {"edge": round(edge, 4), "full_kelly": 0.0,
                "suggested_risk_pct": 0.0, "stand_aside": True,
                "note": "negative edge — stand aside (0.0% risk)"}
    full = edge / b
    frac = full * fraction
    suggested = min(frac * 100.0, max_risk)
    return {"edge": round(edge, 4), "full_kelly": round(full, 4),
            "suggested_risk_pct": round(suggested, 3), "stand_aside": False,
            "note": "fractional Kelly, clamped to the risk cap"}

def kelly_from_stats(wins: int, losses: int, avg_win_r: Optional[float],
                     avg_loss_r: Optional[float], fraction: float = 0.25,
                     max_risk: float = 1.0) -> dict:
    """Kelly from decided-sample statistics (R-based)."""
    p, n = bayesian_win_rate(wins, losses)
    if n == 0:
        return kelly_size(None, None, fraction, max_risk)
    payoff = None
    if avg_win_r is not None and avg_loss_r:
        payoff = float(avg_win_r) / abs(float(avg_loss_r))
    out = kelly_size(p, payoff, fraction, max_risk)
    out["wins"] = int(wins)
    out["losses"] = int(losses)
    out["n"] = n
    out["win_rate"] = p
    out["payoff"] = round(payoff, 3) if payoff is not None else None
    return out

def kelly_from_progress(progress: list[dict], plan_types=None,
                        fraction: float = 0.25, max_risk: float = 1.0) -> dict:
    """Kelly from simulator progress rows (paper_progress output).

    Aggregates wins/losses/win R/loss R over ``plan_types`` (default: all
    rows given) — the same deduped samples the graduation gate uses.
    """
    rows = [p for p in progress
            if plan_types is None or p["plan_type"] in set(plan_types)]
    if not rows:
        return kelly_size(None, None, fraction, max_risk)
    wins = sum(p["wins"] for p in rows)
    losses = sum(p["losses"] for p in rows)
    win_r = sum(p.get("win_r") or 0.0 for p in rows)
    loss_r = sum(p.get("loss_r") or 0.0 for p in rows)
    avg_win_r = _safe_div(win_r, wins) if wins else None
    avg_loss_r = _safe_div(loss_r, losses) if losses else None
    out = kelly_from_stats(wins, losses, avg_win_r, avg_loss_r,
                           fraction=fraction, max_risk=max_risk)
    out["plan_types"] = [p["plan_type"] for p in rows]
    out["avg_win_r"] = round(avg_win_r, 3) if avg_win_r is not None else None
    out["avg_loss_r"] = round(avg_loss_r, 3) if avg_loss_r is not None else None
    return out

# ── 4. 8D state vector + similarity search ────────────────────────────────
STATE_DIM_NAMES = ("return_z", "vol_z", "volume_z", "skew_z", "bandwidth_z",
                   "trend_slope_z", "cvd_z", "mean_reverting_p")

def state_vectors(df: pd.DataFrame, window: int = WINDOW,
                  history: int = HISTORY) -> pd.DataFrame:
    """8D normalized state vectors for every bar (vectorised, [-1, 1])."""
    n = len(df)
    if n < window + 4:
        return pd.DataFrame({name: pd.Series(dtype=float) for name in STATE_DIM_NAMES})
    c = df["close"].astype(float)
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    v = df["volume"].astype(float)
    rets = c.pct_change()

    vol = rets.rolling(window).std()
    ret_win = rets.rolling(window).sum()
    volume_z = (v - v.rolling(history).mean()) / v.rolling(history).std()
    skew = rets.rolling(window).skew()
    bw = ((h - l) / c).rolling(window).mean()
    ema5 = c.ewm(span=5, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    slope = (ema5 - ema20) / c
    cvd = pd.Series(np.cumsum(_volume_delta(df)), index=df.index)
    cvd_z = (cvd - cvd.rolling(history).mean()) / cvd.rolling(history).std()

    def _z(series: pd.Series, win: int) -> pd.Series:
        m = series.rolling(win, min_periods=2).mean()
        s = series.rolling(win, min_periods=2).std()
        return ((series - m) / s.replace(0, np.nan)).fillna(0.0)

    out = pd.DataFrame({
        "return_z": _z(ret_win, history),
        "vol_z": _z(vol, history),
        "volume_z": volume_z.replace([np.inf, -np.inf], np.nan).fillna(0.0),
        "skew_z": _z(skew, history),
        "bandwidth_z": _z(bw, history),
        "trend_slope_z": _z(slope, history),
        "cvd_z": cvd_z.replace([np.inf, -np.inf], np.nan).fillna(0.0),
        "mean_reverting_p": 0.0,
    })
    out = out.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    # dim 8: mean-reverting latent probability mapped to [-1, 1] (one pass)
    em = _emission_matrix(df, window, history)
    fp = _forward_probs(em)
    out["mean_reverting_p"] = (2.0 * fp[:, 3] - 1.0)

    return np.tanh(out).round(4)

def state_vector(df: pd.DataFrame, i: Optional[int] = None) -> dict:
    """The 8D fingerprint at bar ``i`` (default: last)."""
    sv = state_vectors(df)
    if sv.empty:
        return {"vector": [0.0] * 8, "names": list(STATE_DIM_NAMES),
                "available": False}
    idx = len(sv) - 1 if i is None else min(i, len(sv) - 1)
    vec = [round(float(x), 4) for x in sv.iloc[idx].tolist()]
    return {"vector": vec, "names": list(STATE_DIM_NAMES),
            "index": idx, "available": True}

def similar_states(df: pd.DataFrame, i: Optional[int] = None, k: int = 5,
                   horizon: int = 24, window: int = WINDOW) -> dict:
    """Nearest historical state fingerprints + what happened next.

    Each match reports the euclidean distance to the current 8D vector and the
    forward return / volatility over ``horizon`` bars.  The aggregate tells you
    how the market behaved after *similar* conditions.
    """
    sv = state_vectors(df)
    n = len(df)
    if sv.empty or n < window + horizon + 2:
        return {"available": False, "note": "insufficient data"}
    idx = n - 1 if i is None else min(i, n - 1)
    cur = sv.iloc[idx].to_numpy(dtype=float)
    closes = df["close"].astype(float).to_numpy()
    rets = df["close"].astype(float).pct_change().to_numpy()
    matches = []
    for j in range(window, n - horizon):
        if abs(j - idx) <= horizon:
            continue                      # skip self and the overlap window
        d = float(np.sqrt(((sv.iloc[j].to_numpy(dtype=float) - cur) ** 2).sum()))
        fwd = (closes[j + horizon] / closes[j] - 1.0) * 100.0
        fwd_vol = float(rets[j:j + horizon].std() * 100.0)
        matches.append({"index": j, "distance": round(d, 4),
                        "forward_return_pct": round(fwd, 3),
                        "forward_vol_pct": round(fwd_vol, 3)})
    matches.sort(key=lambda m: m["distance"])
    top = matches[:k]
    if not top:
        return {"available": False, "note": "no comparable windows"}
    fwds = [m["forward_return_pct"] for m in top]
    stats = {
        "n": len(top),
        "mean_forward_return_pct": round(float(np.mean(fwds)), 3),
        "median_forward_return_pct": round(float(np.median(fwds)), 3),
        "win_rate_forward": round(sum(1 for f in fwds if f > 0) / len(fwds), 3),
    }
    return {"available": True, "current_index": idx, "horizon": horizon,
            "matches": top, "stats": stats}

# ── combined report (CLI / intelligence / dashboard) ──────────────────────
def hidden_alpha_report(df: pd.DataFrame, symbol: str, timeframe: str,
                        with_kelly: bool = True) -> dict:
    """One JSON-able snapshot of the whole hidden alpha layer."""
    report: dict = {"symbol": symbol, "timeframe": timeframe,
                    "bars": 0 if df is None else len(df)}
    if df is None or len(df) < WINDOW + 4:
        report["available"] = False
        report["note"] = "insufficient data"
        return report
    report["available"] = True
    report["regime"] = regime_probabilities(df)
    report["cvd"] = cvd_analysis(df)
    report["state_vector"] = state_vector(df)
    report["similar_states"] = similar_states(df)
    if with_kelly:
        try:
            from data.database import SignalDB
            from data.simulator import paper_progress, primary_plan_types
            with SignalDB() as db:
                progress = paper_progress(db)
            report["kelly"] = kelly_from_progress(
                progress, plan_types=primary_plan_types())
        except Exception as exc:
            report["kelly"] = {"available": False,
                               "reason": f"{type(exc).__name__}: {exc}"}
    return report

def format_hidden(report: dict) -> str:
    """Human-readable block for `python main.py hidden`."""
    lines = ["=" * 66,
             f"HIDDEN ALPHA — {report.get('symbol')} {report.get('timeframe')} "
             f"({report.get('bars')} bars)", "-" * 66]
    if not report.get("available"):
        lines.append(f"  unavailable: {report.get('note', 'no data')}")
        return "\n".join(lines)
    reg = report["regime"]
    lines.append("  latent regimes (HMM-style, P over 4 states):")
    for key in REGIME_KEYS:
        bar = "█" * int(round(reg[key] * 24))
        marker = " ◄ dominant" if key == reg["dominant"] else ""
        lines.append(f"    {key:<18} {reg[key]:>6.1%}  {bar}{marker}")
    lines.append(f"    → dominant: {reg['dominant']} — {reg['label']}")
    cvd = report["cvd"]
    lines.append(f"  order flow    : CVD {cvd['cvd']:+,.0f} (z {cvd['cvd_z']:+.2f}), "
                 f"buy {cvd['buy_pressure']:.0%} / sell {cvd['sell_pressure']:.0%}")
    if cvd["absorption"]:
        lines.append(f"    ⚡ absorption: {cvd['absorption_direction']} — "
                     f"large volume absorbed on a narrow range")
    if cvd["exhaustion"]:
        lines.append(f"    ⚡ exhaustion: {cvd['exhaustion_direction']} — "
                     f"high volume, long wick against the trend")
    kelly = report.get("kelly") or {}
    if kelly.get("suggested_risk_pct") is not None:
        note = "STAND ASIDE (negative edge)" if kelly.get("stand_aside") \
            else "within the progression cap"
        lines.append(f"  kelly size    : {kelly['suggested_risk_pct']}% risk/trade "
                     f"(edge {kelly.get('edge')}, p={kelly.get('win_rate')}, "
                     f"b={kelly.get('payoff')}, n={kelly.get('n')}) — {note}")
    elif kelly:
        lines.append(f"  kelly size    : {kelly.get('note', 'not enough evidence yet')}")
    sv = report["state_vector"]
    if sv.get("available"):
        vec = " ".join(f"{x:+.2f}" for x in sv["vector"])
        lines.append(f"  8D fingerprint: [{vec}]")
    sim = report["similar_states"]
    if sim.get("available"):
        s = sim["stats"]
        lines.append(f"  similar states: {s['n']} matches @ {sim['horizon']} bars — "
                     f"mean fwd {s['mean_forward_return_pct']:+.2f}%, "
                     f"win rate {s['win_rate_forward']:.0%}")
        for m in sim["matches"][:3]:
            lines.append(f"    bar {m['index']}  d={m['distance']:.3f}  "
                         f"fwd {m['forward_return_pct']:+.2f}% "
                         f"(vol {m['forward_vol_pct']:.2f}%)")
    return "\n".join(lines)
