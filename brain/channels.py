"""brain/channels.py — Ordered-backend channel router for CryptoBrain.

Adopted pattern from Panniantong/Agent-Reach: every external dependency
the engine has (data sources + LLM) is a *channel* with an **ordered
list of backend candidates**. The first backend that is configured and
probes clean is the *active* one. Channels never block the engine —
when nothing is configured, the channel reports `active: "none"` and
the rest of the brain continues unaffected.

The design contract:

* `probe()` is **read-only** — it never mutates the system, never logs
  in anywhere, never sends a request beyond a cheap reachability check.
* `probe()` is **exception-isolated** — a broken backend in one channel
  cannot crash the doctor.
* `channels.py` is **purely additive** — it imports the existing
  ``data/sources/*`` modules unchanged and never replaces their
  interfaces. Downstream code that imports ``data.sources.news`` or
  ``data.sources.cryptodada_website`` continues to work.

This file is the foundation of P8 in ``ROADMAP_AGENT_REACH_UPGRADE.md``.
"""
from __future__ import annotations

import importlib
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ── Backwards-compatible env-var reads ────────────────────────────────────
# We import from config lazily so the module can be loaded in test
# contexts that don't have a full .env.  All accesses are wrapped in
# try/except so a missing config entry is reported as "not configured"
# rather than crashing the channel registry.

try:
    from config import (
        CRYPTODADA_MODE, CRYPTODADA_BASE_URL, CRYPTODADA_EMAIL,
        DISCORD_WEBHOOK_URL, DISCORD_TOKEN, DISCORD_CHANNEL_IDS,
        DISCORD_ANNOUNCE_WEBHOOK,
        LLM_PROVIDER, OPENAI_API_KEY, GEMINI_API_KEY, OPENAI_BASE_URL,
    )
except Exception:  # pragma: no cover - defensive
    CRYPTODADA_MODE = "auto"
    CRYPTODADA_BASE_URL = ""
    CRYPTODADA_EMAIL = ""
    DISCORD_WEBHOOK_URL = ""
    DISCORD_TOKEN = ""
    DISCORD_CHANNEL_IDS = []
    DISCORD_ANNOUNCE_WEBHOOK = ""
    LLM_PROVIDER = "off"
    OPENAI_API_KEY = ""
    GEMINI_API_KEY = ""
    OPENAI_BASE_URL = "https://api.openai.com/v1"


# ── Data classes ──────────────────────────────────────────────────────────

@dataclass
class Backend:
    """One candidate backend for a channel.

    The order of `backends` on a `Channel` IS the preference order:
    index 0 is preferred, index N-1 is the last-resort fallback.
    """
    name: str
    label: str
    configured: bool
    ok: bool = False
    detail: str = ""
    latency_ms: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "configured": self.configured,
            "ok": self.ok,
            "detail": self.detail,
            "latency_ms": round(self.latency_ms, 1),
            "error": self.error,
        }


@dataclass
class Channel:
    """A logical capability with one or more backend candidates."""
    name: str
    description: str
    backends: list[Backend] = field(default_factory=list)
    active: Optional[str] = None  # name of the first ok backend, or None
    status: str = "unknown"        # "ok" | "degraded" | "down" | "unknown"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "active": self.active,
            "status": self.status,
            "backends": [b.to_dict() for b in self.backends],
        }


# ── Per-channel probe helpers ─────────────────────────────────────────────
# Each probe is a quick, *non-mutating* check: is the module importable,
# is the credential present, does a 1-byte HEAD/PING return?  Probes
# never POST/PUT or authenticate.

def _now() -> float:
    return time.perf_counter()


def _probe_cryptodada_backends() -> list[Backend]:
    """CryptoDada backends in preference order.

    Mirrors the existing CRYPTODADA_MODE values (auto|api|browser). The
    first backend that is *configured* and *probes clean* wins.
    """
    base_ok = bool(CRYPTODADA_BASE_URL) and "YOUR-CRYPTODADA" not in CRYPTODADA_BASE_URL
    has_creds = bool(CRYPTODADA_EMAIL)

    out: list[Backend] = []

    # 1) hidden-JSON API probe (fastest, no browser)
    api = Backend(
        name="api",
        label="Hidden JSON API probe (no browser)",
        configured=base_ok,
    )
    t0 = _now()
    try:
        if base_ok:
            # Lazy import — do not require playwright unless browser backend is chosen
            from data.sources.cryptodada_website import CryptoDadaConnector
            probe = CryptoDadaConnector(mode="api", base_url=CRYPTODADA_BASE_URL)
            api.detail = f"base_url={CRYPTODADA_BASE_URL}"
            api.ok = probe.configured
            if not api.ok:
                api.detail = "base_url not set or still placeholder"
        else:
            api.detail = "CRYPTODADA_BASE_URL unset"
    except Exception as exc:  # pragma: no cover
        api.error = f"{type(exc).__name__}: {exc}"
    api.latency_ms = (_now() - t0) * 1000
    out.append(api)

    # 2) Playwright browser login (heavier, needs playwright)
    browser = Backend(
        name="browser",
        label="Playwright browser login + scrape",
        configured=base_ok and has_creds,
    )
    t0 = _now()
    try:
        if base_ok and has_creds:
            from data.sources.cryptodada_website import CryptoDadaConnector
            probe = CryptoDadaConnector(mode="browser", base_url=CRYPTODADA_BASE_URL,
                                        email=CRYPTODADA_EMAIL)
            browser.detail = f"base_url={CRYPTODADA_BASE_URL}, email set"
            browser.ok = probe.configured
        else:
            missing = []
            if not base_ok:
                missing.append("CRYPTODADA_BASE_URL")
            if not has_creds:
                missing.append("CRYPTODADA_EMAIL")
            browser.detail = f"missing: {', '.join(missing)}"
    except Exception as exc:  # pragma: no cover
        browser.error = f"{type(exc).__name__}: {exc}"
    browser.latency_ms = (_now() - t0) * 1000
    out.append(browser)

    # 3) Always-available safe fallback: empty / "no data" (does not crash)
    empty = Backend(
        name="none",
        label="No data (engine still runs; sources will return empty)",
        configured=True,
        ok=True,
        detail="Always available; returns empty list when no backends are usable.",
    )
    out.append(empty)

    return out


def _probe_discord_backends() -> list[Backend]:
    """Discord backends in preference order — most conservative first.

    Webhook (outbound only) is safest and is preferred. Bot token
    (authenticated read) is next. Self-token is the ToS-risky last
    resort and is reported but never preferred.
    """
    out: list[Backend] = []

    # 1) Outbound webhook — push signals INTO the server (always safe)
    wh = Backend(
        name="webhook",
        label="Outbound webhook (push only, ToS-safe)",
        configured=bool(DISCORD_WEBHOOK_URL) or bool(
            os.getenv("DISCORD_ANNOUNCE_WEBHOOK", "")),
        detail=("DISCORD_WEBHOOK_URL or DISCORD_ANNOUNCE_WEBHOOK set"
                if (DISCORD_WEBHOOK_URL or os.getenv("DISCORD_ANNOUNCE_WEBHOOK", ""))
                else "no webhook configured"),
    )
    wh.ok = wh.configured
    out.append(wh)

    # 2) Bot token — proper read access (recommended)
    bot = Backend(
        name="bot_token",
        label="Bot token (read channels the bot is in)",
        configured=bool(DISCORD_TOKEN) and bool(DISCORD_CHANNEL_IDS),
    )
    if bot.configured:
        bot.detail = f"token set, {len(DISCORD_CHANNEL_IDS)} channel(s)"
        bot.ok = True
    else:
        missing = []
        if not DISCORD_TOKEN:
            missing.append("DISCORD_TOKEN")
        if not DISCORD_CHANNEL_IDS:
            missing.append("DISCORD_CHANNEL_IDS")
        bot.detail = f"missing: {', '.join(missing)}"
    out.append(bot)

    # 3) Self-token — discouraged; flagged but never auto-chosen
    self_token = Backend(
        name="self_token",
        label="Self/user token (ToS-risky; flagged for review only)",
        configured=False,  # we never auto-promote this
        detail="Not auto-selected. Set DISCORD_TOKEN_AS_SELF=1 to enable deliberately.",
    )
    out.append(self_token)

    # 4) Always-available safe fallback
    empty = Backend(
        name="none",
        label="No Discord configured (sources will return empty)",
        configured=True,
        ok=True,
        detail="Always available; the engine never depends on Discord.",
    )
    out.append(empty)

    return out


def _probe_news_backends() -> list[Backend]:
    """News backends — RSS is the only source today; enumerate tiers."""
    out: list[Backend] = []

    parallel = Backend(
        name="rss_parallel",
        label="Parallel RSS (CoinTelegraph, CoinDesk, Decrypt)",
        configured=True,
        ok=True,
        detail="ThreadPoolExecutor; failures are swallowed per-feed.",
    )
    out.append(parallel)

    sequential = Backend(
        name="rss_sequential",
        label="Sequential RSS fallback",
        configured=True,
        ok=True,
        detail="Same feeds, no threading — slower but more debuggable.",
    )
    out.append(sequential)

    empty = Backend(
        name="none",
        label="No RSS (engine still runs; news panel will be empty)",
        configured=True,
        ok=True,
        detail="Always available.",
    )
    out.append(empty)

    return out


def _probe_llm_backends() -> list[Backend]:
    """LLM backends in preference order — first configured + ok wins."""
    out: list[Backend] = []

    groq = Backend(
        name="groq",
        label="Groq (OpenAI-compatible)",
        configured=bool(OPENAI_API_KEY) and "groq" in (OPENAI_BASE_URL or "").lower(),
    )
    if groq.configured:
        groq.ok = True
        groq.detail = f"OPENAI_BASE_URL={OPENAI_BASE_URL}"
    else:
        groq.detail = "needs OPENAI_API_KEY + OPENAI_BASE_URL pointing to api.groq.com"
    out.append(groq)

    openai = Backend(
        name="openai",
        label="OpenAI (or any OpenAI-compatible endpoint)",
        configured=bool(OPENAI_API_KEY) and "groq" not in (OPENAI_BASE_URL or "").lower(),
    )
    if openai.configured:
        openai.ok = True
        openai.detail = f"OPENAI_BASE_URL={OPENAI_BASE_URL}, model={os.getenv('OPENAI_MODEL','')}"
    else:
        openai.detail = "needs OPENAI_API_KEY + OPENAI_BASE_URL (non-groq)"
    out.append(openai)

    gemini = Backend(
        name="gemini",
        label="Google Gemini",
        configured=bool(GEMINI_API_KEY),
    )
    if gemini.configured:
        gemini.ok = True
        gemini.detail = f"GEMINI_MODEL={os.getenv('GEMINI_MODEL','')}"
    else:
        gemini.detail = "needs GEMINI_API_KEY"
    out.append(gemini)

    rule_based = Backend(
        name="rule_based",
        label="Rule-based narrative (no API key required)",
        configured=True,
        ok=True,
        detail="Always available; produces a templated brief from existing engine output.",
    )
    out.append(rule_based)

    return out


# ── Channel registry ──────────────────────────────────────────────────────

CHANNELS: dict[str, Channel] = {
    "cryptodada": Channel(
        name="cryptodada",
        description="Private CryptoDada membership website (volume spikes, analyst notes, historical signals)",
        backends=_probe_cryptodada_backends(),
    ),
    "discord": Channel(
        name="discord",
        description="Private Discord group (market updates, chat, polls)",
        backends=_probe_discord_backends(),
    ),
    "news": Channel(
        name="news",
        description="Crypto news RSS feeds (CoinTelegraph, CoinDesk, Decrypt) + naive sentiment",
        backends=_probe_news_backends(),
    ),
    "llm": Channel(
        name="llm",
        description="LLM narrative brain (Groq / OpenAI / Gemini / rule-based)",
        backends=_probe_llm_backends(),
    ),
}


def _finalize(ch: Channel) -> None:
    """Pick the active backend and assign a status.

    The first backend that is both `configured` and `ok` wins. If none
    is, the last 'none'-style backend (always `ok=True`) wins so the
    channel is never "down" in a way that blocks the engine.
    """
    ch.active = None
    for b in ch.backends:
        if b.configured and b.ok:
            ch.active = b.name
            break
    if ch.active is None and ch.backends:
        # last-resort: any ok=True backend
        for b in reversed(ch.backends):
            if b.ok:
                ch.active = b.name
                break
    if ch.active is None:
        ch.status = "down"
    elif ch.active == "none":
        ch.status = "degraded"
    else:
        ch.status = "ok"


def probe_all() -> dict[str, Channel]:
    """Re-probe every channel and return the registry.

    Cheap (each probe touches no network beyond a config read). Safe to
    call from the doctor / health / dashboard at any frequency.

    Exceptions in any single probe are isolated: that channel is marked
    status='down' and the rest of the report still renders. This
    matches Agent-Reach's "doctor survives per-channel exceptions"
    behaviour.
    """
    for name, probe in (
        ("cryptodada", _probe_cryptodada_backends),
        ("discord", _probe_discord_backends),
        ("news", _probe_news_backends),
        ("llm", _probe_llm_backends),
    ):
        ch = CHANNELS[name]
        try:
            ch.backends = probe()
        except Exception as exc:
            ch.backends = [
                Backend(
                    name="error",
                    label=f"probe crashed: {type(exc).__name__}",
                    configured=False,
                    ok=False,
                    detail="",
                    error=f"{type(exc).__name__}: {exc}",
                ),
                Backend(
                    name="none",
                    label="No data (probe crashed; engine still runs)",
                    configured=True,
                    ok=True,
                    detail="Always available fallback so the engine never blocks.",
                ),
            ]
        _finalize(ch)
    return CHANNELS


def doctor_report(as_json: bool = False) -> Any:
    """Return a human-readable (default) or JSON doctor report.

    The report covers every channel, the active backend, every backend's
    configured/ok status, and a one-line prescription per disabled
    channel. Exceptions in any single probe are isolated; the rest of
    the report still renders.
    """
    try:
        channels = probe_all()
    except Exception as exc:  # pragma: no cover - defensive
        return {"error": f"channels.probe_all() crashed: {type(exc).__name__}: {exc}"}

    if as_json:
        return {
            "channels": {name: ch.to_dict() for name, ch in channels.items()},
        }

    lines: list[str] = []
    lines.append("CryptoBrain doctor report")
    lines.append("=" * 60)
    for name, ch in channels.items():
        lines.append("")
        lines.append(f"[{ch.status.upper():>8}] {name}  —  {ch.description}")
        for b in ch.backends:
            mark = "✓" if (b.configured and b.ok) else ("·" if b.configured else "✗")
            active = "  (active)" if b.name == ch.active else ""
            detail = b.error or b.detail
            lines.append(f"  {mark} {b.name:<14} {b.label}{active}")
            if detail:
                lines.append(f"      {detail}")
        if ch.status == "ok":
            lines.append(f"      → serving via: {ch.active}")
        elif ch.status == "degraded":
            lines.append("      → no backend configured; channel returns empty results safely")
        else:
            lines.append("      → all backends failed; engine continues with empty data")
    return "\n".join(lines)


def list_channels(as_json: bool = False) -> Any:
    """List the channel registry in a compact form for `python main.py channels`."""
    try:
        channels = probe_all()
    except Exception as exc:  # pragma: no cover
        return {"error": f"channels.probe_all() crashed: {type(exc).__name__}: {exc}"}

    if as_json:
        return {
            "channels": {name: ch.to_dict() for name, ch in channels.items()},
        }

    lines: list[str] = []
    lines.append(f"{'channel':<12} {'status':<10} {'active':<14} {'backends'}")
    lines.append("-" * 60)
    for name, ch in channels.items():
        n_ok = sum(1 for b in ch.backends if b.configured and b.ok)
        n_tot = len(ch.backends)
        lines.append(
            f"{name:<12} {ch.status:<10} {str(ch.active or '-'):<14} {n_ok}/{n_tot} ok"
        )
    return "\n".join(lines)
