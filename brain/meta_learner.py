"""Offline advisory search for scoring-weight profiles.

This is deliberately *not* online learning. It replays the exact walk-forward
engine over a small, explicit grid and recommends a profile. The operator must
review the evidence and set ``SCORING_WEIGHTS_JSON`` manually; no live profile
is ever changed by this module.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

import pandas as pd

from data.backtester import run_backtest
from engine.scorer import DEFAULT_SCORING_WEIGHTS, normalize_weights


CANDIDATE_PROFILES: dict[str, dict[str, int]] = {
    "default": dict(DEFAULT_SCORING_WEIGHTS),
    "trend": {
        "Trend": 25, "Market structure": 15, "OB/FVG": 15,
        "Liquidity": 10, "Volume": 10, "RSI divergence": 5,
        "Momentum": 15, "Location": 5,
    },
    "structure": {
        "Trend": 10, "Market structure": 25, "OB/FVG": 25,
        "Liquidity": 20, "Volume": 5, "RSI divergence": 5,
        "Momentum": 5, "Location": 5,
    },
    "mean_reversion": {
        "Trend": 8, "Market structure": 20, "OB/FVG": 20,
        "Liquidity": 15, "Volume": 7, "RSI divergence": 15,
        "Momentum": 10, "Location": 5,
    },
}


def _profile_metrics(result: dict, primary_horizon: float) -> dict:
    graded = [g for g in result["graded"] if g.horizon_hours == primary_horizon]
    decided = [g for g in graded if g.outcome in ("FULL_WIN", "PARTIAL_WIN", "LOSS")]
    positives = [g.rr_achieved for g in decided if g.rr_achieved > 0]
    negatives = [abs(g.rr_achieved) for g in decided if g.rr_achieved < 0]
    expectancy = sum(g.rr_achieved for g in decided) / len(decided) if decided else 0.0
    profit_factor = (sum(positives) / sum(negatives)) if negatives else (99.0 if positives else 0.0)
    fill_rate = (sum(1 for g in graded if g.outcome != "NOT_TRIGGERED") / len(graded)
                 if graded else 0.0)
    # Reward expectancy first; cap PF's influence so a tiny lucky sample cannot
    # dominate. A logarithmic-like sample factor penalizes sparse profiles.
    sample_factor = min(1.0, len(decided) / 30.0)
    objective = sample_factor * (expectancy + 0.10 * min(profit_factor, 3.0))
    return {
        "decided": len(decided),
        "generated": len(graded),
        "expectancy": round(expectancy, 4),
        "profit_factor": round(profit_factor, 4),
        "fill_rate": round(fill_rate, 4),
        "objective": round(objective, 5),
    }


def evaluate_weight_profiles(
    df: pd.DataFrame,
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "15m",
    profiles: Mapping[str, Mapping[str, int | float]] | None = None,
    horizon: float = 4.0,
    min_bars: int = 120,
    step: int = 5,
    min_confidence: int = 55,
    min_decided: int = 20,
    min_improvement: float = 0.05,
) -> dict:
    """Grid-search weight profiles and return a human-review advisory."""
    profiles = profiles or CANDIDATE_PROFILES
    evidence: dict[str, dict] = {}
    for name, raw in profiles.items():
        weights = normalize_weights(raw)
        result = run_backtest(
            df, symbol=symbol, timeframe=timeframe, horizons=[horizon],
            min_bars=min_bars, step=step, min_confidence=min_confidence,
            scoring_weights=weights,
        )
        evidence[name] = {
            "weights": weights,
            **_profile_metrics(result, horizon),
        }

    baseline_name = "default" if "default" in evidence else next(iter(evidence))
    baseline = evidence[baseline_name]
    ranked = sorted(evidence.items(), key=lambda item: item[1]["objective"], reverse=True)
    best_name, best = ranked[0]
    enough_data = best["decided"] >= min_decided
    improvement = best["objective"] - baseline["objective"]
    recommend_change = bool(best_name != baseline_name and enough_data and
                            improvement >= min_improvement)
    recommendation = best_name if recommend_change else baseline_name
    reason = (
        f"{best_name} improves objective by {improvement:+.4f} with {best['decided']} decided samples"
        if recommend_change else
        (f"insufficient decided samples ({best['decided']} < {min_decided}); retain {baseline_name}"
         if not enough_data else
         f"improvement {improvement:+.4f} is below {min_improvement:.4f}; retain {baseline_name}")
    )
    chosen = evidence[recommendation]
    return {
        "mode": "offline_advisory_only",
        "symbol": symbol,
        "timeframe": timeframe,
        "horizon_hours": horizon,
        "recommendation": recommendation,
        "recommend_change": recommend_change,
        "reason": reason,
        "evidence": evidence,
        "operator_action": {
            "required": True,
            "env": "SCORING_WEIGHTS_JSON=" + json.dumps(chosen["weights"], separators=(",", ":")),
            "warning": "Review out-of-sample evidence before changing .env. This command never activates a profile.",
        },
    }


def save_advisory(advisory: dict, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(advisory, indent=2), encoding="utf-8")
    return target
