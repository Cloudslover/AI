"""Tests for the scoring + rule engine."""
from __future__ import annotations

from engine.features import build_snapshot
from engine.indicators import add_all_indicators, find_rsi_divergence
from engine.rules import build_plans
from engine.scorer import score_bullish, score_bearish, _mapped_confidence
from engine.structure import analyze_structure


def _snapshot(df):
    ind = add_all_indicators(df)
    ms = analyze_structure(ind)
    div = find_rsi_divergence(ind)
    return build_snapshot(ind, ms, div, ms.equal_levels), ms, ind


def test_confidence_mapping():
    assert _mapped_confidence(85) == ("HIGH", 85)
    assert _mapped_confidence(70) == ("MEDIUM", 70)
    assert _mapped_confidence(45) == ("LOW", 45)
    assert _mapped_confidence(20) == ("NO TRADE", 20)


def test_scores_are_bounded(df):
    f, _, _ = _snapshot(df)
    bull = score_bullish(f)
    bear = score_bearish(f)
    assert 0 <= bull.score <= 100
    assert 0 <= bear.score <= 100
    assert bull.confidence in ("HIGH", "MEDIUM", "LOW", "NO TRADE")


def test_bearish_scores_on_downtrend(df_bearish):
    f, _, _ = _snapshot(df_bearish)
    bear = score_bearish(f)
    assert bear.score >= 40, f"expected bearish edge on downtrend, got {bear.score}"


def test_plans_generated(df):
    f, _, _ = _snapshot(df)
    bull = score_bullish(f)
    bear = score_bearish(f)
    plans = build_plans(f, bull, bear, min_confidence=0)  # force all scenarios
    assert len(plans) >= 1
    for p in plans:
        assert p.entry and p.stop_loss and p.take_profits
        assert p.risk_reward > 0
        if p.action == "BUY":
            assert p.stop_loss < p.entry
        else:
            assert p.stop_loss > p.entry


def test_plan_sorting(df):
    f, _, _ = _snapshot(df)
    bull, bear = score_bullish(f), score_bearish(f)
    plans = build_plans(f, bull, bear, min_confidence=0)
    confs = [p.confidence_pct for p in plans]
    assert confs == sorted(confs, reverse=True)
