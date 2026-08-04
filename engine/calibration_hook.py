"""engine/calibration_hook.py

Thin indirection so `engine/rules.py` can apply calibration without a hard
dependency on the brain layer (keeps the engine import-light and offline).
"""
from __future__ import annotations


def apply_calibration(conf: int, plan_type: str, calibration: dict) -> tuple[int, bool]:
    """Return (adjusted_confidence, filtered_out) given a calibration profile."""
    if not calibration:
        return conf, False
    entry = calibration.get(plan_type)
    if not entry:
        return conf, False
    if entry.get("filtered"):
        return conf, True
    mult = entry.get("multiplier", 1.0)
    return max(5, min(100, int(round(conf * mult)))), False
