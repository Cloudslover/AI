"""brain/calibrator.py

The self-improvement loop. After enough historical backtest outcomes and
approved live-market paper outcomes accumulate in the database, the calibrator
computes a per-plan-type "calibration profile":

    multiplier = clamp(1 + expectancy * gain, min_mult, max_mult)

* Positive-expectancy setups (e.g. Buy Pullback) get a multiplier > 1
  → their confidence is boosted in future signals.
* Negative-expectancy setups (e.g. Breakout Buy in our first run) get
  a multiplier < 1 → dampened; if they are bad enough and well-sampled
  they can be dropped entirely (CALIBRATE_FILTER).

The profile is stored in the DB and loaded by `analyze_frame` → `build_plans`,
so the engine literally improves with every backtest you run. With zero data
the profile is empty and every multiplier is 1.0 (neutral — no behaviour
change), so calibration is strictly additive.
"""
from __future__ import annotations

import time
from typing import Optional

from config import (CALIBRATE_MIN_N, CALIBRATE_GAIN, CALIBRATE_MAX_MULT,
                    CALIBRATE_MIN_MULT, CALIBRATE_FILTER, CALIBRATE_FILTER_THRESHOLD)
from data.database import SignalDB

WIN_SET = {"FULL_WIN", "PARTIAL_WIN"}


def compute_expectancy_by_type(db: SignalDB, horizons: Optional[list[float]] = None) -> dict:
    """Expectancy (average R) per plan type from backtests + paper outcomes."""
    # Historical walk-forward grades and live-market paper outcomes are both
    # useful evidence, but remain separate tables so the dashboard can show
    # them honestly.  The calibration pass deliberately combines only decided
    # outcomes: TP_HIT behaves like a win; STOP_LOSS behaves like a loss.
    rows = db.conn.execute(
        """WITH decided AS (
                 SELECT plan_type, outcome, rr_achieved, 'backtest' AS source
                 FROM backtest_results
                 WHERE outcome IN ('FULL_WIN','PARTIAL_WIN','LOSS')
                 UNION ALL
                 SELECT plan_type,
                        CASE outcome WHEN 'TP_HIT' THEN 'FULL_WIN'
                                     WHEN 'STOP_LOSS' THEN 'LOSS' END AS outcome,
                        rr_achieved, 'paper' AS source
                 FROM paper_trades
                 WHERE outcome IN ('TP_HIT','STOP_LOSS')
             )
             SELECT plan_type,
                    COUNT(*) n,
                    SUM(CASE WHEN outcome IN ('FULL_WIN','PARTIAL_WIN') THEN 1 ELSE 0 END) wins,
                    SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) losses,
                    SUM(CASE WHEN source='backtest' THEN 1 ELSE 0 END) backtest_samples,
                    SUM(CASE WHEN source='paper' THEN 1 ELSE 0 END) paper_samples,
                    AVG(rr_achieved) avg_rr
             FROM decided
             GROUP BY plan_type"""
    ).fetchall()
    out = {}
    for r in rows:
        n = r["n"] or 0
        wins = r["wins"] or 0
        losses = r["losses"] or 0
        decided = wins + losses
        avg_rr = r["avg_rr"] or 0.0
        out[r["plan_type"]] = {
            "n": n,
            "wins": wins,
            "losses": losses,
            "backtest_samples": r["backtest_samples"] or 0,
            "paper_samples": r["paper_samples"] or 0,
            "win_rate": round(wins / decided, 3) if decided else None,
            "expectancy": round(avg_rr, 3),
        }
    return out


def build_profile(db: SignalDB, filter_neg: bool = CALIBRATE_FILTER,
                  min_n: int = CALIBRATE_MIN_N) -> dict:
    """Turn decided backtest/paper stats into a calibration profile."""
    stats = compute_expectancy_by_type(db)
    profile: dict = {}
    for plan_type, st in stats.items():
        n = st["n"]
        if n < min_n:
            continue  # not enough samples to trust — keep neutral
        exp = st["expectancy"]
        mult = max(CALIBRATE_MIN_MULT, min(CALIBRATE_MAX_MULT, 1 + exp * CALIBRATE_GAIN))
        filtered = bool(filter_neg and exp < CALIBRATE_FILTER_THRESHOLD)
        profile[plan_type] = {
            "multiplier": round(mult, 3),
            "expectancy": exp,
            "samples": n,
            "win_rate": st["win_rate"],
            "filtered": filtered,
        }
    return profile


def learn(profile_path: Optional[str] = None) -> dict:
    """Run the calibration pass over the current database."""
    with SignalDB() as db:
        profile = build_profile(db)
        db.save_calibration(profile)
    return {"profile": profile, "note": "saved to DB — engine will use it on the next scan"}


def apply_calibration(conf: int, plan_type: str, calibration: dict) -> tuple[int, bool]:
    """Apply the calibration profile to one plan's confidence.
    Returns (adjusted_confidence, filtered_out)."""
    if not calibration:
        return conf, False
    entry = calibration.get(plan_type)
    if not entry:
        return conf, False
    if entry.get("filtered"):
        return conf, True
    mult = entry.get("multiplier", 1.0)
    return max(5, min(100, int(round(conf * mult)))), False


def describe(profile: dict) -> str:
    if not profile:
        return "No calibration yet — run `python main.py learn` after a backtest with --save."
    lines = ["Calibration profile (applied to future signals):"]
    for pt, e in sorted(profile.items(), key=lambda kv: kv[1]["samples"], reverse=True):
        if e["filtered"]:
            lines.append(f"  {pt:<24} FILTERED (expectancy {e['expectancy']:+.2f}R, n={e['samples']})")
        else:
            lines.append(f"  {pt:<24} x{e['multiplier']:.2f}  (expectancy {e['expectancy']:+.2f}R, "
                         f"win {e['win_rate']*100:.0f}%, n={e['samples']})")
    return "\n".join(lines)


# keep import-time reference so `time` is used (updated_at stamping lives in db)
_ = time.time
