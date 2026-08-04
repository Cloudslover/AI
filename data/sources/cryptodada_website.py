"""data/sources/cryptodada_website.py

Connector for the private CryptoDada membership website (your screenshots 1-5).

The site exposes (per your screenshots):
  - Volume Spike Screener   (coins, volume change %, prev volume, 24h H/L, trend)
  - Market Radar            (trending / momentum / strength)
  - Syndicate Analyst       (manual analyst notes: funding, support/resistance,
                             15m / 1h change)
  - Historical Signals      (past signals you can score for win-rate learning)
  - Dashboard               (totals, historical tracking)

Three operating modes (CRYPTODADA_MODE):
  api     — probe hidden JSON endpoints the dashboard's frontend calls
            (fastest; discover them with DevTools → Network tab).
  browser — Playwright login + scrape the rendered pages. Requires:
                pip install playwright && playwright install chromium
  auto    — try api first, fall back to browser if api yields nothing.

IMPORTANT: credentials live in .env, never commit them. Logging into a
service with an account you hold a membership for is fine; be respectful of
their ToS and rate limits.
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional

import requests

from config import CRYPTODADA_BASE_URL, CRYPTODADA_MODE, CRYPTODADA_EMAIL, CRYPTODADA_PASSWORD

# Hidden-API endpoints commonly found on such dashboards — probe these first.
LIKELY_ENDPOINTS = [
    "/api/signals", "/api/signals/latest", "/api/volume-spikes", "/api/volume",
    "/api/market-radar", "/api/radar", "/api/analyst", "/api/screener",
    "/api/dashboard", "/api/stats",
]


class CryptoDadaConnector:
    def __init__(self, base_url: str = CRYPTODADA_BASE_URL,
                 email: str = CRYPTODADA_EMAIL, password: str = CRYPTODADA_PASSWORD,
                 mode: str = CRYPTODADA_MODE):
        self.base_url = base_url
        self.email = email
        self.password = password
        self.mode = mode
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) CryptoBrain/1.0"})
        self._auth_cookies: dict = {}

    @property
    def configured(self) -> bool:
        return bool(self.base_url and "YOUR-CRYPTODADA-SITE" not in self.base_url)

    # ── auth ─────────────────────────────────────────────────────────────
    def _login_api(self) -> bool:
        """Try common login endpoints (JSON). Returns True on success."""
        for path in ("/api/login", "/api/auth/login", "/auth/login", "/api/user/login"):
            try:
                r = self.session.post(
                    f"{self.base_url}{path}",
                    json={"email": self.email, "password": self.password},
                    timeout=10)
                if r.status_code in (200, 201):
                    self._auth_cookies = dict(self.session.cookies)
                    return True
            except requests.RequestException:
                continue
        return False

    # ── api mode ─────────────────────────────────────────────────────────
    def fetch_via_api(self) -> dict:
        """Probe likely hidden endpoints and merge whatever returns JSON."""
        out: dict = {}
        for path in LIKELY_ENDPOINTS:
            try:
                r = self.session.get(f"{self.base_url}{path}", timeout=8)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                    try:
                        payload = r.json()
                    except ValueError:
                        continue
                    key = path.strip("/").replace("/", "_")
                    out[key] = payload if not isinstance(payload, list) else payload[:50]
            except requests.RequestException:
                continue
        return out

    # ── browser mode (Playwright, optional) ──────────────────────────────
    def fetch_via_browser(self) -> dict:
        """Login + scrape rendered pages with Playwright. Requires the optional
        `playwright` dependency; degrades with a clear message if missing."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"error": "Playwright not installed. Run: pip install playwright && playwright install chromium"}

        pages = {
            "volume_screener": "/",
            "market_radar": "/radar",
            "analyst": "/analyst",
            "signals": "/signals",
        }
        out: dict = {}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.base_url, timeout=30000, wait_until="networkidle")
            # attempt login if a form is present
            if self.email and self.password:
                for sel in ('input[type="email"]', 'input[name="email"]', 'input[name="username"]'):
                    try:
                        page.fill(sel, self.email)
                        break
                    except Exception:
                        continue
                try:
                    page.fill('input[type="password"]', self.password)
                    page.click('button[type="submit"], button:has-text("Login"), button:has-text("Sign in")')
                    page.wait_for_timeout(4000)
                except Exception:
                    pass
            for name, path in pages.items():
                try:
                    page.goto(f"{self.base_url}{path}", timeout=20000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)
                    rows = page.query_selector_all("table tbody tr, [class*=card], [class*=row]")
                    out[name] = [row.inner_text()[:500] for row in rows[:60]]
                except Exception as exc:
                    out[name] = {"error": str(exc)}
            browser.close()
        return out

    # ── unified ──────────────────────────────────────────────────────────
    def fetch(self) -> dict:
        if not self.configured:
            return {"configured": False,
                    "message": "Set CRYPTODADA_BASE_URL/EMAIL/PASSWORD in .env to enable.",
                    "data": {}}
        if self.email and self.password:
            self._login_api()
        if self.mode in ("api", "auto"):
            data = self.fetch_via_api()
            if data or self.mode == "api":
                return {"configured": True, "mode": "api", "data": data}
        if self.mode in ("browser", "auto"):
            return {"configured": True, "mode": "browser", "data": self.fetch_via_browser()}
        return {"configured": True, "mode": self.mode, "data": {}}


def parse_screener_text(rows: list[str]) -> list[dict]:
    """Best-effort parser for the volume-spike screener table rows → structured
    rows the scoring engine can consume (coin, vol_change_pct, 24h high/low,
    trend, price)."""
    parsed = []
    for row in rows:
        if not row or len(row) < 5:
            continue
        tokens = [t.strip() for t in row.split("\t") if t.strip()] or [t.strip() for t in row.split() if t.strip()]
        if len(tokens) < 3:
            continue
        rec: dict = {"raw": row[:300]}
        rec["coin"] = tokens[0].upper()
        rec["trend"] = "up" if any(w in row.lower() for w in ("green", "bull", "up")) else \
                       "down" if any(w in row.lower() for w in ("red", "bear", "down")) else "flat"
        m = re.findall(r"[-+]?\d+(?:\.\d+)?x?", row.lower())
        if m:
            rec["volume_change"] = m[0]
        for i, tok in enumerate(tokens):
            if tok.replace(",", "").replace(".", "").isdigit() and 0.1 < float(tok) < 1_000_000:
                rec.setdefault("price", float(tok))
        parsed.append(rec)
    return parsed


def summarize_cryptodada(raw: dict) -> dict:
    """Flatten a CryptoDada fetch into a compact, serialisable summary."""
    data = raw.get("data", {})
    summary = {"source": "cryptodada", "configured": raw.get("configured", False),
               "mode": raw.get("mode", ""), "tables": {}}
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, list):
                summary["tables"][key] = parse_screener_text([str(v)[:500] for v in val])[:30]
            else:
                summary["tables"][key] = val
    else:
        summary["tables"]["raw"] = str(data)[:2000]
    return summary
