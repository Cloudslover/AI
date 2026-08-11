"""engine/correlation.py — measured cross-asset correlation & beta (read-only).

Decision B2 hard-codes the professional rule that **BTC + ETH are ONE
correlated crypto-risk bucket** (see ``brain/portfolio.py``).  That rule is a
deliberate, static safety default.  This module *measures* whether the
assumption currently holds:

  * Pearson correlation matrix over rolling log returns (per pair),
  * ETH/BTC beta (how much ETH moves per unit of BTC),
  * gold-vs-crypto coupling (normal: low; risk-off macro regimes can raise it),
  * explicit warnings when the measured relationship drifts far enough that a
    human should re-read the bucket rule.

Read-only by design: nothing here changes the portfolio veto, the risk gate,
or any automatic behaviour — it is desk analytics, like ``hidden`` / ``analytics``.

Mixed-history honesty: Binance symbol histories share one candle timestamp
grid, which the engine aligns by exact ``ts`` join.  In DEMO_MODE the BTC
sample is real (its own timestamps) while the other symbols are synthetic
(their own grid).  When the timestamp alignment yields too few bars, the
report falls back to *positional tail alignment* and says so explicitly, so a
demo matrix is never silently confused with a live one.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "XAUUSD")
MIN_ALIGNED_ROWS = 20


def _log_returns(df: pd.DataFrame) -> pd.Series:
    """Log returns of close, indexed by candle timestamp when available."""
    if df is None or len(df) < 2 or "close" not in df.columns:
        return pd.Series(dtype=float)
    close = pd.to_numeric(df["close"], errors="coerce").astype(float)
    ret = np.log(close / close.shift(1)).dropna()
    if "ts" in df.columns:
        idx = pd.to_numeric(df["ts"], errors="coerce").astype("int64")[1:]
        ret.index = idx.values
        ret = ret[~ret.index.duplicated(keep="last")]
    else:
        ret.index = pd.RangeIndex(len(ret))
    ret.name = None
    return ret.dropna()


def _positional_align(returns: dict[str, pd.Series]) -> pd.DataFrame:
    """Align series by position over the common length (tail)."""
    n = min(len(r) for r in returns.values())
    if n <= 0:
        return pd.DataFrame()
    return pd.DataFrame({sym: r.tail(n).reset_index(drop=True)
                         for sym, r in returns.items()})


def aligned_returns(series: dict[str, pd.DataFrame],
                    min_rows: int = MIN_ALIGNED_ROWS) -> tuple[pd.DataFrame, str]:
    """Align per-symbol return series into one observation matrix.

    Returns ``(frame, mode)`` where mode is ``"ts"`` (exact timestamp join) or
    ``"positional"`` (tail-by-position fallback, e.g. mixed real+synthetic
    demo data).  An empty frame means there is simply not enough overlap.
    """
    returns = {sym: _log_returns(df) for sym, df in series.items()}
    returns = {sym: r for sym, r in returns.items() if len(r) >= 2}
    if len(returns) < 2:
        return pd.DataFrame(), "insufficient"

    frame = pd.DataFrame(returns).dropna()
    if len(frame) >= min_rows:
        return frame, "ts"

    frame = _positional_align(returns)
    if len(frame) >= min_rows:
        return frame, "positional"
    return pd.DataFrame(), "insufficient"


def _beta(ret_x: pd.Series, ret_y: pd.Series) -> Optional[float]:
    """beta of x on y: cov(x, y) / var(y)."""
    var_y = float(np.var(ret_y, ddof=1))
    if var_y <= 0 or len(ret_x) < 3:
        return None
    cov = float(np.cov(ret_x, ret_y, ddof=1)[0, 1])
    return round(cov / var_y, 3)


def correlation_report(series: dict[str, pd.DataFrame],
                       window: int = 60,
                       min_rows: int = MIN_ALIGNED_ROWS) -> dict:
    """Rolling correlation matrix + ETH/BTC beta + bucket-assumption check.

    ``series`` maps a symbol to its OHLCV frame.  ``window`` bounds how many
    recent aligned returns feed the matrix (all of them when fewer exist).
    """
    symbols = [s for s in series if series[s] is not None and len(series[s]) >= 2]
    if len(symbols) < 2:
        return {"available": False,
                "note": "need at least two symbols with price history",
                "symbols": list(series)}

    frame, mode = aligned_returns({s: series[s] for s in symbols})
    if frame.empty or len(frame) < min_rows:
        return {"available": False,
                "note": f"not enough aligned observations ({len(frame)} < {min_rows})",
                "symbols": symbols,
                "alignment": mode}

    obs = frame.tail(window)
    corr = obs.corr()
    matrix = {s1: {s2: (round(float(corr.loc[s1, s2]), 3)
                        if pd.notna(corr.loc[s1, s2]) else None)
                   for s2 in corr.columns}
              for s1 in corr.index}

    def pair(a: str, b: str) -> Optional[float]:
        try:
            v = matrix[a][b]
        except KeyError:
            return None
        return v

    btc_eth = pair("BTCUSDT", "ETHUSDT")
    btc_gold = pair("BTCUSDT", "XAUUSD")
    eth_gold = pair("ETHUSDT", "XAUUSD")

    beta = None
    if {"BTCUSDT", "ETHUSDT"} <= set(obs.columns):
        beta = _beta(obs["ETHUSDT"], obs["BTCUSDT"])

    warnings: list[str] = []
    affirmations: list[str] = []

    # BTC/ETH: the portfolio bucket assumes high positive correlation.
    if btc_eth is None:
        warnings.append("BTC/ETH correlation unmeasurable on this data")
    elif btc_eth >= 0.8:
        affirmations.append(
            f"BTC/ETH strongly correlated ({btc_eth:+.2f}) — the ONE-bucket "
            f"portfolio rule is confirmed by current measurement")
    elif btc_eth >= 0.5:
        warnings.append(
            f"BTC/ETH correlation only moderate ({btc_eth:+.2f}) — the bucket "
            f"rule still applies; treat halves of the bucket with care")
    else:
        warnings.append(
            f"BTC/ETH decoupled right now ({btc_eth:+.2f}) — the static bucket "
            f"rule stays conservative; review before treating BTC and ETH "
            f"as independent trades")

    # Gold vs crypto: normally low; macro risk-off can couple everything.
    crypto_gold = [c for c in (btc_gold, eth_gold) if c is not None]
    if crypto_gold:
        mx = max(abs(c) for c in crypto_gold)
        if mx >= 0.7:
            warnings.append(
                f"gold/crypto coupling unusually high (max {mx:+.2f}) — "
                f"macro risk regime; gold is NOT an independent hedge this week")

    if obs.isna().any().any():
        warnings.append("NaNs detected in aligned returns — matrix computed on pairwise data")

    return {
        "available": True,
        "symbols": list(obs.columns),
        "n_observations": int(len(obs)),
        "window": int(window),
        "alignment": mode,
        "matrix": matrix,
        "btc_eth_corr": btc_eth,
        "btc_gold_corr": btc_gold,
        "eth_gold_corr": eth_gold,
        "eth_btc_beta": beta,
        "warnings": warnings,
        "confirmations": affirmations,
        "note": ("positional alignment (mixed demo/sample data — not a live "
                 "matrix)" if mode == "positional" else
                 "timestamp-aligned returns"),
    }


def fetch_report(client, symbols: list[str] | tuple[str, ...] | None = DEFAULT_SYMBOLS,
                 timeframe: str = "1h", bars: int = 300,
                 window: int = 60) -> dict:
    """Fetch klines for the watchlist and build the correlation report."""
    symbols = tuple(symbols or DEFAULT_SYMBOLS)
    series: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    for sym in symbols:
        try:
            series[sym] = client.klines(sym, timeframe, bars)
        except Exception as exc:
            errors[sym] = f"{type(exc).__name__}: {exc}"
            series[sym] = None
    report = correlation_report(series, window=window)
    report["timeframe"] = timeframe
    report["bars_requested"] = int(bars)
    if errors:
        report["fetch_errors"] = errors
    return report


def format_correlation(res: dict) -> str:
    """Human-readable cross-asset correlation summary for the CLI."""
    lines = ["=" * 72, "CROSS-ASSET CORRELATION — measured bucket check (read-only)",
             "-" * 72]
    if not res.get("available"):
        lines.append(f"  unavailable: {res.get('note', 'unknown reason')}")
        return "\n".join(lines)

    syms = res["symbols"]
    lines.append(f"  tf={res.get('timeframe', '?')}  window={res['window']} "
                 f"obs={res['n_observations']}  alignment={res['alignment']}")
    header = "  " + " " * 10 + "".join(f"{s[:9]:>12}" for s in syms)
    lines.append(header)
    for s1 in syms:
        row = [f"{((res['matrix'][s1][s2] if res['matrix'][s1][s2] is not None else float('nan'))):+12.3f}"
               for s2 in syms]
        lines.append(f"  {s1[:10]:<10}" + "".join(row))
    lines.append("-" * 72)
    if res.get("btc_eth_corr") is not None:
        lines.append(f"  BTC/ETH corr  {res['btc_eth_corr']:+.3f}"
                     + (f"   ETH/BTC beta {res['eth_btc_beta']:+.3f}"
                        if res.get("eth_btc_beta") is not None else ""))
    if res.get("btc_gold_corr") is not None:
        lines.append(f"  BTC/GOLD corr {res['btc_gold_corr']:+.3f}   "
                     f"ETH/GOLD corr {res['eth_gold_corr']:+.3f}")
    for line in res.get("confirmations", []):
        lines.append(f"  ✓ {line}")
    for line in res.get("warnings", []):
        lines.append(f"  ⚠ {line}")
    lines.append(f"  note: {res.get('note', '')}")
    lines.append("  static rule (brain/portfolio.py): BTC+ETH = ONE crypto bucket, "
                 "gold separate — this report only measures it.")
    return "\n".join(lines)
