"""Tests for the Coach teaching layer."""
from __future__ import annotations

from brain.coach import GLOSSARY, _expand, explain_signal, mentor, personal_feedback
from data.database import SignalDB


def _payload() -> dict:
    return {
        "signal": {"signal_id": "BTCUSDT_20260804_1452", "action": "BUY",
                   "asset": "BTCUSDT", "timeframe": "15m", "confidence": "HIGH",
                   "reason": "Bullish BOS + volume spike above VWAP + bullish RSI divergence"},
        "plans": [
            {"type": "Buy Pullback", "action": "BUY", "confidence": 84,
             "condition": "IF price pulls back to bullish Order Block near 61000.00 AND shows rejection",
             "entry": 61000.0, "stop_loss": 60600.0,
             "take_profits": [61900.0, 62800.0], "risk_reward": 2.2,
             "status": "waiting", "reasons": ["Bullish structure (bos_up)",
                                               "Unfilled bullish fair value gap"]},
        ],
        "snapshot": {"features": {"trend": "bullish", "ema_alignment_bull": True,
                                  "supertrend_bull": True, "adx": 28, "rsi": 58,
                                  "volume_spike": True, "volume_ratio": 2.4,
                                  "above_vwap": True, "close_vs_vwap_pct": 0.4,
                                  "event_kind": "bos_up", "premium_discount": "discount",
                                  "premium_discount_position": 0.3,
                                  "sweep": {"side": "sellside", "level": 60500.0},
                                  "rsi_divergence": {"bull": 2, "bear": 0}}},
    }


def test_glossary_has_core_terms():
    for term in ("BOS", "CHOCH", "FVG", "Order Block", "Liquidity Sweep", "VWAP",
                 "Risk:Reward", "Expectancy"):
        assert term in GLOSSARY


def test_expand_annotates_terms():
    out = _expand("IF price pulls back to bullish Order Block near 61000 AND shows rejection")
    assert "Order Block" in out and "footprint" in out


def test_explain_signal_speaks_plain():
    lines = explain_signal(_payload())
    joined = "\n".join(lines).lower()
    assert "trend is bullish" in joined
    assert "rsi 58.0" in joined
    assert "volume is 2.4x" in joined
    assert "sl = where you're wrong" in joined  # the safety reminder


def test_mentor_walks_through():
    out = mentor(_payload())
    assert "1." in out and "Entry" in out and "Stop at" in out
    assert "Take profits" in out
    assert "Risk:reward" in out


def test_mentor_no_plans():
    out = mentor({"signal": {"action": "NO TRADE"}, "plans": [],
                  "snapshot": {"features": {"trend": "mixed", "price": 60000.0,
                                            "trend_bias": "neutral"}}})
    assert "best trade is no trade" in out.lower()


def test_personal_feedback_empty(tmp_path):
    db = SignalDB(tmp_path / "t.db")
    fb = personal_feedback(db)
    assert isinstance(fb, list)
    db.close()


def test_personal_feedback_with_activity(tmp_path):
    db = SignalDB(tmp_path / "t.db")
    from tests.test_database import _payload as mk
    sid = db.save_scan(mk())
    db.update_status(sid, "APPROVED", note="strong setup")
    fb = personal_feedback(db)
    assert any("approved" in f for f in fb)
    db.close()
