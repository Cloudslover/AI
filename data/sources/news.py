"""data/sources/news.py

Lightweight crypto-news collector with naive keyword sentiment. Uses public
RSS feeds only (no API key). Failures are swallowed — the rest of the brain
never depends on news being available.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import requests

FEEDS = [
    "https://cointelegraph.com/rss",
    "https://coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
]

BULLISH = {"surge", "rally", "bull", "gain", "soar", "breakout", "record", "etf inflow",
           "approval", "adoption", "partnership", "upgrade", "buy", "accumulation", "all-time high"}
BEARISH = {"crash", "drop", "plunge", "sell", "bear", "reject", "hack", "fraud", "ban",
           "crackdown", "lawsuit", "inflation", "recession", "outflow", "dump", "liquidation"}


def _feed_items(url: str, timeout: int = 8) -> list[dict]:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "CryptoBrain/1.0"})
        if r.status_code != 200:
            return []
        text = r.text
    except requests.RequestException:
        return []
    items = re.findall(r"<item>(.*?)</item>", text, re.S)
    out = []
    for it in items[:15]:
        title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
        pub = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
        link = re.search(r"<link>(.*?)</link>", it, re.S)
        if title:
            out.append({
                "title": title.group(1).strip()[:200],
                "link": link.group(1).strip() if link else "",
                "published": pub.group(1).strip() if pub else "",
            })
    return out


def _sentiment(text: str) -> str:
    words = set(re.findall(r"[a-z']+", text.lower()))
    bull = len(words & BULLISH)
    bear = len(words & BEARISH)
    if bull > bear and bull > 0:
        return "bullish"
    if bear > bull and bear > 0:
        return "bearish"
    return "neutral"


def fetch_news(limit: int = 20) -> dict:
    items: list[dict] = []
    for feed in FEEDS:
        items += _feed_items(feed)
    for it in items:
        it["sentiment"] = _sentiment(it["title"])
    items = items[:limit]
    tally = {"bullish": 0, "bearish": 0, "neutral": 0}
    for it in items:
        tally[it["sentiment"]] += 1
    return {
        "source": "crypto-news",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "headlines": items,
        "sentiment_tally": tally,
    }
