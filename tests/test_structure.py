"""Tests for market-structure detection."""
from __future__ import annotations

from engine.indicators import add_all_indicators
from engine.structure import (
    analyze_structure, detect_swings, detect_fvgs, detect_events,
)


def test_swings_found(df):
    swings = detect_swings(df)
    assert len(swings) >= 3
    kinds = {s.kind for s in swings}
    assert kinds == {"high", "low"}


def test_events_parse(df):
    swings = detect_swings(df)
    events = detect_events(df, swings)
    for ev in events:
        assert ev.kind in ("bos_up", "bos_down", "choch_up", "choch_down")
        assert ev.price > 0


def test_fvgs(df):
    fvgs = detect_fvgs(df)
    for f in fvgs:
        assert f.side in ("bullish", "bearish")
        assert f.top > f.bottom


def test_analyze_structure_shape(df):
    ind = add_all_indicators(df)
    ms = analyze_structure(ind)
    d = ms.as_dict()
    assert d["trend_bias"] in ("bullish", "bearish", "neutral")
    assert isinstance(d["liquidity_above"], list)
    assert isinstance(d["liquidity_below"], list)
    assert "order_blocks" in d and "fvgs" in d
    assert "premium_discount" in d


def test_sweep_detected(df):
    """Our synthetic data engineers a sell-side sweep — must be detected."""
    ind = add_all_indicators(df)
    ms = analyze_structure(ind)
    assert ms.sweep is not None
    assert ms.sweep["side"] == "sellside"
