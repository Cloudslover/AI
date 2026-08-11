"""Compatibility facade for CryptoBrain's functional analytical core.

The implementation now lives in :mod:`engine.pipeline`.  This module keeps the
long-standing import path (``engine.signal_engine.analyze_frame``) stable for
CLI, dashboard, tests and third-party users.
"""
from __future__ import annotations

from typing import Mapping

import pandas as pd

from .pipeline import (BrainOutput, FeatureStage, FrozenScore, PlanStage,
                       ScoreStage, analyze_core, build_best_signal, freeze,
                       thaw)


def analyze_frame(df: pd.DataFrame, symbol: str = "BTCUSDT",
                  timeframe: str = "15m", min_confidence: int = 55,
                  default_rr: float = 2.0, calibration: dict | None = None,
                  primary_types: set | None = None,
                  tp_rr_by_type: dict | None = None,
                  fill_stats_by_type: dict | None = None,
                  scoring_weights: Mapping[str, int | float] | None = None,
                  htf_context: Mapping | None = None,
                  now_ms: int | None = None) -> BrainOutput:
    """Run the pure core on one closed OHLCV frame.

    All I/O must happen before or after this call. ``now_ms`` is injectable so
    acceptance snapshots do not depend on wall-clock time.
    """
    return analyze_core(
        df, symbol=symbol, timeframe=timeframe,
        min_confidence=min_confidence, default_rr=default_rr,
        calibration=calibration, primary_types=primary_types,
        tp_rr_by_type=tp_rr_by_type, fill_stats_by_type=fill_stats_by_type,
        scoring_weights=scoring_weights, htf_context=htf_context,
        now_ms=now_ms,
    )


__all__ = [
    "BrainOutput", "FeatureStage", "FrozenScore", "PlanStage", "ScoreStage",
    "analyze_core", "analyze_frame", "build_best_signal", "freeze", "thaw",
]
