"""Risk / execution analytics built on the decided-paper book.

Two tools for the "what is my real risk / edge" question that the single
profit-factor number cannot answer:

  * mae_mfe_summary — how far against / for did each trade go, in R?  Tells
    you whether your stops are too tight (MAE routinely approaches your stop)
    or your targets are unreachable (MFE caps well below target).

  * monte_carlo_equity — resample the realised trade outcomes thousands of
    times to get a *distribution* of terminal equity and drawdown, not a single
    hopeful backtest line.  This is the honest picture of variance before you
    trust PROGRESSION=micro.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from config import RISK_PCT


def mae_mfe_summary(db, plan_type: Optional[str] = None) -> dict:
    """MAE / MFE statistics per setup, in R (price excursion / planned risk).

    Returns per-setup aggregates plus an overall insight.  Runs on the real
    paper book (decided_paper_rows with exclude_sim=True): simulator samples
    are calibration evidence, not the live book the desk should review.
    """
    rows = db.decided_paper_rows(exclude_sim=True)
    if not rows:
        return {"available": False, "note": "no decided paper trades yet"}

    by_type: dict[str, dict] = {}
    for r in rows:
        if plan_type and r.get("plan_type") != plan_type:
            continue
        pt = r.get("plan_type") or "unknown"
        entry = r.get("entry")
        sl = r.get("stop_loss")
        risk = abs(entry - sl) if (entry is not None and sl is not None) else None
        mae = r.get("mae")
        mfe = r.get("mfe")
        rr = r.get("rr_achieved")
        mae_r = (mae / risk) if (mae is not None and risk) else None
        mfe_r = (mfe / risk) if (mfe is not None and risk) else None
        bucket = by_type.setdefault(pt, {
            "n": 0, "mae_r": [], "mfe_r": [], "wins": 0, "losses": 0,
        })
        bucket["n"] += 1
        if mae_r is not None:
            bucket["mae_r"].append(mae_r)
        if mfe_r is not None:
            bucket["mfe_r"].append(mfe_r)
        if rr is not None:
            if rr > 0:
                bucket["wins"] += 1
            elif rr < 0:
                bucket["losses"] += 1

    summary = {}
    for pt, b in by_type.items():
        mae_r = b["mae_r"]
        mfe_r = b["mfe_r"]
        win_rate = b["wins"] / max(1, b["wins"] + b["losses"])
        summary[pt] = {
            "n": b["n"],
            "win_rate": round(win_rate, 3),
            "avg_mae_r": round(float(np.mean(mae_r)), 3) if mae_r else None,
            "max_mae_r": round(float(np.max(mae_r)), 3) if mae_r else None,
            "avg_mfe_r": round(float(np.mean(mfe_r)), 3) if mfe_r else None,
            "max_mfe_r": round(float(np.max(mfe_r)), 3) if mfe_r else None,
        }

    # overall insight across every setup the desk has actually traded
    all_mae = [v for b in by_type.values() for v in b["mae_r"]]
    all_mfe = [v for b in by_type.values() for v in b["mfe_r"]]
    insight = _mae_mfe_insight(all_mae, all_mfe)
    return {
        "available": True,
        "by_setup": summary,
        "overall": {
            "n": sum(b["n"] for b in by_type.values()),
            "avg_mae_r": round(float(np.mean(all_mae)), 3) if all_mae else None,
            "avg_mfe_r": round(float(np.mean(all_mfe)), 3) if all_mfe else None,
        },
        "insight": insight,
    }


def _mae_mfe_insight(mae_r: list[float], mfe_r: list[float]) -> list[str]:
    out = []
    if not mae_r or not mfe_r:
        return ["not enough excursion data yet"]
    avg_mae = float(np.mean(mae_r))
    avg_mfe = float(np.mean(mfe_r))
    if avg_mae >= 0.9:
        out.append(f"MAE averages {avg_mae:.2f}R — you are getting stopped out "
                   f"close to your stop; entries are acceptable, keep the risk "
                   f"discipline")
    elif avg_mae <= 0.4:
        out.append(f"MAE averages only {avg_mae:.2f}R against a typical 1R stop — "
                   f"your stops may be too tight; consider whether noise is taking "
                   f"you out before the move")
    if avg_mfe >= 1.5:
        out.append(f"MFE averages {avg_mfe:.2f}R — the setups run well past 1R; a "
                   f"runner (move stop to breakeven at 1R, trail the rest) would "
                   f"capture more")
    elif avg_mfe <= 0.8 and avg_mfe < avg_mae:
        out.append(f"MFE ({avg_mfe:.2f}R) is below MAE ({avg_mae:.2f}R) — trades "
                   f"rarely run in your favour; review entries / setup quality "
                   f"before increasing size")
    if not out:
        out.append(f"MAE {avg_mae:.2f}R vs MFE {avg_mfe:.2f}R — reasonable "
                   f"asymmetry, keep executing")
    return out


def monte_carlo_equity(db, start: float = 10_000.0, risk_pct: float = None,
                       samples: int = 2000, seed: Optional[int] = None) -> dict:
    """Distribution of terminal equity and drawdown from the realised trade book.

    Resamples the decided paper-trade outcomes (with replacement) ``samples``
    times, grows an equity curve at ``risk_pct`` % of equity per trade, and
    reports the median / percentile terminal equity and the drawdown
    distribution.  This is the honest variance picture behind a single
    profit-factor number.
    """
    rows = db.decided_paper_rows(exclude_sim=True)
    outcomes = [float(r["rr_achieved"]) for r in rows
                if r.get("rr_achieved") is not None]
    if not outcomes:
        return {"available": False, "note": "no decided paper trades yet"}

    risk_pct = risk_pct if risk_pct is not None else RISK_PCT
    rng = np.random.default_rng(seed)
    n = len(outcomes)
    terminals = np.zeros(samples)
    max_dds = np.zeros(samples)
    for s in range(samples):
        perm = rng.choice(outcomes, size=n, replace=True)
        equity = start
        peak = start
        dd = 0.0
        for rr in perm:
            equity *= (1.0 + rr * risk_pct / 100.0)
            if equity > peak:
                peak = equity
            dd = max(dd, 1.0 - equity / peak)
        terminals[s] = equity
        max_dds[s] = dd

    return {
        "available": True,
        "start": start,
        "risk_pct": risk_pct,
        "n_trades": n,
        "samples": samples,
        "terminal": {
            "median": round(float(np.median(terminals)), 2),
            "mean": round(float(np.mean(terminals)), 2),
            "p5": round(float(np.percentile(terminals, 5)), 2),
            "p95": round(float(np.percentile(terminals, 95)), 2),
            "prob_profit": round(float(np.mean(terminals > start)), 3),
        },
        "drawdown": {
            "median_pct": round(float(np.median(max_dds)) * 100, 2),
            "p95_pct": round(float(np.percentile(max_dds, 95)) * 100, 2),
        },
    }
