"""Tests for the SQLite signal database (offline, tmp_path)."""
from __future__ import annotations

from data.database import SignalDB


def _payload() -> dict:
    return {
        "signal": {
            "signal_id": "BTCUSDT_20260804_1452", "timestamp": 1785826521000,
            "asset": "BTCUSDT", "action": "BUY", "entry": 61250.0,
            "stop_loss": 60700.0, "take_profit": 62200.0, "risk_reward": 2.1,
            "confidence": "HIGH", "timeframe": "15m", "reason": "test",
            "signal_type": "SIGNAL",
        },
        "plans": [
            {"id": "imm_buy", "type": "Immediate Buy", "action": "BUY",
             "condition": "enter now", "trigger_level": None, "entry": 61250.0,
             "stop_loss": 60700.0, "take_profits": [62200.0, 63200.0],
             "risk_reward": 2.1, "confidence": 90, "confidence_label": "HIGH",
             "status": "active"},
            {"id": "buy_pullback", "type": "Buy Pullback", "action": "BUY",
             "condition": "pullback to OB", "trigger_level": 61000.0,
             "entry": 61000.0, "stop_loss": 60600.0, "take_profits": [61900.0],
             "risk_reward": 2.0, "confidence": 84, "confidence_label": "HIGH",
             "status": "waiting"},
        ],
        "snapshot": {"features": {"price": 61250.0, "trend": "bullish"}},
        "market_context": {"funding_rate_pct": 0.01},
    }


def test_save_and_read_scan(tmp_path):
    db = SignalDB(tmp_path / "test.db")
    scan_id = db.save_scan(_payload())
    assert scan_id > 0
    latest = db.latest_scans(limit=10)
    assert len(latest) == 1
    assert latest[0]["symbol"] == "BTCUSDT"
    assert latest[0]["action"] == "BUY"
    db.close()


def test_plans_persisted(tmp_path):
    db = SignalDB(tmp_path / "test.db")
    db.save_scan(_payload())
    rows = db.conn.execute("SELECT * FROM plans").fetchall()
    assert len(rows) == 2
    types = {r["type"] for r in rows}
    assert types == {"Immediate Buy", "Buy Pullback"}
    db.close()


def test_plan_stats(tmp_path):
    db = SignalDB(tmp_path / "test.db")
    db.save_scan(_payload())
    stats = db.plan_stats()
    assert len(stats) == 2
    by_type = {s["type"]: s for s in stats}
    assert by_type["Immediate Buy"]["n"] == 1
    assert by_type["Immediate Buy"]["avg_conf"] == 90.0
    db.close()


def test_backtest_rows_and_stats(tmp_path):
    db = SignalDB(tmp_path / "test.db")
    rows = [
        {"ts": 1, "symbol": "BTCUSDT", "timeframe": "15m", "plan_type": "Immediate Buy",
         "action": "BUY", "confidence_pct": 85, "horizon_hours": 4.0,
         "outcome": "FULL_WIN", "rr_achieved": 2.0, "max_favorable": 300.0,
         "max_adverse": -50.0, "entry": 60000.0, "trigger_level": None},
        {"ts": 2, "symbol": "BTCUSDT", "timeframe": "15m", "plan_type": "Immediate Buy",
         "action": "BUY", "confidence_pct": 70, "horizon_hours": 4.0,
         "outcome": "LOSS", "rr_achieved": -1.0, "max_favorable": 20.0,
         "max_adverse": -400.0, "entry": 60500.0, "trigger_level": None},
    ]
    n = db.save_backtest_rows(rows, run_id="test_run")
    assert n == 2
    stats = db.backtest_stats()
    assert stats["overall"]["n"] == 2
    assert stats["overall"]["win_rate"] == 0.5
    assert stats["by_type"][0]["plan_type"] == "Immediate Buy"
    # confidence buckets: 85 -> HIGH, 70 -> MEDIUM
    buckets = {b["bucket"]: b for b in stats["by_confidence"]}
    assert buckets["HIGH"]["win_rate"] == 1.0
    assert buckets["MEDIUM"]["win_rate"] == 0.0
    db.close()
