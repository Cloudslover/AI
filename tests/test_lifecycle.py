"""Tests for the signal lifecycle (human approval gate)."""
from __future__ import annotations

import pytest

from engine.lifecycle import (
    LifecycleError, can_transition, next_states, reviewable, transition,
)


def test_valid_states():
    assert can_transition("PENDING_REVIEW", "APPROVED")
    assert can_transition("PENDING_REVIEW", "REJECTED")
    assert can_transition("APPROVED", "EXECUTED")
    assert can_transition("APPROVED", "SKIPPED")
    assert can_transition("EXECUTED", "CLOSED")
    assert can_transition("CREATED", "PENDING_REVIEW")


def test_invalid_transitions():
    assert not can_transition("REJECTED", "APPROVED")   # dead end
    assert not can_transition("APPROVED", "PENDING_REVIEW")
    assert not can_transition("PENDING_REVIEW", "CLOSED")
    assert not can_transition("CLOSED", "EXECUTED")


def test_transition_roundtrip():
    assert transition("CREATED", "PENDING_REVIEW") == "PENDING_REVIEW"
    assert transition("PENDING_REVIEW", "APPROVED") == "APPROVED"


def test_transition_raises():
    with pytest.raises(LifecycleError):
        transition("PENDING_REVIEW", "CLOSED")


def test_next_states():
    assert next_states("PENDING_REVIEW") == ["APPROVED", "REJECTED"]


def test_reviewable():
    assert reviewable({"action": "BUY", "signal_type": "SIGNAL"})
    assert reviewable({"action": "SELL", "signal_type": "SIGNAL"})
    assert not reviewable({"action": "NO TRADE", "signal_type": "MONITOR"})
