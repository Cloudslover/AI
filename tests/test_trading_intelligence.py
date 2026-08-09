"""Tests for strict AI Trading Intelligence System output."""
from __future__ import annotations

import pandas as pd

from brain.trading_intelligence import build_intelligence


def _payload(confidence=88, rr=2.5, action="BUY"):
    return {
        "signal": {"asset": "XAUUSD", "action": action, "timeframe": "15m"},
        "plans": [{
            "id": "buy_pullback", "type": "Buy Pullback", "action": action,
            "condition": "IF price pulls back to bullish order block AND rejects",
            "trigger_level": 3370.0, "entry": 3372.5, "stop_loss": 3362.1,
            "take_profits": [3385.0, 3394.0], "risk_reward": rr,
            "confidence": confidence, "reasons": ["Bullish BOS", "EMA alignment"],
        }],
        "snapshot": {
            "features": {
                "symbol": "XAUUSD", "timeframe": "15m", "price": 3374.0,
                "trend": "bullish", "event_kind": "bos_up", "trend_bias": "bullish",
                "volume_ratio": 1.6, "volume_above_avg": True, "volume_spike": False,
                "above_vwap": True, "rsi": 62, "macd_hist": 1.2, "adx": 28,
                "atr_pct": 0.22, "bb_compress": False, "nearest_bull_ob": 3370.0,
                "nearest_bear_ob": 3400.0, "fvg_bull_count": 1, "fvg_bear_count": 0,
                "premium_discount": "discount", "swing_high": 3406.0,
                "swing_low": 3360.0, "liquidity_above": [3406.0],
                "liquidity_below": [], "equal_highs": [], "equal_lows": [],
            },
            "scores": {"bull": {"confidence_pct": confidence}, "bear": {"confidence_pct": 20}},
        },
        "mtf": {"htf_bias": "bullish", "ltf_bias": "bullish",
                "alignment": {"score": 55, "label": "aligned_bull"},
                "views": {"1h": {"trend": "bull"}}},
        "context": {"macro": {"available": True, "high_impact_imminent": False, "events": []},
                    "geopolitics": {"elevated": False}, "fear_greed": {"available": False},
                    "social": {"count": 0}, "news": {"count": 0},
                    "equities": {"change_pct": {}}},
        "market_context": {"data_symbol": "PAXGUSDT", "futures": False},
    }


def test_intelligence_allows_only_high_quality_trade():
    df = pd.DataFrame([
        {"open": 3370.0, "high": 3378.0, "low": 3368.0, "close": 3376.0},
        {"open": 3374.0, "high": 3380.0, "low": 3370.0, "close": 3379.0},
    ])
    out = build_intelligence(_payload(), df=df)
    assert out["asset"] == "XAUUSD"
    assert out["signal"] == "BUY"
    assert out["confidence"] == 88
    assert out["market_structure"] == "BOS"
    assert out["risk_reward"] == "1:2.5"
    assert out["trade_filter"]["confidence_minimum"]["ok"] is True
    assert out["self_review"]["would_professional_take_trade"] is True


def test_intelligence_rejects_low_confidence_or_bad_rr():
    low = build_intelligence(_payload(confidence=72))
    assert low["signal"] == "NO TRADE"
    assert any("confidence minimum" in r.lower() for r in low["reason"])

    bad_rr = build_intelligence(_payload(rr=1.4))
    assert bad_rr["signal"] == "NO TRADE"
    assert bad_rr["trade_filter"]["rr_minimum"]["ok"] is False


def test_intelligence_rejects_missing_data():
    out = build_intelligence({"signal": {"asset": "XAUUSD"}})
    assert out["signal"] == "NO TRADE"
    assert out["confidence"] == 0
    assert out["reason"] == ["Insufficient market data."]
