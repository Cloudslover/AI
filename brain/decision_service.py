"""Three-layer decision contract for the CryptoBrain desk.

Analytical confidence answers "how strong is this setup?".  Execution
probability answers "how likely is this conditional order to fill?".  They are
intentionally separate: a high-confidence pullback that never arrives remains
a watch item, not an active trade.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Iterable, Mapping


def _plan_dict(plan) -> dict:
    if hasattr(plan, "as_dict"):
        return plan.as_dict()
    return deepcopy(dict(plan))


def build_candidate_layers(plans: Iterable, min_confidence: int = 55) -> dict:
    """Split generated plans into conditional watch items and one active entry.

    Only an authorized, threshold-passing, immediately executable plan can be
    the ``active_candidate``.  Every other plan stays visible for research and
    calibration; authorization never suppresses learning output.
    """
    raw = [_plan_dict(p) for p in plans]
    eligible: list[dict] = []
    watch_items: list[dict] = []

    for plan in raw:
        authorized = bool(plan.get("primary", True))
        immediate = (plan.get("execution_mode") or
                     ("conditional" if plan.get("status") == "waiting" else "immediate")) == "immediate"
        active = plan.get("status", "active") == "active"
        above_threshold = int(plan.get("confidence") or 0) >= int(min_confidence)
        if authorized and immediate and active and above_threshold:
            eligible.append(plan)
            continue

        reason = (
            "awaiting market trigger" if not immediate or not active else
            "outside authorized setup family" if not authorized else
            "below active-candidate threshold"
        )
        item = deepcopy(plan)
        item["watch_reason"] = reason
        item["analytical_confidence"] = item.get("confidence")
        item["execution_probability"] = item.get("fill_probability")
        watch_items.append(item)

    eligible.sort(key=lambda p: (int(p.get("confidence") or 0),
                                 float(p.get("risk_reward") or 0)), reverse=True)
    candidate = deepcopy(eligible[0]) if eligible else None
    if candidate:
        candidate["analytical_confidence"] = candidate.get("confidence")
        candidate["execution_probability"] = candidate.get("fill_probability", 1.0)

    return {
        "watch_items": watch_items,
        "active_candidate": candidate,
        "desk_verdict": {
            "status": "PENDING_DESK" if candidate else "NO_TRADE",
            "action": candidate.get("action") if candidate else "NO TRADE",
            "execution_probability": (candidate.get("execution_probability")
                                      if candidate else None),
            "reason": ("active candidate awaiting desk gates" if candidate else
                       "no authorized immediate-entry candidate; conditional plans remain watch items"),
            "blocked_by": [],
        },
        "semantics": {
            "confidence": "per-plan analytical confluence; not a fill forecast",
            "execution_probability": "historical trigger/fill rate; 1.0 for an immediate candidate",
        },
    }


def finalize_decision_layers(layers: Mapping, desk_decision: Mapping | None) -> dict:
    """Attach the playbook/portfolio/risk-gated verdict to candidate layers."""
    out = deepcopy(dict(layers))
    candidate = out.get("active_candidate")
    desk = dict(desk_decision or {})
    action = desk.get("action", "NO TRADE")
    candidate_action = (candidate or {}).get("action")
    approved = bool(candidate and action in ("BUY", "SELL") and action == candidate_action)
    blocked = list(desk.get("blocked_by") or [])
    if candidate and action in ("BUY", "SELL") and action != candidate_action:
        blocked.append("desk/candidate direction mismatch")
    out["desk_verdict"] = {
        "status": "TRADE" if approved else "NO_TRADE",
        "action": action if approved else "NO TRADE",
        "execution_probability": ((candidate or {}).get("execution_probability")
                                  if approved else None),
        "analytical_confidence": ((candidate or {}).get("analytical_confidence")
                                  if candidate else None),
        "plan_id": (candidate or {}).get("id"),
        "plan_type": (candidate or {}).get("type"),
        "reason": (desk.get("decision_text") or
                   ("TRADE" if approved else "WAIT — no trade")),
        "blocked_by": blocked,
        "gates": deepcopy(desk.get("gates") or {}),
    }
    return out


def is_actionable(payload: Mapping) -> bool:
    """Canonical queue/notifier check; legacy ``signal`` is not authoritative."""
    verdict = ((payload.get("decision_service") or {}).get("desk_verdict") or {})
    return verdict.get("status") == "TRADE" and verdict.get("action") in ("BUY", "SELL")
