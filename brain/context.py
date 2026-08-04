"""brain/context.py — the "what affects BTC" layer.

A human trader does not look at a chart in a vacuum. They watch:
  news & events, macro calendar (FOMC/CPI/NFP), geopolitics,
  the crypto cycle (halving phase), influencer/social sentiment,
  equities & the dollar (risk-on/off), fear & greed, BTC dominance,
  and on-chain-ish proxies.

This module collects all of that into one serialisable "context" dict.
Every source is best-effort and independently guarded: if a public API is
unreachable (or geo-blocked) the field reports `available: false` and the
rest of the brain keeps working. Results are cached for a few minutes so the
30s dashboard refresh never hammers external APIs.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from data.sources.news import fetch_news

_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 300  # seconds

# ── Macro calendar (curated recurring events; best-effort) ──────────────
# 2026 FOMC meeting dates (per the Fed's published schedule).
FOMC_2026 = [
    datetime(2026, 1, 28), datetime(2026, 3, 18), datetime(2026, 4, 29),
    datetime(2026, 6, 17), datetime(2026, 7, 29), datetime(2026, 9, 16),
    datetime(2026, 10, 28), datetime(2026, 12, 9),
]
HALVINGS = [
    datetime(2012, 11, 28), datetime(2016, 7, 9), datetime(2020, 5, 11),
    datetime(2024, 4, 20), datetime(2028, 4, 20),  # ~4y cadence
]
GEOPOLITICAL_KEYWORDS = [
    "war", "invasion", "sanction", "conflict", "missile", "nuclear",
    "ceasefire", "military", "geopolitic", "china", "russia", "ukraine",
    "israel", "iran", "oil price", "opec", "tariff", "trade war", "crisis",
]
INFLUENCER_KEYWORDS = [
    "elon", "musk", "trump", "sec", "etf", "blackrock", "fidelity",
    "cathie wood", "saylor", "microstrategy", "cz", "binance", "coinbase",
]


def _cached(name: str, fn, ttl: int = CACHE_TTL):
    now = time.time()
    hit = _CACHE.get(name)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception:
        val = {"available": False}
    _CACHE[name] = (now, val)
    return val


# ── Fear & Greed ─────────────────────────────────────────────────────────
def fear_greed() -> dict:
    def _f():
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8)
        d = r.json()["data"][0]
        return {"available": True, "value": int(d["value"]),
                "label": d["value_classification"]}
    return _cached("fng", _f)


# ── BTC dominance / total market cap (CoinGecko global) ──────────────────
def dominance() -> dict:
    def _d():
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=8,
                         headers={"User-Agent": "CryptoBrain/1.0"})
        g = r.json()["data"]
        return {
            "available": True,
            "btc_dominance": round(g["market_cap_percentage"]["btc"], 2),
            "eth_dominance": round(g["market_cap_percentage"]["eth"], 2),
            "total_market_cap_usd": g["total_market_cap"]["usd"],
            "market_cap_change_24h_pct": round(g["market_cap_change_percentage_24h_usd"], 2),
        }
    return _cached("dominance", _d)


# ── Equities & dollar (stooq CSV — usually open, no key) ─────────────────
def equities() -> dict:
    def _e():
        url = "https://stooq.com/q/l/?s=^spx,^ndq,dx.f,xauusd&f=sd2t2ohlcv&h&e=csv"
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        rows = {}
        for line in r.text.strip().splitlines()[1:]:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            sym = parts[0]
            try:
                close = float(parts[5])
                prev = float(parts[6])
                rows[sym] = round((close / prev - 1) * 100, 2)
            except (ValueError, IndexError):
                continue
        if not rows:
            return {"available": False}
        return {"available": True, "change_pct": rows}
    return _cached("equities", _e, ttl=600)


# ── Macro events ─────────────────────────────────────────────────────────
def macro_events() -> dict:
    def _m():
        today = datetime.now(timezone.utc).date()
        events = []
        for d in FOMC_2026:
            days = (d.date() - today).days
            if -2 <= days <= 60:
                events.append({"name": "FOMC meeting", "date": d.strftime("%Y-%m-%d"),
                               "days_until": max(days, 0), "high_impact": True})
        # NFP: first Friday of each month (heuristic)
        y, mo = today.year, today.month
        for offset in range(0, 3):
            m = mo + offset
            yy = y + (m - 1) // 12
            mm = (m - 1) % 12 + 1
            first = datetime(yy, mm, 1)
            shift = (4 - first.weekday()) % 7  # first Friday
            nfp = first + timedelta(days=shift)
            days = (nfp.date() - today).days
            if 0 <= days <= 45:
                events.append({"name": "US Non-Farm Payrolls", "date": nfp.strftime("%Y-%m-%d"),
                               "days_until": days, "high_impact": True})
        # CPI: ~mid-month heuristic (2nd Tuesday-ish)
        for offset in range(0, 3):
            m = mo + offset
            yy = y + (m - 1) // 12
            mm = (m - 1) % 12 + 1
            cpi = datetime(yy, mm, 13)
            days = (cpi.date() - today).days
            if 0 <= days <= 45:
                events.append({"name": "US CPI", "date": cpi.strftime("%Y-%m-%d"),
                               "days_until": days, "high_impact": True})
        events.sort(key=lambda e: e["days_until"])
        imminent = [e for e in events if e["days_until"] <= 2]
        return {"available": True, "events": events[:6],
                "high_impact_imminent": bool(imminent),
                "imminent": imminent}
    return _cached("macro", _m, ttl=3600)


# ── Cycle (halving phase + long-term position) ───────────────────────────
def cycle(sma200_1d: Optional[float] = None, price_1d: Optional[float] = None) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # latest past halving
    past = [h for h in HALVINGS if h <= now]
    last_h = max(past) if past else HALVINGS[0]
    days_since = (now - last_h).days
    cycle_len_days = 365 * 4
    pct = days_since / cycle_len_days
    if pct < 0.15:
        phase = "early-post-halving"
    elif pct < 0.45:
        phase = "expansion"
    elif pct < 0.75:
        phase = "late-cycle"
    else:
        phase = "pre-halving"
    # long-term position proxy
    position = None
    if sma200_1d and price_1d:
        ratio = price_1d / sma200_1d if sma200_1d else None
        position = "above-200d" if ratio and ratio > 1.05 else \
                   "below-200d" if ratio and ratio < 0.95 else "around-200d"
    return {
        "available": True,
        "days_since_halving": days_since,
        "phase": phase,
        "next_halving": max(HALVINGS).strftime("%Y-%m-%d"),
        "position_vs_200d": position,
        "note": ("Halving cycles historically mark multi-year expansion after the event; "
                 "the phase is a macro filter, not a timing signal."),
    }


# ── Social / influencer pulse (best-effort keyword scan over headlines) ──
def social_pulse(headlines: list[dict]) -> dict:
    hits = []
    for h in headlines:
        text = (h.get("title", "") + " " + h.get("summary", "")).lower()
        for kw in INFLUENCER_KEYWORDS:
            if kw in text:
                hits.append({"keyword": kw, "title": h.get("title", "")[:120]})
                break
    return {"available": True, "influencer_mentions": hits[:8],
            "count": len(hits)}


# ── Geopolitics (keyword scan over headlines) ────────────────────────────
def geopolitics(headlines: list[dict]) -> dict:
    hits = []
    for h in headlines:
        text = (h.get("title", "") + " " + h.get("summary", "")).lower()
        for kw in GEOPOLITICAL_KEYWORDS:
            if kw in text:
                hits.append({"keyword": kw, "title": h.get("title", "")[:120]})
                break
    return {"available": True, "hits": hits[:8], "count": len(hits),
            "elevated": len(hits) >= 2}


# ── Risk regime: equities + dollar + fear&greed + dominance ──────────────
def risk_regime(eq: dict, fng: dict, dom: dict) -> dict:
    spx = eq.get("change_pct", {}).get("^spx")
    ndq = eq.get("change_pct", {}).get("^ndq")
    dxy = eq.get("change_pct", {}).get("dx.f")
    score = 0
    parts = []
    if spx is not None:
        score += 1 if spx >= 0 else -1
        parts.append(f"S&P500 {spx:+.2f}%")
    if ndq is not None:
        score += 1 if ndq >= 0 else -1
        parts.append(f"Nasdaq {ndq:+.2f}%")
    if dxy is not None:
        score += -1 if dxy >= 0 else 1  # strong dollar is headwind for BTC
        parts.append(f"DXY {dxy:+.2f}%")
    if fng.get("available"):
        v = fng["value"]
        score += 1 if v >= 60 else -1 if v <= 40 else 0
        parts.append(f"Fear&Greed {v} ({fng['label']})")
    if dom.get("available"):
        d = dom["btc_dominance"]
        parts.append(f"BTC dom {d}%")
        score += 1 if d <= 55 else 0  # rising alt appetite when dom lower
    regime = "risk_on" if score >= 2 else "risk_off" if score <= -2 else "neutral"
    return {"regime": regime, "score": score, "parts": parts}


def collect(price_1d: Optional[float] = None, sma200_1d: Optional[float] = None) -> dict:
    """Gather the full market context (cached, best-effort)."""
    fng = fear_greed()
    dom = dominance()
    eq = equities()
    macro = macro_events()
    cyc = cycle(sma200_1d, price_1d)
    headlines = fetch_news(limit=15).get("headlines", [])
    social = social_pulse(headlines)
    geo = geopolitics(headlines)
    regime = risk_regime(eq, fng, dom)
    return {
        "fear_greed": fng,
        "dominance": dom,
        "equities": eq,
        "macro": macro,
        "cycle": cyc,
        "news": {"headlines": headlines[:8], "count": len(headlines)},
        "social": social,
        "geopolitics": geo,
        "risk_regime": regime,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
