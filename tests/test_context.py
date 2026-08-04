"""Tests for the market-context layer (network mocked / offline)."""
from __future__ import annotations

import pytest

from brain import context as ctx_mod


def test_cycle_phase_deterministic():
    c = ctx_mod.cycle()
    assert c["available"] is True
    assert c["phase"] in ("early-post-halving", "expansion", "late-cycle", "pre-halving")
    assert c["days_since_halving"] > 0
    # position proxy only when price+sma given
    assert c["position_vs_200d"] is None
    c2 = ctx_mod.cycle(sma200_1d=60_000, price_1d=66_000)
    assert c2["position_vs_200d"] == "above-200d"
    c3 = ctx_mod.cycle(sma200_1d=60_000, price_1d=56_000)
    assert c3["position_vs_200d"] == "below-200d"


def test_macro_events_have_shape():
    m = ctx_mod.macro_events()
    assert m["available"] is True
    for e in m["events"]:
        assert {"name", "date", "days_until", "high_impact"} <= set(e)
    assert isinstance(m["high_impact_imminent"], bool)


def test_social_pulse():
    headlines = [
        {"title": "Elon Musk tweets about bitcoin again"},
        {"title": "SEC approves new bitcoin ETF"},
        {"title": "Regular market update"},
    ]
    s = ctx_mod.social_pulse(headlines)
    assert s["count"] >= 2
    kws = {h["keyword"] for h in s["influencer_mentions"]}
    assert "elon" in kws and "sec" in kws


def test_geopolitics():
    headlines = [
        {"title": "War escalates in the region, oil prices jump"},
        {"title": "BTC consolidates"},
    ]
    g = ctx_mod.geopolitics(headlines)
    assert g["count"] >= 1
    assert g["elevated"] is False  # only 1 hit


def test_geopolitics_elevated():
    headlines = [
        {"title": "War escalates, missiles fired"},
        {"title": "Sanctions announced amid conflict"},
        {"title": "Military buildup continues"},
    ]
    g = ctx_mod.geopolitics(headlines)
    assert g["elevated"] is True


def test_risk_regime():
    eq = {"available": True, "change_pct": {"^spx": 1.2, "^ndq": 1.8, "dx.f": -0.3}}
    fng = {"available": True, "value": 72, "label": "Greed"}
    dom = {"available": True, "btc_dominance": 53}
    r = ctx_mod.risk_regime(eq, fng, dom)
    assert r["regime"] == "risk_on"
    assert r["score"] >= 2


def test_risk_regime_off():
    eq = {"available": True, "change_pct": {"^spx": -1.5, "^ndq": -2.1, "dx.f": 0.8}}
    fng = {"available": True, "value": 22, "label": "Extreme Fear"}
    dom = {"available": True, "btc_dominance": 58}
    r = ctx_mod.risk_regime(eq, fng, dom)
    assert r["regime"] == "risk_off"


def test_collect_degrades_without_network(monkeypatch):
    """collect() must never raise even if every external API fails."""
    def unavailable(*a, **k):
        return {"available": False}
    monkeypatch.setattr(ctx_mod, "fear_greed", unavailable)
    monkeypatch.setattr(ctx_mod, "dominance", unavailable)
    monkeypatch.setattr(ctx_mod, "equities", unavailable)
    monkeypatch.setattr(ctx_mod, "macro_events", lambda: {"available": True,
                                                          "events": [], "high_impact_imminent": False})
    monkeypatch.setattr(ctx_mod, "cycle", lambda *a, **k: {"available": True, "phase": "expansion"})
    monkeypatch.setattr(ctx_mod, "fetch_news", lambda limit=15: {"headlines": []})
    c = ctx_mod.collect()
    assert c["fear_greed"]["available"] is False
    assert c["dominance"]["available"] is False
    assert c["equities"]["available"] is False
    assert "risk_regime" in c
