"""engine/lifecycle.py

The signal lifecycle — human-in-the-loop approval + full audit trail.

A signal is born the moment the engine scans. It then flows through states
that a human (you) can advance with one command:

    CREATED ──▶ PENDING_REVIEW ──▶ APPROVED ──▶ EXECUTED ──▶ CLOSED (outcome recorded)
                    │                   │            │
                    │                   └─▶ SKIPPED ──┘
                    └─▶ REJECTED

* CREATED         engine produced the signal (scan/watch)
* PENDING_REVIEW  awaiting a human decision (the approval gate)
* APPROVED        human said "yes, I'll take this"
* REJECTED        human said "no" (reason stored for learning)
* EXECUTED        the approved trade was actually placed
* SKIPPED         approved but not taken (missed / changed mind)
* CLOSED          the trade outcome was recorded (win/loss), closing the loop

Every transition is written to the `decisions` table so the coach can later
teach from *your* decision history, and the calibrator can learn which signal
types you (and the engine) actually profit from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

VALID_STATES = {
    "CREATED", "PENDING_REVIEW", "APPROVED", "REJECTED",
    "EXECUTED", "SKIPPED", "CLOSED",
}
TRANSITIONS = {
    "CREATED": {"PENDING_REVIEW"},
    "PENDING_REVIEW": {"APPROVED", "REJECTED"},
    "APPROVED": {"EXECUTED", "SKIPPED"},
    "EXECUTED": {"CLOSED"},
    "SKIPPED": {"CLOSED"},
    "REJECTED": set(),
    "CLOSED": set(),
}

# For feedback prompts in the approval UI / CLI
REJECT_REASONS = [
    "low_confidence", "bad_risk_reward", "trend_conflict", "news_conflict",
    "already_in_position", "avoid_overtrade", "other",
]


@dataclass
class LifecycleError(Exception):
    message: str


def can_transition(current: str, target: str) -> bool:
    return current in TRANSITIONS and target in TRANSITIONS[current]


def next_states(current: str) -> list[str]:
    return sorted(TRANSITIONS.get(current, set()))


def transition(current: str, target: str) -> str:
    """Validate and apply a lifecycle transition. Returns the new state."""
    cur = (current or "CREATED").upper()
    tgt = target.upper()
    if cur not in VALID_STATES:
        raise LifecycleError(f"unknown current state: {current}")
    if tgt not in VALID_STATES:
        raise LifecycleError(f"unknown target state: {target}")
    if not can_transition(cur, tgt):
        raise LifecycleError(f"cannot go {cur} → {tgt} (allowed: {next_states(cur)})")
    return tgt


def reviewable(sig: dict) -> bool:
    """A signal is worth putting in front of a human if it's actionable."""
    return sig.get("action") in ("BUY", "SELL") and sig.get("signal_type") == "SIGNAL"
