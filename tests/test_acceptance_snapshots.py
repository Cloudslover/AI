"""Daily end-to-end acceptance snapshots over frozen offline market frames.

Unlike a unit test, this exercises MTF -> functional core -> plan authorization
-> intelligence -> playbook/portfolio/risk desk -> three-layer decision output.
The blessed signature intentionally excludes timestamps and prices.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from brain.full_pipeline import analyze_full
from data.database import SignalDB

SAMPLES = Path(__file__).resolve().parent.parent / "data_samples"
BLESSED = json.loads((SAMPLES / "acceptance" / "blessed_signatures.json").read_text())


class RecordedAcceptanceClient:
    def __init__(self, symbol: str):
        path = (SAMPLES / "btcusdt_15m_sample.csv" if symbol == "BTCUSDT" else
                SAMPLES / "acceptance" / f"{symbol.lower()}_15m.csv")
        self.frame = pd.read_csv(path)

    def klines(self, symbol: str, timeframe: str, limit: int = 500, *args, **kwargs):
        frame = self.frame.tail(int(limit)).reset_index(drop=True).copy()
        frame.attrs["symbol"] = symbol
        frame.attrs["timeframe"] = timeframe
        return frame

    def market_context(self, symbol: str) -> dict:
        return {"data_symbol": symbol, "provider": "recorded-acceptance",
                "futures": False}


def _signature(payload: dict) -> dict:
    layers = payload["decision_service"]
    return {
        "signal_action": payload["signal"]["action"],
        "signal_confidence": payload["signal"]["confidence"],
        "plan_count": len(payload["plans"]),
        "plan_types": [plan["type"] for plan in payload["plans"]],
        "authorized_count": sum(bool(plan["primary"]) for plan in payload["plans"]),
        "watch_count": len(layers["watch_items"]),
        "active_candidate_type": (layers.get("active_candidate") or {}).get("type"),
        "desk_status": layers["desk_verdict"]["status"],
        "desk_action": layers["desk_verdict"]["action"],
        "htf_structure_count": len(payload["mtf"].get("htf_structure") or []),
        "validation_ok": payload["validation"]["ok"],
    }


@pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT", "XAUUSD"])
def test_full_desk_acceptance_snapshot(symbol, tmp_path):
    with SignalDB(tmp_path / f"{symbol}.db") as db:
        payload = analyze_full(
            symbol, "15m", 500, client=RecordedAcceptanceClient(symbol),
            with_context=False, with_memory=False, db=db,
            now_ms=1_786_420_800_000,
        )
    assert _signature(payload) == BLESSED[symbol]
