"""Boundary tests for the functional-core / decision-service redesign."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from brain.context_providers import (CallableContextProvider,
                                     collect_provider_context)
from brain.decision_service import (build_candidate_layers,
                                    finalize_decision_layers)
from brain.meta_learner import evaluate_weight_profiles
from data.backtester import GradedPlan
from data.database import SignalDB
from engine.rules import Plan, build_plans
from engine.scorer import (DEFAULT_SCORING_WEIGHTS, ScoreBreakdown,
                           score_bullish)
from engine.signal_engine import analyze_frame


def _score(value=80, side="bull"):
    return ScoreBreakdown(score=value, max_score=100,
                          confidence="HIGH" if value >= 80 else "MEDIUM",
                          confidence_pct=value,
                          fired=[f"{side} evidence"])


def test_functional_core_is_deterministic_and_immutable(df):
    first = analyze_frame(df, min_confidence=0, now_ms=1_786_420_800_000)
    second = analyze_frame(df, min_confidence=0, now_ms=1_786_420_800_000)
    assert first.as_json() == second.as_json()
    assert first.best_signal["timestamp"] == 1_786_420_800_000
    with pytest.raises(TypeError):
        first.features["price"] = 1
    with pytest.raises(TypeError):
        first.plans[0]["confidence"] = 1


def test_conditional_confidence_is_not_immediate_execution():
    waiting = Plan(
        id="wait", type="Buy Pullback", action="BUY", condition="IF pullback",
        trigger_level=98, entry=98, stop_loss=96, take_profits=[102],
        risk_reward=2, confidence_pct=95, confidence_label="HIGH",
        status="waiting", execution_mode="conditional", fill_probability=0.37,
    )
    immediate = Plan(
        id="now", type="Immediate Buy", action="BUY", condition="now",
        trigger_level=None, entry=100, stop_loss=98, take_profits=[104],
        risk_reward=2, confidence_pct=82, confidence_label="HIGH",
        fill_probability=1.0,
    )
    layers = build_candidate_layers([waiting, immediate], min_confidence=80)
    assert layers["active_candidate"]["id"] == "now"
    watch = layers["watch_items"][0]
    assert watch["analytical_confidence"] == 95
    assert watch["execution_probability"] == pytest.approx(0.37)

    final = finalize_decision_layers(layers, {
        "action": "BUY", "decision_text": "TRADE BUY", "blocked_by": [],
        "gates": {"risk": {"ok": True}},
    })
    assert final["desk_verdict"]["status"] == "TRADE"
    assert final["desk_verdict"]["execution_probability"] == 1.0


def test_authorization_is_post_generation_not_plan_suppression():
    features = {"price": 100.0, "atr": 1.0, "timeframe": "15m",
                "premium_discount": "equilibrium"}
    plans = build_plans(features, _score(85), _score(0, "bear"),
                        min_confidence=0,
                        primary_types={"Buy Pullback"})
    immediate = next(plan for plan in plans if plan.type == "Immediate Buy")
    assert immediate.primary is False
    assert "research-only" in immediate.authorization_reason
    layers = build_candidate_layers(plans, min_confidence=55)
    assert layers["active_candidate"] is None
    assert any(item["id"] == "imm_buy" for item in layers["watch_items"])


def test_htf_order_block_becomes_conditional_plan_level():
    features = {
        "price": 100.0, "atr": 1.0, "timeframe": "15m",
        "premium_discount": "equilibrium",
        "htf_structure": [{"kind": "order_block", "side": "bullish",
                           "timeframe": "1h", "level": 97.5}],
    }
    plans = build_plans(features, _score(80), _score(0, "bear"),
                        min_confidence=0)
    pullback = next(plan for plan in plans if plan.type == "Buy Pullback")
    assert pullback.entry == pytest.approx(97.5)
    assert pullback.source_timeframe == "1h"
    assert "1h bullish Order Block" in pullback.condition
    assert "15m prints CHOCH up" in pullback.condition


def test_fill_probability_is_calibrated_separately(tmp_path):
    from brain.calibrator import (build_profile,
                                  compute_fill_probability_by_key,
                                  fill_probability_by_type)
    db = SignalDB(tmp_path / "fills.db")
    rows = []
    for i, outcome in enumerate(["FULL_WIN", "LOSS", "NOT_TRIGGERED", "NOT_TRIGGERED"]):
        rows.append({
            "ts": i, "symbol": "BTCUSDT", "timeframe": "15m",
            "plan_type": "Buy Pullback", "action": "BUY",
            "confidence_pct": 80, "horizon_hours": 4,
            "outcome": outcome, "rr_achieved": 2 if outcome == "FULL_WIN" else -1 if outcome == "LOSS" else 0,
            "max_favorable": 1, "max_adverse": 1, "entry": 100,
            "trigger_level": 99, "regime": "RANGING",
        })
    db.save_backtest_rows(rows, "fills")
    stats = compute_fill_probability_by_key(db)
    assert stats["Buy Pullback::RANGING"]["fill_probability"] == 0.5
    assert stats["Buy Pullback::RANGING"]["fill_horizon_hours"] == 4
    profile = build_profile(db, min_n=2, min_paper_n=0)
    assert profile["Buy Pullback::RANGING"]["expectancy"] == 0.5
    assert fill_probability_by_type(profile, "RANGING")["Buy Pullback"]["fill_probability"] == 0.5
    db.save_calibration(profile)
    loaded = db.load_calibration()["Buy Pullback::RANGING"]
    assert loaded["fill_probability"] == 0.5
    assert loaded["fill_horizon_hours"] == 4
    assert loaded["filtered"] is False
    db.close()


def test_context_provider_failure_isolated_and_completeness_exposed():
    good = CallableContextProvider("good", lambda _s: {"available": True, "value": 1})
    bad = CallableContextProvider("bad", lambda _s: (_ for _ in ()).throw(RuntimeError("offline")))
    optional = CallableContextProvider("optional", lambda _s: {}, required=False,
                                       is_configured=False)
    bundle = collect_provider_context([good, bad, optional], "BTCUSDT")
    assert bundle["data"]["good"]["value"] == 1
    assert bundle["providers"]["bad"]["status"] == "failed"
    assert bundle["providers"]["optional"]["status"] == "skipped"
    assert bundle["context_completeness"]["ratio"] == 0.5


def test_scoring_weights_change_composition_without_changing_total():
    features = {
        "trend": "bullish", "supertrend_bull": True, "adx_strong": True,
        "event_kind": None, "trend_bias": "neutral", "above_vwap": False,
    }
    baseline = score_bullish(features)
    trend_heavy = dict(DEFAULT_SCORING_WEIGHTS)
    trend_heavy.update({"Trend": 30, "OB/FVG": 10, "Liquidity": 10})
    assert sum(trend_heavy.values()) == 100
    weighted = score_bullish(features, trend_heavy)
    assert weighted.conditions["Trend"] == 30
    assert weighted.score > baseline.score


def test_meta_learner_is_advisory_only(monkeypatch, df):
    def fake_backtest(_df, **kwargs):
        trend_weight = kwargs["scoring_weights"]["Trend"]
        rr = 2.0 if trend_weight >= 25 else 0.5
        graded = [
            GradedPlan(ts=i, plan_type="Immediate Buy", action="BUY",
                       confidence_pct=80, entry=100, trigger_level=None,
                       horizon_hours=4.0, outcome="FULL_WIN", rr_achieved=rr)
            for i in range(30)
        ]
        return {"graded": graded, "report": {}}

    monkeypatch.setattr("brain.meta_learner.run_backtest", fake_backtest)
    result = evaluate_weight_profiles(df, horizon=4, min_decided=20,
                                      min_improvement=0.01)
    assert result["mode"] == "offline_advisory_only"
    assert result["recommend_change"] is True
    assert result["operator_action"]["required"] is True
    assert result["operator_action"]["env"].startswith("SCORING_WEIGHTS_JSON=")
