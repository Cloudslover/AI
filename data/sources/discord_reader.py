"""data/sources/discord_reader.py

Connector for the private Discord group (your screenshots 6-8).

What we extract from Discord:
  - Market Update messages   -> structured bias notes (bullish/bearish + levels)
  - Crypto news / headlines  -> sentiment tags for the news panel
  - Analyst signal posts     -> parsed as candidate signals (cross-checked
                                against the engine's own scores)
  - Chat sentiment           -> simple keyword ratio (crowd positioning)

Two ingestion paths:
  1. DISCORD_TOKEN (bot or self-token)  — read channel messages.
     NOTE: automating a *user account* may violate Discord ToS; use a bot
     account your server admin adds, or review the ToS yourself.
  2. DISCORD_WEBHOOK_URL                — outbound only: push CryptoBrain
     signals INTO your server (alerts). Safe and recommended.
"""
from __future__ import annotations

import json
import re
from typing import Optional

import requests

from config import DISCORD_TOKEN, DISCORD_CHANNEL_IDS, DISCORD_WEBHOOK_URL, DISCORD_ANNOUNCE_WEBHOOK

API = "https://discord.com/api/v10"


class DiscordReader:
    def __init__(self, token: str = DISCORD_TOKEN, channel_ids: list[str] | None = None):
        self.token = token
        self.channel_ids = channel_ids or DISCORD_CHANNEL_IDS
        self.session = requests.Session()
        if token:
            self.session.headers.update({"Authorization": token, "User-Agent": "CryptoBrain/1.0"})

    @property
    def can_read(self) -> bool:
        return bool(self.token and self.channel_ids)

    def read_channel(self, channel_id: str, limit: int = 100) -> list[dict]:
        """Fetch recent messages from a channel as structured records."""
        if not self.token:
            return [{"error": "DISCORD_TOKEN not configured"}]
        r = self.session.get(f"{API}/channels/{channel_id}/messages", params={"limit": limit}, timeout=10)
        if r.status_code != 200:
            return [{"error": f"HTTP {r.status_code}: {r.text[:200]}"}]
        out = []
        for m in r.json():
            out.append({
                "id": m.get("id"),
                "ts": m.get("timestamp"),
                "author": (m.get("author") or {}).get("username"),
                "content": (m.get("content") or "")[:2000],
                "attachments": [a.get("url") for a in m.get("attachments", [])],
            })
        return out

    def read_all(self, limit: int = 100) -> dict:
        return {cid: self.read_channel(cid, limit) for cid in self.channel_ids}

    def push_signal(self, text: str, webhook: str | None = None) -> bool:
        """Send a formatted signal message into a channel via webhook."""
        url = webhook or DISCORD_ANNOUNCE_WEBHOOK
        if not url:
            return False
        r = requests.post(url, json={"content": text}, timeout=10)
        return r.status_code in (200, 204)


def parse_market_update(content: str) -> dict:
    """Heuristic parser for analyst 'Market Update' posts → structured note."""
    lower = content.lower()
    bias = None
    if any(w in lower for w in ("bearish", "short", "sell", "rejected", "distribution")):
        bias = "bearish"
    elif any(w in lower for w in ("bullish", "long", "buy", "accumulation", "rally")):
        bias = "bullish"
    levels = [float(x) for x in re.findall(r"[$]?\s?(\d{3,6}(?:[.,]\d{1,2})?)", content) if float(x) > 100]
    return {
        "bias": bias,
        "levels": sorted(levels)[:8],
        "mentions": {
            "support": [l for l in levels if l <= (levels[0] if levels else 0)][:3],
            "resistance": sorted(levels, reverse=True)[:3],
        } if levels else {},
        "raw": content[:800],
    }


def summarize_discord(messages_by_channel: dict) -> dict:
    notes = []
    sentiment_hits = {"bullish": 0, "bearish": 0, "neutral": 0}
    for cid, msgs in (messages_by_channel or {}).items():
        for m in msgs if isinstance(msgs, list) else []:
            content = m.get("content", "")
            if not content or "error" in content.lower():
                continue
            note = parse_market_update(content)
            if note["bias"]:
                sentiment_hits[note["bias"]] += 1
            notes.append({**note, "channel": cid, "author": m.get("author")})
    return {
        "source": "discord",
        "messages_scanned": sum(len(v) for v in (messages_by_channel or {}).values() if isinstance(v, list)),
        "sentiment": sentiment_hits,
        "analyst_notes": notes[:40],
    }
