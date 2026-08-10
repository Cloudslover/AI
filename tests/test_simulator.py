"""Tests for the paper-sample grind (data/simulator.py): unique-sample
dedupe, paper-trade creation, progress accounting, and the PROGRESSION=micro
verdict.  Fully offline with a deterministic fake client."""
from __future__ import annotations

import pytest

from tests.conftest import make_ohlcv


class FakeClient:
    """Deterministic offline client: one seeded series per symbol."""

    def __init__(self, n: int = 400, seed: int = 11):
        self.n = n
        self.seed = seed
        self.calls = 0

    def klines(self, symbol="BTCUSDT", timeframe="15m", limit=500):
        self.calls += 1
        return make_ohlcv(n=max(self.n, limit), seed=self.seed + len(symbol))


@pytest.fixture
def sim_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setattr("config.DB_PATH", str(tmp_path / "sim.db"))
    yield tmp_path


def test_simulate_round_stores_unique_samples(sim_env):
    from data.database import SignalDB
    from data.simulator import simulate_round

    client = FakeClient(n=400, seed=5)
    r1 = simulate_round(symbols=["BTCUSDT"], bars=400, step=8,
                        min_confidence=50, horizons=[1], client=client)
    assert r1["backtest_added"] > 0
    assert r1["paper_added"] > 0
    assert r1["saved"] is True

    with SignalDB() as db:
        bt = db.conn.execute(
            "SELECT COUNT(*) n, COUNT(DISTINCT sim_key) keys "
            "FROM backtest_results").fetchone()
        pp = db.conn.execute(
            "SELECT COUNT(*) n, COUNT(DISTINCT sim_key) keys "
            "FROM paper_trades").fetchone()
    assert bt["n"] == bt["keys"] == r1["backtest_added"]  # all unique
    assert pp["n"] == pp["keys"] == r1["paper_added"]     # all unique
    # paper samples are decided + closed
    with SignalDB() as db:
        closed = db.conn.execute(
            "SELECT COUNT(*) n FROM paper_trades WHERE status='CLOSED' "
            "AND outcome IN ('TP_HIT','STOP_LOSS')").fetchone()["n"]
    assert closed == r1["paper_added"]


def test_simulate_round_dedupes_exact_rerun(sim_env):
    """Re-simulating the same history adds ZERO samples (honest counts)."""
    from data.simulator import simulate_round

    client = FakeClient(n=300, seed=7)
    r1 = simulate_round(symbols=["BTCUSDT"], bars=300, step=6,
                        min_confidence=50, horizons=[1], client=client)
    assert r1["backtest_added"] > 0
    r2 = simulate_round(symbols=["BTCUSDT"], bars=300, step=6,
                        min_confidence=50, horizons=[1], client=client)
    assert r2["backtest_added"] == 0
    assert r2["paper_added"] == 0


def test_simulate_round_dry_run_stores_nothing(sim_env):
    from data.database import SignalDB
    from data.simulator import simulate_round

    client = FakeClient(n=300, seed=9)
    r = simulate_round(symbols=["BTCUSDT"], bars=300, step=6, save=False,
                       min_confidence=50, horizons=[1], client=client)
    assert r["backtest_added"] > 0
    with SignalDB() as db:
        n = db.conn.execute("SELECT COUNT(*) n FROM backtest_results").fetchone()["n"]
    assert n == 0


def test_paper_progress_and_verdict(sim_env):
    from data.database import SignalDB
    from data.simulator import (grind_verdict, paper_progress, simulate_round,
                                primary_plan_types)

    client = FakeClient(n=500, seed=3)
    simulate_round(symbols=["BTCUSDT", "ETHUSDT", "XAUUSD"], bars=500,
                   step=4, min_confidence=50, horizons=[1], client=client)
    with SignalDB() as db:
        progress = paper_progress(db)
        verdict = grind_verdict(progress)
    assert progress  # at least one plan type tracked
    for p in progress:
        assert p["backtest_target"] == 100
        assert p["paper_target"] == 20
        assert p["backtest_n"] >= 0 and p["paper_n"] >= 0
    # verdict is a well-formed structure regardless of readiness
    assert set(verdict) >= {"ready", "primary_plan_types", "missing", "targets"}
    assert primary_plan_types()  # the A1 setup family is non-empty
    for m in verdict["missing"]:
        assert "missing" in m and "plan_type" in m


def test_grind_verdict_ready_when_proven(sim_env):
    from data.simulator import grind_verdict
    fake = [
        {"plan_type": "Sweep Reversal Buy", "backtest_n": 150, "paper_n": 25,
         "expectancy": 0.4, "proven": True},
        {"plan_type": "Sweep Reversal Sell", "backtest_n": 130, "paper_n": 21,
         "expectancy": 0.2, "proven": True},
        {"plan_type": "Buy Pullback", "backtest_n": 120, "paper_n": 22,
         "expectancy": 0.3, "proven": True},
        {"plan_type": "Sell Pullback", "backtest_n": 110, "paper_n": 24,
         "expectancy": 0.1, "proven": True},
    ]
    v = grind_verdict(fake)
    assert v["ready"] is True
    assert v["missing"] == []


def test_grind_verdict_lists_missing(sim_env):
    from data.simulator import grind_verdict
    fake = [
        {"plan_type": "Sweep Reversal Buy", "backtest_n": 150, "paper_n": 25,
         "expectancy": 0.4, "proven": True},
        # other three primary setups have no samples at all
    ]
    v = grind_verdict(fake)
    assert v["ready"] is False
    types_missing = {m["plan_type"] for m in v["missing"]}
    assert types_missing == {"Sweep Reversal Sell", "Buy Pullback", "Sell Pullback"}
