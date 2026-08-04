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


def validate_output(payload: dict) -> dict:
    """Validate a full BrainOutput dict; returns {ok, errors, warnings}."""
    errors, warnings = [], []
    sig = payload.get("signal", {})
    errors += [f"signal: {e}" for e in validate_signal(sig)]
    plans = payload.get("plans", [])
    if not plans and sig.get("action") != "NO TRADE":
        warnings.append("signal exists but no plans")
    for i, p in enumerate(plans):
        errors += [f"plan[{i}]: {e}" for e in validate_plan(p)]
    return {"ok": not errors, "errors": errors, "warnings": warnings}
