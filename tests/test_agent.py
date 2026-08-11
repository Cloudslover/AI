"""Tests for the desk agent layer (brain/agent.py): health report, morning
briefing, natural-language ask.  All offline via DEMO_MODE=1 + temp DB."""
from __future__ import annotations

import pytest


@pytest.fixture
def desk_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setattr("config.DB_PATH", str(tmp_path / "agent.db"))
    yield tmp_path


def test_health_report_ok(desk_env):
    from brain.agent import health_report
    report = health_report()
    assert report["ok"] is True
    assert report["data"]["mode"] == "demo"
    assert report["database"]["ok"] is True
    assert report["risk_gate"]["allowed"] is True
    assert report["pending_reviews"] == 0
    assert report["mcp"]["available"] is True
    assert report["llm"]["provider"] == "off"
    # every watchlist symbol has a data probe
    assert set(report["data"]["probe"]) == {"BTCUSDT", "ETHUSDT", "XAUUSD"}
    assert all(p["ok"] for p in report["data"]["probe"].values())
    assert all(p.get("last_ts") is not None for p in report["data"]["probe"].values())
    assert all(p.get("age_seconds") is not None for p in report["data"]["probe"].values())


def test_health_report_format(desk_env):
    from brain.agent import format_health, health_report
    text = format_health(health_report())
    assert "VERDICT      : OK" in text
    assert "data mode" in text
    assert "BTCUSDT" in text


def test_data_probe_preserves_material_future_skew(monkeypatch):
    """Only tiny clock skew is clamped; preflight needs larger skew to fail."""
    import pandas as pd
    import brain.agent as agent

    class Client:
        def klines(self, symbol, timeframe, limit):
            assert (symbol, timeframe, limit) == ("BTCUSDT", "15m", 60)
            return pd.DataFrame({"ts": [1120] * 10, "close": [100.0] * 10})

    monkeypatch.setattr(agent, "SYMBOLS", ["BTCUSDT"])
    monkeypatch.setattr(agent.time, "time", lambda: 1000)
    probe = agent._probe_data(Client())["BTCUSDT"]
    assert probe["age_seconds"] == -120.0


def test_morning_briefing_assets_and_gate(desk_env):
    from brain.agent import morning_briefing
    b = morning_briefing(bars=200)
    assert len(b["assets"]) == 3
    for a in b["assets"]:
        assert a["ok"] is True
        assert a["desk_action"] in ("BUY", "SELL", "NO TRADE")
        assert a["signal_id"]
        assert a["confidence_pct"] is None or a["confidence_pct"] > 0
    assert b["risk_gate"]["allowed"] is True
    assert b["pending_reviews"] == 0
    assert b["narrative"]  # rule-based narrative always present
    assert "Risk gate OPEN" in b["narrative"]


def test_morning_briefing_json_safe(desk_env):
    """The briefing must be JSON-serializable (dashboard + MCP render it)."""
    import json
    from brain.agent import morning_briefing
    json.dumps(morning_briefing(bars=200), default=str)


def test_ask_risk_intent(desk_env):
    from brain.agent import ask
    r = ask("is the risk gate open?")
    assert r["intent"] == "risk"
    assert r["data"]["allowed"] is True
    assert any("GATE: OPEN" in line for line in r["answer"])


def test_ask_pending_and_journal(desk_env):
    from brain.agent import ask
    assert ask("what's pending review?").get("intent") == "pending"
    assert ask("how is my journal discipline?").get("intent") == "journal"
    assert ask("show me the paper book").get("intent") == "paper"
    assert ask("any exposure right now?").get("intent") == "exposure"


def test_ask_market_scan(desk_env):
    from brain.agent import ask
    r = ask("scan BTC", symbol="BTCUSDT", bars=200)
    assert r["intent"] == "market"
    assert r["data"]["signal"]["asset"] == "BTCUSDT"
    assert r["data"]["decision"]["action"] in ("BUY", "SELL", "NO TRADE")


def test_ask_help_fallback(desk_env):
    from brain.agent import ask
    r = ask("what can you do?")
    assert r["intent"] == "help"
    assert "calibration" in r["data"]["intents"]


def test_ask_graduation_intent(desk_env):
    """'am i ready for micro?' hits the graduation gate (BLUEPRINT Step 2→3)."""
    from brain.agent import ask
    r = ask("am i ready for micro?")
    assert r["intent"] == "graduation"
    assert "GRADUATION GATE" in "\n".join(r["answer"])
    g = r["data"]["graduation"]
    assert set(g["criteria"]) == {"expectancy", "win_rate", "pf", "compliance"}
    assert set(g["met"]) == {"expectancy", "win_rate", "pf", "compliance"}
    assert "ready" in g and "samples_proven" in g


def test_graduation_report_shape(desk_env):
    from brain.agent import graduation_report
    rep = graduation_report()
    assert set(rep) == {"progress", "graduation", "journal"}
    assert "ready" in rep["graduation"] and "stats" in rep["graduation"]
    assert rep["journal"]["violation_rate"] is None  # no journal entries yet


def test_health_report_skips_cross_exchange_in_demo(desk_env):
    """Demo mode has no live Binance prices, so the multi-exchange
    cross-check must degrade to a note instead of running."""
    from brain.agent import health_report
    report = health_report()
    cross = report["data"]["cross_exchange"]
    assert cross["ok"] is False
    assert "demo" in cross["note"]
    assert "exchanges" not in cross


def test_cross_exchange_probe_uses_newest_candle(monkeypatch):
    """KuCoin and OKX return newest-first; never compare an old candle."""
    from brain.agent import _cross_exchange_probe

    class Response:
        def __init__(self, data):
            self._data = data

        def json(self):
            return {"data": self._data}

    def fake_get(url, timeout):
        assert timeout == 6
        if "kucoin" in url:
            # KuCoin close is index 2.  The older row is intentionally far off.
            return Response([
                ["200", "99", "100", "101", "98", "1", "100"],
                ["100", "49", "50", "51", "48", "1", "50"],
            ])
        # OKX close is index 4 and is also newest-first.
        return Response([
            ["200", "99", "101", "98", "100", "1"],
            ["100", "49", "51", "48", "50", "1"],
        ])

    monkeypatch.setattr("requests.get", fake_get)
    cross = _cross_exchange_probe({"BTCUSDT": 100.0})

    assert cross["ok"] is True
    assert cross["exchanges"]["kucoin"]["symbols"]["BTCUSDT"] == {
        "price": 100.0, "deviation_pct": 0.0, "flag": False,
    }
    assert cross["exchanges"]["okx"]["symbols"]["BTCUSDT"] == {
        "price": 100.0, "deviation_pct": 0.0, "flag": False,
    }
