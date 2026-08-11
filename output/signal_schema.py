"""output/signal_schema.py

Validation for the CryptoBrain signal JSON so downstream consumers (webhooks,
dashboards, backtesters, your other agents) can rely on the shape.
"""
from __future__ import annotations

import re
from typing import Any

REQUIRED_SIGNAL_FIELDS = [
    "signal_id", "timestamp", "asset", "action", "entry", "stop_loss",
    "take_profit", "risk_reward", "confidence", "timeframe", "reason",
]
VALID_ACTIONS = {"BUY", "SELL", "NO TRADE"}
VALID_CONFIDENCE = {"HIGH", "MEDIUM", "LOW", "NO TRADE"}


def validate_signal(sig: dict) -> list[str]:
    errors = []
    for f in REQUIRED_SIGNAL_FIELDS:
        if f not in sig:
            errors.append(f"missing field: {f}")
    if "action" in sig and sig["action"] not in VALID_ACTIONS:
        errors.append(f"invalid action: {sig['action']}")
    if "confidence" in sig and sig["confidence"] not in VALID_CONFIDENCE:
        errors.append(f"invalid confidence: {sig['confidence']}")
    if "signal_id" in sig and not re.match(r"^[A-Z0-9]+_\d{8}_\d{4}$", sig["signal_id"]):
        errors.append(f"signal_id format: {sig['signal_id']}")
    if sig.get("entry") and sig.get("stop_loss"):
        if sig["action"] == "BUY" and sig["stop_loss"] >= sig["entry"]:
            errors.append("BUY stop_loss must be below entry")
        if sig["action"] == "SELL" and sig["stop_loss"] <= sig["entry"]:
            errors.append("SELL stop_loss must be above entry")
    return errors


def validate_plan(plan: dict) -> list[str]:
    errors = []
    for f in ("id", "type", "action", "condition", "entry", "stop_loss", "take_profits", "confidence"):
        if f not in plan:
            errors.append(f"missing plan field: {f}")
    if plan.get("entry") and plan.get("stop_loss"):
        if plan["action"] == "BUY" and plan["stop_loss"] >= plan["entry"]:
            errors.append("plan BUY stop_loss >= entry")
        if plan["action"] == "SELL" and plan["stop_loss"] <= plan["entry"]:
            errors.append("plan SELL stop_loss <= entry")
    return errors


def validate_decision_service(service: dict) -> list[str]:
    """Validate the v2.1 canonical watch/candidate/verdict contract."""
    errors: list[str] = []
    for field in ("watch_items", "active_candidate", "desk_verdict"):
        if field not in service:
            errors.append(f"missing decision_service field: {field}")
    candidate = service.get("active_candidate")
    if candidate:
        if not candidate.get("primary", True):
            errors.append("active_candidate is not authorized")
        if candidate.get("status", "active") != "active":
            errors.append("active_candidate is still waiting")
        if candidate.get("execution_mode", "immediate") != "immediate":
            errors.append("active_candidate is conditional")
        probability = candidate.get("execution_probability")
        if probability is not None and not 0 <= float(probability) <= 1:
            errors.append("active_candidate execution_probability outside 0..1")
    verdict = service.get("desk_verdict") or {}
    if verdict.get("status") == "TRADE":
        if not candidate:
            errors.append("TRADE verdict has no active_candidate")
        elif verdict.get("action") != candidate.get("action"):
            errors.append("TRADE verdict direction differs from active_candidate")
    return errors


def validate_output(payload: dict) -> dict:
    """Validate legacy compatibility plus the canonical v2.1 decision layers."""
    errors, warnings = [], []
    sig = payload.get("signal", {})
    errors += [f"signal: {e}" for e in validate_signal(sig)]
    plans = payload.get("plans", [])
    if not plans and sig.get("action") != "NO TRADE":
        warnings.append("signal exists but no plans")
    for i, p in enumerate(plans):
        errors += [f"plan[{i}]: {e}" for e in validate_plan(p)]
    if "decision_service" in payload:
        errors += [f"decision_service: {e}" for e in
                   validate_decision_service(payload["decision_service"])]
    else:
        warnings.append("legacy payload: decision_service missing")
    return {"ok": not errors, "errors": errors, "warnings": warnings}
