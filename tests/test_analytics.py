"""Analytics tests: MAE/MFE summary + Monte Carlo equity distribution.

Both functions read db.decided_paper_rows(exclude_sim=True) — simulator
samples (sim_key NOT NULL) are excluded from the live book the desk reviews.
"""
from __future__ import annotations

import sqlite3

import pytest

from brain.analytics import mae_mfe_summary, monte_carlo_equity
from data.database import SignalDB


# ── fixture + helper (defined here so pytest discovers them) ───────────────

@pytest.fixture
def db():
    d = SignalDB(path=":memory:")
    d.conn.row_factory = sqlite3.Row
    counter = [0]

    def add_trade(**kw):
        sid = 1000 + counter[0]
        counter[0] += 1
        d.conn.execute(
            "INSERT INTO paper_trades "
            "(scan_id,signal_id,plan_id,plan_type,symbol,timeframe,action,"
            "entry,stop_loss,take_profit,risk_reward,confidence_pct,status,"
            "created_ts,opened_ts,closed_ts,entry_price,exit_price,"
            "outcome,rr_achieved,close_reason,last_candle_ts,last_price,"
            "checks,error,regime,mae,mfe,sim_key) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, "s1", "p1", kw.pop("plan_type", "trend_following"),
             kw.pop("symbol", "BTC"), kw.pop("timeframe", "1h"),
             kw.pop("action", "BUY"),
             kw.pop("entry", 100.0), kw.pop("stop_loss", 90.0),
             kw.pop("take_profit", 120.0), kw.pop("risk_reward", 2.0),
             kw.pop("confidence_pct", 70), kw.pop("status", "CLOSED"),
             1000, 1100, 2000,   # created_ts, opened_ts, closed_ts
             kw.pop("entry_price", 100.0), kw.pop("exit_price", 100.0),
             kw.pop("outcome", "TP_Hit"), kw.pop("rr_achieved", 2.0),
             kw.pop("close_reason", "slip"),
             2000, 100.0,
             counter[0],          # checks (unique per trade)
             kw.pop("error", None), kw.pop("regime", ""),
             kw.pop("mae", None), kw.pop("mfe", None),
             kw.pop("sim_key", None)),
        )
        counter[0] += 1
        d.conn.commit()

    d.add_trade = add_trade
    return d


# ── MAE / MFE summary ──────────────────────────────────────────────────────

def test_mae_mfe_no_trades(db):
    r = mae_mfe_summary(db)
    assert r["available"] is False
    assert "note" in r


def test_mae_mfe_empty_filter(db):
    r = mae_mfe_summary(db, plan_type="nonexistent")
    assert r["available"] is False


def test_mae_mfe_by_setup(db):
    db.add_trade( plan_type="trend_following", outcome="TP_HIT",
              rr_achieved=2.0, mae=5.0, mfe=15.0)
    db.add_trade( plan_type="trend_following", outcome="STOP_LOSS",
              rr_achieved=-1.0, mae=9.5, mfe=3.0)
    db.add_trade( plan_type="reversal", outcome="TP_HIT",
              rr_achieved=1.5, mae=3.0, mfe=8.0)
    db.add_trade( plan_type="reversal", outcome="STOP_LOSS",
              rr_achieved=-1.0, mae=8.0, mfe=2.0)

    r = mae_mfe_summary(db)
    assert r["available"] is True
    by = r["by_setup"]
    assert "trend_following" in by
    assert "reversal" in by
    tf = by["trend_following"]
    assert tf["n"] == 2
    assert tf["win_rate"] == 0.5
    assert tf["avg_mae_r"] == pytest.approx(0.725, abs=1e-3)
    assert tf["max_mae_r"] == pytest.approx(0.95, abs=1e-3)
    assert tf["avg_mfe_r"] == pytest.approx(0.9, abs=1e-3)
    assert tf["max_mfe_r"] == pytest.approx(1.5, abs=1e-3)
    rv = by["reversal"]
    assert rv["n"] == 2
    assert rv["win_rate"] == 0.5


def test_mae_mfe_overall_insight(db):
    db.add_trade( plan_type="trend_following", outcome="TP_HIT",
              rr_achieved=2.0, mae=5.0, mfe=15.0)
    db.add_trade( plan_type="trend_following", outcome="STOP_LOSS",
              rr_achieved=-1.0, mae=9.5, mfe=3.0)
    db.add_trade( plan_type="reversal", outcome="TP_HIT",
              rr_achieved=1.5, mae=3.0, mfe=8.0)
    db.add_trade( plan_type="reversal", outcome="STOP_LOSS",
              rr_achieved=-1.0, mae=8.0, mfe=2.0)

    r = mae_mfe_summary(db)
    assert r["overall"]["n"] == 4
    assert r["overall"]["avg_mae_r"] == pytest.approx(0.6375, abs=1e-3)
    assert r["overall"]["avg_mfe_r"] == pytest.approx(0.7, abs=1e-3)
    assert isinstance(r["insight"], list)
    assert len(r["insight"]) >= 1


def test_mae_mfe_high_mae_insight(db):
    db.add_trade( outcome="TP_HIT", rr_achieved=2.0, mae=9.5, mfe=12.0)
    db.add_trade( outcome="STOP_LOSS", rr_achieved=-1.0, mae=9.0, mfe=2.0)

    r = mae_mfe_summary(db)
    insight = r["insight"]
    assert any("MAE averages" in s and "0.9" in s for s in insight)


def test_mae_mfe_low_mae_insight(db):
    db.add_trade( outcome="TP_HIT", rr_achieved=2.0, mae=2.5, mfe=8.0)
    db.add_trade( outcome="STOP_LOSS", rr_achieved=-1.0, mae=3.5, mfe=1.0)

    r = mae_mfe_summary(db)
    insight = r["insight"]
    assert any("only" in s and "R" in s for s in insight)


def test_mae_mfe_runner_insight(db):
    db.add_trade( outcome="TP_HIT", rr_achieved=2.0, mae=4.0, mfe=18.0)
    db.add_trade( outcome="STOP_LOSS", rr_achieved=-1.0, mae=5.0, mfe=12.0)

    r = mae_mfe_summary(db)
    insight = r["insight"]
    assert any("runner" in s.lower() for s in insight)


def test_mae_mfe_plan_type_filter(db):
    db.add_trade( plan_type="trend_following", outcome="TP_HIT",
              rr_achieved=2.0, mae=5.0, mfe=15.0)
    db.add_trade( plan_type="reversal", outcome="TP_HIT",
              rr_achieved=1.5, mae=3.0, mfe=8.0)

    r_all = mae_mfe_summary(db)
    assert r_all["overall"]["n"] == 2
    r_filt = mae_mfe_summary(db, plan_type="trend_following")
    assert r_filt["overall"]["n"] == 1
    assert "trend_following" in r_filt["by_setup"]
    assert "reversal" not in r_filt["by_setup"]


def test_mae_mfe_missing_fields(db):
    db.add_trade( outcome="TP_HIT", rr_achieved=2.0, mae=None, mfe=None)
    r = mae_mfe_summary(db)
    assert r["available"] is True
    assert r["overall"]["avg_mae_r"] is None
    assert r["overall"]["avg_mfe_r"] is None


# ── Monte Carlo equity ─────────────────────────────────────────────────────

def test_mc_no_trades(db):
    r = monte_carlo_equity(db)
    assert r["available"] is False
    assert "note" in r


def test_mc_structure(db):
    db.add_trade( outcome="TP_HIT", rr_achieved=2.0)
    db.add_trade( outcome="STOP_LOSS", rr_achieved=-1.0)
    db.add_trade( outcome="TP_HIT", rr_achieved=1.5)

    r = monte_carlo_equity(db, samples=500, seed=42)
    assert r["available"] is True
    assert r["start"] == 10_000.0
    assert r["risk_pct"] == 0.5
    assert r["n_trades"] == 3
    assert r["samples"] == 500
    t = r["terminal"]
    for k in ("median", "mean", "p5", "p95", "prob_profit"):
        assert k in t
    dd = r["drawdown"]
    for k in ("median_pct", "p95_pct"):
        assert k in dd
    assert 0.0 <= t["prob_profit"] <= 1.0


def test_mc_deterministic_with_seed(db):
    db.add_trade( outcome="TP_HIT", rr_achieved=2.0)
    db.add_trade( outcome="STOP_LOSS", rr_achieved=-1.0)

    r1 = monte_carlo_equity(db, samples=200, seed=7)
    r2 = monte_carlo_equity(db, samples=200, seed=7)
    assert r1["terminal"]["median"] == r2["terminal"]["median"]
    assert r1["drawdown"]["median_pct"] == r2["drawdown"]["median_pct"]


def test_mc_excludes_sim_samples(db):
    db.add_trade( outcome="TP_HIT", rr_achieved=2.0, sim_key=None)
    db.add_trade( outcome="TP_HIT", rr_achieved=3.0, sim_key="sim-1")
    db.add_trade( outcome="TP_HIT", rr_achieved=4.0, sim_key="sim-2")

    r = monte_carlo_equity(db, samples=100, seed=1)
    assert r["available"] is True
    assert r["n_trades"] == 1

