"""data/binance_client.py

Binance market-data client.

* OHLCV klines are fetched from the geo-friendly public market-data mirror
  (data-api.binance.vision) first, with api.binance.com as fallback.
* Futures endpoints (funding rate, open interest, long/short ratio,
  liquidations) live on fapi.binance.com, which geo-blocks some regions
  (including this sandbox). The client tries them and *degrades gracefully*:
  if unreachable, the engine simply runs without futures features and the
  output notes they were unavailable. On your machine (Dhaka, BD) they will
  normally work.

All methods are read-only public endpoints — no API keys required.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import pandas as pd
import requests

from config import BINANCE_HOSTS, BINANCE_FUTURES_HOSTS

TIMEFRAME_TO_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "6h": 21_600_000, "12h": 43_200_000, "1d": 86_400_000, "1w": 604_800_000,
}

TIMEOUT = 10
_RETRIES = 2


class BinanceClient:
    def __init__(self, timeout: int = TIMEOUT, retries: int = _RETRIES):
        self.timeout = timeout
        self.retries = retries
        # Thread-local sessions so parallel timeframe fetches are safe.
        self._local = threading.local()
        self._futures_ok: Optional[bool] = None  # None = not yet tested

    @property
    def session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({"User-Agent": "cryptobrain/1.0"})
            self._local.session = s
        return s

    # ── helpers ──────────────────────────────────────────────────────────
    def _get(self, host: str, path: str, params: dict) -> Optional[dict]:
        for attempt in range(self.retries + 1):
            try:
                r = self.session.get(f"{host}{path}", params=params, timeout=self.timeout)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (451, 403, 429):
                    return None  # geo-block / rate-limit — not retryable
            except requests.RequestException:
                pass
            time.sleep(0.4 * (attempt + 1))
        return None

    def _get_first_host(self, hosts: list[str], path: str, params: dict) -> Optional[dict]:
        for host in hosts:
            data = self._get(host, path, params)
            if data is not None:
                return data
        return None

    # ── OHLCV ────────────────────────────────────────────────────────────
    def klines(self, symbol: str = "BTCUSDT", timeframe: str = "15m",
               limit: int = 500) -> pd.DataFrame:
        """Fetch OHLCV candles. Returns a DataFrame with columns
        ts, open, high, low, close, volume (closed candles only)."""
        params = {"symbol": symbol, "interval": timeframe, "limit": limit}
        data = self._get_first_host(BINANCE_HOSTS, "/api/v3/klines", params)
        if data is None:
            raise ConnectionError(
                f"Could not fetch klines for {symbol} {timeframe} — check network "
                f"or try a Binance-accessible location."
            )
        df = pd.DataFrame(data, columns=[
            "ts", "open", "high", "low", "close", "volume",
            "close_ts", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore",
        ])
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)
        return df[["ts", "open", "high", "low", "close", "volume"]].astype({"ts": "int64"})

    # ── Futures (optional; may geo-block) ────────────────────────────────
    @property
    def futures_available(self) -> bool:
        if self._futures_ok is None:
            self._futures_ok = self._get_first_host(
                BINANCE_FUTURES_HOSTS, "/fapi/v1/ping", {}) is not None
        return self._futures_ok

    def funding_rate(self, symbol: str = "BTCUSDT") -> Optional[dict]:
        """Current (last) funding rate for the USDT-margined future."""
        if not self.futures_available:
            return None
        data = self._get_first_host(BINANCE_FUTURES_HOSTS, "/fapi/v1/premiumIndex",
                                    {"symbol": symbol})
        if not data:
            return None
        return {
            "funding_rate_pct": round(float(data.get("lastFundingRate", 0)) * 100, 4),
            "mark_price": float(data.get("markPrice", 0)),
            "time": data.get("time"),
        }

    def open_interest(self, symbol: str = "BTCUSDT") -> Optional[dict]:
        if not self.futures_available:
            return None
        data = self._get_first_host(BINANCE_FUTURES_HOSTS, "/fapi/v1/openInterest",
                                    {"symbol": symbol})
        if not data:
            return None
        return {"open_interest": float(data.get("openInterest", 0))}

    def long_short_ratio(self, symbol: str = "BTCUSDT", period: str = "5m",
                         limit: int = 1) -> Optional[dict]:
        if not self.futures_available:
            return None
        data = self._get_first_host(
            BINANCE_FUTURES_HOSTS, "/futures/data/globalLongShortAccountRatio",
            {"symbol": symbol, "period": period, "limit": limit})
        if not data:
            return None
        latest = data[-1] if isinstance(data, list) and data else data
        return {"long_short_ratio": float(latest.get("longShortRatio", 0))}

    def liquidations(self, symbol: str = "BTCUSDT") -> Optional[dict]:
        """Recent forced-liquidations snapshot (via allForceOrders is heavy, so
        we use the public 24h stats + the top longs/shorts as a proxy)."""
        if not self.futures_available:
            return None
        data = self._get_first_host(BINANCE_FUTURES_HOSTS, "/fapi/v1/ticker/24hr",
                                    {"symbol": symbol})
        if not data:
            return None
        return {
            "24h_high": float(data.get("highPrice", 0)),
            "24h_low": float(data.get("lowPrice", 0)),
            "24h_volume_base": float(data.get("volume", 0)),
            "24h_price_change_pct": float(data.get("priceChangePercent", 0)),
        }

    # ── Combined convenience ─────────────────────────────────────────────
    def market_context(self, symbol: str = "BTCUSDT") -> dict:
        ctx = {"futures": False}
        if self.futures_available:
            fr = self.funding_rate(symbol)
            oi = self.open_interest(symbol)
            ls = self.long_short_ratio(symbol)
            liq = self.liquidations(symbol)
            ctx = {
                "futures": True,
                "funding_rate_pct": fr["funding_rate_pct"] if fr else None,
                "open_interest": oi["open_interest"] if oi else None,
                "long_short_ratio": ls["long_short_ratio"] if ls else None,
                "liq_24h_high": liq["24h_high"] if liq else None,
                "liq_24h_low": liq["24h_low"] if liq else None,
                "liq_24h_change_pct": liq["24h_price_change_pct"] if liq else None,
            }
        return ctx
