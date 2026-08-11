"""Pure analytical pipeline — CryptoBrain's functional core.

Network calls, SQLite writes, state memory and notifications belong to
``brain.full_pipeline`` / CLI / web shells.  This module accepts a closed OHLCV
frame plus explicit configuration and returns immutable stage records.
Providing ``now_ms`` makes the entire result deterministic for acceptance tests.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

import pandas as pd

from brain.decision_service import build_candidate_layers
from data.symbols import normalize_symbol
from .features import build_snapshot
from .indicators import add_all_indicators, find_rsi_divergence
from .regime import classify_market_regime
from .rules import Plan, build_plans
from .scorer import (ScoreBreakdown, normalize_weights, score_bearish,
                     score_bullish, score_neutral)
from .structure import analyze_structure


def freeze(value: Any) -> Any:
    """Recursively freeze JSON-shaped data at a stage boundary."""
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    if isinstance(value, set):
        return frozenset(value)
    return value


def thaw(value: Any) -> Any:
    """Return fresh JSON-compatible containers from immutable stage data."""
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    return value


@dataclass(frozen=True)
class FrozenScore:
    score: int
    max_score: int
    confidence: str
    confidence_pct: int
    conditions: Mapping
    fired: tuple[str, ...]

    @classmethod
    def from_score(cls, score: ScoreBreakdown) -> "FrozenScore":
        return cls(score.score, score.max_score, score.confidence,
                   score.confidence_pct, freeze(score.conditions),
                   tuple(score.fired))

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "max_score": self.max_score,
            "confidence_pct": self.confidence_pct,
            "confidence": self.confidence,
            "conditions": thaw(self.conditions),
            "reasons": list(self.fired),
        }


@dataclass(frozen=True)
class FeatureStage:
    features: Mapping
    structure: Mapping


@dataclass(frozen=True)
class ScoreStage:
    bull: FrozenScore
    bear: FrozenScore
    weights: Mapping


@dataclass(frozen=True)
class PlanStage:
    plans: tuple[Plan, ...]
    authorization_policy: str


@dataclass(frozen=True)
class BrainOutput:
    features: Mapping
    structure: Mapping
    bull_score: FrozenScore
    bear_score: FrozenScore
    best_signal: Mapping
    plans: tuple[Mapping, ...]
    decision_service: Mapping
    scoring_weights: Mapping

    def as_json(self) -> dict:
        return {
            # Compatibility adapter. New integrations should consume
            # decision_service.{watch_items,active_candidate,desk_verdict}.
            "signal": thaw(self.best_signal),
            "plans": thaw(self.plans),
            "decision_service": thaw(self.decision_service),
            "snapshot": {
                "features": thaw(self.features),
                "structure": thaw(self.structure),
                "scores": {
                    "bull": self.bull_score.as_dict(),
                    "bear": self.bear_score.as_dict(),
                },
                "scoring_weights": thaw(self.scoring_weights),
            },
        }


def _feature_stage(df: pd.DataFrame, symbol: str, timeframe: str,
                   htf_context: Mapping | None = None) -> FeatureStage:
    data = df.copy()
    data.attrs["symbol"] = symbol
    data.attrs["timeframe"] = timeframe
    indicators = add_all_indicators(data)
    structure = analyze_structure(indicators)
    divergence = find_rsi_divergence(indicators)
    features = build_snapshot(indicators, structure, divergence,
                              structure.equal_levels)

    regime = classify_market_regime(data, features)
    features["regime"] = regime
    features["regime_name"] = regime.get("regime", "RANGING")
    features["regime_label"] = regime.get("label", "Ranging / Neutral")
    features["fake_breakout"] = bool(regime.get("fake_breakout"))
    features["trap_detected"] = bool(regime.get("trap_detected"))

    # HTF structure is explicit input, never fetched here. This preserves the
    # core's determinism while allowing the shell to propagate 1W/1D/4H/1H SMC.
    features["htf_bias"] = (htf_context or {}).get("htf_bias")
    features["mtf_alignment"] = ((htf_context or {}).get("alignment") or {}).get("label")
    features["htf_structure"] = list((htf_context or {}).get("htf_structure") or [])
    return FeatureStage(freeze(features), freeze(structure.as_dict()))


def _score_stage(stage: FeatureStage,
                 scoring_weights: Mapping[str, int | float] | None) -> tuple[ScoreStage, ScoreBreakdown, ScoreBreakdown]:
    profile = normalize_weights(scoring_weights)
    features = thaw(stage.features)
    bull = score_bullish(features, profile)
    bear = score_bearish(features, profile)
    if bull.score == 0 and bear.score == 0:
        neutral = score_neutral(features, profile)
        bull, bear = neutral, neutral
    return (ScoreStage(FrozenScore.from_score(bull), FrozenScore.from_score(bear),
                       freeze(profile)), bull, bear)


def _plan_stage(stage: FeatureStage, bull: ScoreBreakdown, bear: ScoreBreakdown,
                *, min_confidence: int, default_rr: float,
                calibration: dict | None, primary_types: set | None,
                tp_rr_by_type: dict | None, fill_stats_by_type: dict | None) -> PlanStage:
    features = thaw(stage.features)
    plans = build_plans(
        features, bull, bear, min_confidence=min_confidence,
        default_rr=default_rr, calibration=calibration,
        primary_types=primary_types, tp_rr_by_type=tp_rr_by_type,
        fill_stats_by_type=fill_stats_by_type,
        regime=features.get("regime_name", ""),
    )
    policy_name = "all" if primary_types is None else "configured_setup_family"
    return PlanStage(tuple(plans), policy_name)


def _signal_id(symbol: str, ts_ms: int) -> str:
    # UTC keeps an injected timestamp deterministic across CI/servers/timezones.
    return f"{symbol.replace('/', '')}_{time.strftime('%Y%m%d_%H%M', time.gmtime(ts_ms / 1000))}"


def _reason(features: Mapping, side: str, bull: ScoreBreakdown,
            bear: ScoreBreakdown) -> str:
    parts: list[str] = []
    if side == "BUY":
        if (features.get("rsi_divergence") or {}).get("bull"):
            parts.append("Bullish divergence on RSI")
        if features.get("above_vwap"):
            parts.append("price above VWAP")
        if features.get("event_kind") in ("bos_up", "choch_up"):
            parts.append(str(features["event_kind"]).replace("_", " ").upper())
        parts += [r for r in bull.fired if r not in parts]
    elif side == "SELL":
        if (features.get("rsi_divergence") or {}).get("bear"):
            parts.append("Bearish divergence on RSI")
        if features.get("above_vwap") is False:
            parts.append("price below VWAP")
        if features.get("event_kind") in ("bos_down", "choch_down"):
            parts.append(str(features["event_kind"]).replace("_", " ").upper())
        parts += [r for r in bear.fired if r not in parts]
    else:
        parts.append("No authorized immediate entry; conditional scenarios remain on watch")
    if features.get("volume_spike"):
        parts.append("volume spike")
    return " + ".join(parts[:6])


def build_best_signal(features: Mapping, bull: ScoreBreakdown,
                      bear: ScoreBreakdown, plans: list[Plan] | tuple[Plan, ...],
                      symbol: str, timeframe: str, min_confidence: int,
                      now_ms: int | None = None, layers: Mapping | None = None) -> dict:
    """Legacy signal adapter sourced only from ``active_candidate``.

    Conditional plans can no longer masquerade as immediate signals. Their
    confidence remains attached to each watch item instead.
    """
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    layers = dict(layers or build_candidate_layers(plans, min_confidence))
    candidate = layers.get("active_candidate")
    if candidate:
        action = candidate["action"]
        entry = candidate.get("entry") or features.get("price")
        stop = candidate.get("stop_loss")
        tps = candidate.get("take_profits") or []
        confidence = candidate.get("confidence_label", "LOW")
        confidence_pct = int(candidate.get("confidence") or 0)
        rr = float(candidate.get("risk_reward") or 0)
        signal_type = "SIGNAL"
    else:
        action, entry, stop, tps = "NO TRADE", None, None, []
        confidence, confidence_pct, rr, signal_type = "LOW", 0, 0.0, "MONITOR"

    return {
        "signal_id": _signal_id(symbol, now_ms),
        "timestamp": now_ms,
        "asset": symbol,
        "action": action,
        "entry": round(float(entry), 2) if entry else None,
        "stop_loss": round(float(stop), 2) if stop else None,
        "take_profit": round(float(tps[0]), 2) if tps else None,
        "risk_reward": round(rr, 2),
        "confidence": confidence,
        "confidence_pct": confidence_pct,
        "timeframe": timeframe,
        "reason": _reason(features, action, bull, bear),
        "signal_type": signal_type,
        "compatibility_note": "Legacy adapter; use decision_service for action semantics.",
        "note": ("NO TRADE: no authorized immediate entry. Read decision_service.watch_items."
                 if signal_type == "MONITOR" else
                 "Risk advice only — not financial advice. Use stop-losses."),
    }


def analyze_core(df: pd.DataFrame, *, symbol: str = "BTCUSDT",
                 timeframe: str = "15m", min_confidence: int = 55,
                 default_rr: float = 2.0, calibration: dict | None = None,
                 primary_types: set | None = None,
                 tp_rr_by_type: dict | None = None,
                 fill_stats_by_type: dict | None = None,
                 scoring_weights: Mapping[str, int | float] | None = None,
                 htf_context: Mapping | None = None,
                 now_ms: int | None = None) -> BrainOutput:
    """Compose immutable, side-effect-free analytical stages."""
    symbol = normalize_symbol(symbol)
    features = _feature_stage(df, symbol, timeframe, htf_context)
    scores, bull, bear = _score_stage(features, scoring_weights)
    plan_stage = _plan_stage(
        features, bull, bear, min_confidence=min_confidence,
        default_rr=default_rr, calibration=calibration,
        primary_types=primary_types, tp_rr_by_type=tp_rr_by_type,
        fill_stats_by_type=fill_stats_by_type,
    )
    layers = build_candidate_layers(plan_stage.plans, min_confidence)
    signal = build_best_signal(features.features, bull, bear, plan_stage.plans,
                               symbol, timeframe, min_confidence, now_ms, layers)
    return BrainOutput(
        features=features.features,
        structure=features.structure,
        bull_score=scores.bull,
        bear_score=scores.bear,
        best_signal=freeze(signal),
        plans=tuple(freeze(p.as_dict()) for p in plan_stage.plans),
        decision_service=freeze(layers),
        scoring_weights=scores.weights,
    )
