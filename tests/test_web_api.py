"""Web API regression tests — the Flask endpoints against in-process requests.

These exist because `/api/scan` once returned 500 ("Object of type bool is not
JSON serializable") when numpy scalars from the quant layer leaked into the
payload: Flask's jsonify is strict, unlike json.dumps(default=str).  Every
heavy engine endpoint is exercised here so a numpy leak can never ship again.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "web.db"))
    from web.app import make_app
    app = make_app()
    app.testing = True
    return app.test_client()


def test_scan_endpoint_is_json_serializable(client):
    resp = client.get("/api/scan?symbol=BTCUSDT&tf=15m")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    payload = resp.get_json()
    assert payload["signal"]["asset"] == "BTCUSDT"
    assert payload["decision"]["action"] in ("BUY", "SELL", "NO TRADE")
    assert "lifecycle" in payload


def test_intelligence_endpoint(client):
    resp = client.get("/api/intelligence?symbol=BTCUSDT&tf=15m")
    assert resp.status_code == 200
    intel = resp.get_json()
    assert intel["asset"] == "BTCUSDT"
    assert intel["signal"] in ("BUY", "SELL", "NO TRADE")


def test_health_risk_agents_endpoints(client):
    health = client.get("/api/health").get_json()
    assert health["ok"] is True
    assert health["data"]["mode"] == "demo"

    risk = client.get("/api/risk").get_json()
    assert "gate" in risk and "allowed" in risk["gate"]

    agents = client.get("/api/agents").get_json()
    assert len(agents["assets"]) == 3

    mcp = client.get("/api/mcp").get_json()
    assert "tools" in mcp


def test_ask_endpoint(client):
    resp = client.post("/api/ask", json={"question": "what's pending review?"})
    assert resp.status_code == 200
    assert resp.get_json()["intent"] == "pending"
    resp = client.post("/api/ask", json={})
    assert resp.status_code == 400


def test_pending_paper_learning_endpoints(client):
    assert client.get("/api/pending").status_code == 200
    assert client.get("/api/paper").status_code == 200
    learning = client.get("/api/learning").get_json()
    assert "backtest" in learning or "calibration" in learning
    hist = client.get("/api/history").get_json()
    assert "history" in hist and isinstance(hist["history"], list)


def test_sanitize_for_json_helper():
    import numpy as np
    from web.app import _sanitize_for_json
    out = _sanitize_for_json({
        "b": np.bool_(True), "i": np.int64(3), "f": np.float64(1.5),
        "arr": np.array([1, 2]), "nested": [{"x": np.bool_(False)}],
    })
    import json
    json.dumps(out)  # must not raise
    assert out == {"b": True, "i": 3, "f": 1.5, "arr": [1, 2],
                   "nested": [{"x": False}]}


# ── /api/channels + /api/doctor — P8 dashboard surface ────────────────
# The Channels layer is the Panniantong/Agent-Reach ordered-backend
# pattern (P8). It must reach the dashboard without numpy-leak 500s and
# without any single probe being able to crash the endpoint.

def test_channels_endpoint_returns_registry(client):
    """`/api/channels` must return the four channels with status+active+backends."""
    resp = client.get("/api/channels")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    payload = resp.get_json()
    assert "channels" in payload
    assert set(payload["channels"].keys()) == {"cryptodada", "discord", "news", "llm"}
    for name, ch in payload["channels"].items():
        # Schema contract: every channel has these three keys
        assert "active" in ch, f"{name} missing 'active'"
        assert "status" in ch, f"{name} missing 'status'"
        assert "backends" in ch, f"{name} missing 'backends'"
        assert ch["status"] in {"ok", "degraded", "down", "unknown"}
        # Every channel has at least one backend
        assert len(ch["backends"]) >= 1
        # Every backend has the required shape
        for b in ch["backends"]:
            assert {"name", "label", "configured", "ok"} <= set(b.keys())


def test_channels_endpoint_is_json_serializable_under_numpy_leak(client):
    """If a probe accidentally returns a numpy scalar, the endpoint
    must still return valid JSON — the same _sanitize_for_json
    regression that bit /api/scan and /api/intelligence per
    MERGE_NOTES.md must not bite /api/channels."""
    import json
    resp = client.get("/api/channels")
    assert resp.status_code == 200
    # If we got this far, Flask jsonify already serialized cleanly.
    # Do one more round-trip through the stdlib json to be paranoid.
    body = resp.get_data(as_text=True)
    json.loads(body)  # must not raise


def test_channels_endpoint_isolates_probe_exceptions(client, monkeypatch):
    """A broken channel probe must NOT crash the endpoint — the same
    exception-isolation contract as `brain.channels.probe_all`."""
    from brain import channels

    def boom():
        raise RuntimeError("simulated probe failure")

    monkeypatch.setattr(channels, "_probe_cryptodada_backends", boom)
    resp = client.get("/api/channels")
    assert resp.status_code == 200
    payload = resp.get_json()
    # cryptodada should be in 'down' state, not crash the response
    assert "channels" in payload
    assert "cryptodada" in payload["channels"]


def test_doctor_endpoint_returns_text_report(client):
    """`/api/doctor` is the JSON-wrapped text version (same as CLI)."""
    resp = client.get("/api/doctor")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert "report" in payload
    assert "CryptoBrain doctor report" in payload["report"]
    for ch in ("cryptodada", "discord", "news", "llm"):
        assert ch in payload["report"]
