"""Offline tests for the strict paper-operations preflight."""
from __future__ import annotations

import config
import pytest

from brain.preflight import FAIL, PASS, WARN, format_preflight, preflight_report


@pytest.fixture
def safe_config(monkeypatch):
    monkeypatch.setattr(config, "SYMBOLS", ["BTCUSDT", "ETHUSDT", "XAUUSD"])
    monkeypatch.setattr(config, "PROGRESSION", "simulator")
    monkeypatch.setattr(config, "ENFORCE_RISK_LIMITS", True)
    monkeypatch.setattr(config, "TRADER_STATE_BLOCK", True)
    monkeypatch.setattr(config, "DESK_DEFAULT", True)
    monkeypatch.setattr(config, "PRIMARY_SETUP_FAMILY", "sweep_trend_continuation")
    monkeypatch.setattr(config, "GOLD_SESSION_MODE", "block")
    monkeypatch.setattr(config, "DASHBOARD_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr(config, "DISCORD_ANNOUNCE_WEBHOOK", "")
    for name in (
        "BINANCE_API_KEY", "BINANCE_SECRET_KEY", "BINANCE_API_SECRET",
        "EXCHANGE_API_KEY", "EXCHANGE_API_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


def _health(*, mode="live", ages=None, cross=True):
    ages = ages or {"BTCUSDT": 100, "ETHUSDT": 200, "XAUUSD": 300}
    probes = {
        symbol: {
            "ok": True,
            "bars": 60,
            "last": price,
            "last_ts": 1_800_000_000_000,
            "age_seconds": ages.get(symbol),
        }
        for symbol, price in (
            ("BTCUSDT", 60_000.0), ("ETHUSDT", 3_000.0), ("XAUUSD", 2_300.0)
        )
    }
    cross_payload = {
        "ok": True,
        "threshold_pct": 1.0,
        "exchanges": {
            "kucoin": {"ok": True, "symbols": {
                symbol: {"deviation_pct": 0.1, "flag": False}
                for symbol in probes
            }},
            "okx": {"ok": True, "symbols": {
                symbol: {"deviation_pct": -0.1, "flag": False}
                for symbol in probes
            }},
        },
    } if cross else {"ok": False, "note": "unavailable"}
    return {
        "ok": True,
        "data": {
            "mode": mode,
            "ok": True,
            "probe": probes,
            "cross_exchange": cross_payload,
        },
        "database": {"ok": True, "path": "/var/lib/cryptobrain/cryptobrain.db"},
        "risk_gate": {
            "allowed": True,
            "blocked_by": [],
            "progression": {"level": "simulator"},
        },
    }


def _row(report, name):
    return next(row for row in report["checks"] if row["name"] == name)


def test_live_safe_configuration_is_ready(safe_config):
    report = preflight_report(health=_health())
    assert report["ready"] is True
    assert report["summary"]["failures"] == 0
    assert _row(report, "data_mode")["status"] == PASS
    assert _row(report, "candle_freshness")["status"] == PASS
    # Notifications are useful but must not make the engine unsafe to run.
    assert _row(report, "notifications")["status"] == WARN


def test_demo_requires_explicit_rehearsal_flag(safe_config):
    strict = preflight_report(health=_health(mode="demo", cross=False))
    assert strict["ready"] is False
    assert _row(strict, "data_mode")["status"] == FAIL

    rehearsal = preflight_report(
        health=_health(mode="demo", cross=False), allow_demo=True
    )
    assert rehearsal["ready"] is True
    assert rehearsal["profile"] == "paper-rehearsal"
    assert _row(rehearsal, "data_mode")["status"] == WARN


def test_every_watchlist_feed_is_required(safe_config):
    health = _health()
    health["data"]["probe"]["ETHUSDT"] = {
        "ok": False, "bars": 0, "error": "network blocked"
    }
    report = preflight_report(health=health)
    assert report["ready"] is False
    row = _row(report, "market_feeds")
    assert row["status"] == FAIL
    assert "ETHUSDT" in row["details"]["failed"]


def test_live_database_must_be_durable_and_outside_checkout(safe_config):
    health = _health()
    health["database"]["path"] = str(config.ROOT / "data" / "cryptobrain.db")

    strict = preflight_report(health=health)
    assert strict["ready"] is False
    assert _row(strict, "database_location")["status"] == FAIL

    # --allow-demo cannot weaken a live-data run.
    live_with_flag = preflight_report(health=health, allow_demo=True)
    assert live_with_flag["profile"] == "live-paper"
    assert _row(live_with_flag, "database_location")["status"] == FAIL

    health["database"]["path"] = "/tmp/disposable-paper.db"
    ephemeral = preflight_report(health=health)
    assert _row(ephemeral, "database_location")["status"] == FAIL

    health["data"]["mode"] = "demo"
    rehearsal = preflight_report(health=health, allow_demo=True)
    assert _row(rehearsal, "database_location")["status"] == WARN


def test_stale_future_or_unknown_live_candle_blocks_startup(safe_config):
    report = preflight_report(health=_health(ages={
        "BTCUSDT": -120,
        "ETHUSDT": 31 * 60,
        "XAUUSD": None,
    }))
    assert report["ready"] is False
    row = _row(report, "candle_freshness")
    assert row["status"] == FAIL
    assert any("ETHUSDT" in item for item in row["details"]["stale"])
    assert any("BTCUSDT" in item for item in row["details"]["future"])
    assert row["details"]["unknown"] == ["XAUUSD"]


def test_unsafe_operating_controls_block_startup(safe_config, monkeypatch):
    monkeypatch.setattr(config, "PROGRESSION", "micro")
    monkeypatch.setattr(config, "ENFORCE_RISK_LIMITS", False)
    monkeypatch.setattr(config, "DESK_DEFAULT", False)
    monkeypatch.setattr(config, "PRIMARY_SETUP_FAMILY", "all")
    monkeypatch.setattr(config, "GOLD_SESSION_MODE", "warn")
    report = preflight_report(health=_health())
    assert report["ready"] is False
    for name in ("progression", "risk_controls", "desk_policy", "gold_session"):
        assert _row(report, name)["status"] == FAIL


def test_cross_exchange_deviation_blocks_startup(safe_config):
    health = _health()
    info = health["data"]["cross_exchange"]["exchanges"]["okx"]["symbols"]["BTCUSDT"]
    info.update({"deviation_pct": 1.25, "flag": True})
    report = preflight_report(health=health)
    assert report["ready"] is False
    assert _row(report, "cross_exchange")["status"] == FAIL


def test_closed_risk_gate_is_warning_not_monitoring_failure(safe_config):
    health = _health()
    health["risk_gate"].update({
        "allowed": False,
        "blocked_by": ["daily loss limit reached"],
    })
    report = preflight_report(health=health)
    assert report["ready"] is True
    assert _row(report, "risk_gate")["status"] == WARN


def test_format_preflight_surfaces_verdict(safe_config):
    text = format_preflight(preflight_report(health=_health()))
    assert "PAPER OPERATIONS PREFLIGHT" in text
    assert "READY FOR PAPER OPERATIONS" in text
    assert "candle_freshness" in text
