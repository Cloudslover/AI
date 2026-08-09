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
from data.symbols import resolve_symbol

TIMEFRAME_TO_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "6h": 21_600_000, "12h": 43_200_000, "1d": 86_400_000, "1w": 604_800_000,
}

TIMEOUT = 8
_RETRIES = 1
FUT_TIMEOUT = 5
FUT_RETRIES = 0
_CONTEXT_TTL = 60  # seconds to cache market_context


class BinanceClient:
    def __init__(self, timeout: int = TIMEOUT, retries: int = _RETRIES):
        self.timeout = timeout
        self.retries = retries
        # Thread-local sessions so parallel timeframe fetches are safe.
        self._local = threading.local()
        self._futures_ok: Optional[bool] = None  # None = not yet tested
        self._futures_checked_at: float = 0.0
        self._context_cache: dict[str, tuple[float, dict]] = {}

    @property
    def session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({"User-Agent": "cryptobrain/1.0"})
            self._local.session = s
        return s

    def _get(self, host: str, path: str, params: dict,
             timeout: Optional[int] = None, retries: Optional[int] = None) -> Optional[dict]:
        timeout = timeout or self.timeout
        retries = retries or self.retries
        for attempt in range(retries + 1):
            try:
                r = self.session.get(f"{host}{path}", params=params, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (451, 403, 429):
                    return None  # geo-block / rate-limit — not retryable
            except requests.RequestException:
                pass
            time.sleep(0.3 * (attempt + 1))
        return None

    def _get_first_host(self, hosts: list[str], path: str, params: dict,
                        timeout: Optional[int] = None,
                        retries: Optional[int] = None) -> Optional[dict]:
        for host in hosts:
            data = self._get(host, path, params, timeout=timeout, retries=retries)
            if data is not None:
                return data
        return None

    # ── OHLCV ────────────────────────────────────────────────────────────
    def klines(self, symbol: str = "BTCUSDT", timeframe: str = "15m",
               limit: int = 500, start_time: Optional[int] = None,
               end_time: Optional[int] = None) -> pd.DataFrame:
        """Fetch OHLCV candles.

        ``start_time`` / ``end_time`` are optional Unix timestamps in
        milliseconds.  They let the paper-trading runner resume from its last
        inspected candle instead of repeatedly treating all historical data as
        new.  The returned frame retains the standard columns ``ts, open,
        high, low, close, volume``.
        """
        spec = resolve_symbol(symbol)
        params = {"symbol": spec.data_symbol, "interval": timeframe, "limit": min(max(1, int(limit)), 1000)}
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        data = self._get_first_host(BINANCE_HOSTS, "/api/v3/klines", params)
        if data is None:
            raise ConnectionError(
                f"Could not fetch klines for {spec.symbol} ({spec.data_symbol}) {timeframe} — "
                f"check network or try a Binance-accessible location."
            )
        df = pd.DataFrame(data, columns=[
            "ts", "open", "high", "low", "close", "volume",
            "close_ts", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore",
        ])
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)
        out = df[["ts", "open", "high", "low", "close", "volume"]].astype({"ts": "int64"})
        out.attrs["symbol"] = spec.symbol
        out.attrs["data_symbol"] = spec.data_symbol
        out.attrs["market"] = spec.market
        out.attrs["provider"] = spec.provider
        return out

    # ── Futures (optional; may geo-block) ────────────────────────────────
    def _futures_pair(self, symbol: str) -> Optional[str]:
        """Return the Binance USD-M futures pair for a user-facing symbol.

        XAUUSD/GOLD uses PAXGUSDT spot candles as a proxy and has no
        futures/funding context in this project, so futures methods return
        None immediately.
        """
        return resolve_symbol(symbol).futures_symbol

    @property
    def futures_available(self) -> bool:
        now = time.time()
        # Cache the availability probe for 60s and NEVER block more than ~5s.
        if self._futures_ok is None or now - self._futures_checked_at > 60:
            self._futures_ok = self._get_first_host(
                BINANCE_FUTURES_HOSTS, "/fapi/v1/ping", {},
                timeout=FUT_TIMEOUT, retries=FUT_RETRIES) is not None
            self._futures_checked_at = now
        return self._futures_ok

    def funding_rate(self, symbol: str = "BTCUSDT") -> Optional[dict]:
        """Current (last) funding rate for the USDT-margined future."""
        fut_symbol = self._futures_pair(symbol)
        if not fut_symbol or not self.futures_available:
            return None
        data = self._get_first_host(BINANCE_FUTURES_HOSTS, "/fapi/v1/premiumIndex",
                                    {"symbol": fut_symbol}, timeout=FUT_TIMEOUT, retries=FUT_RETRIES)
        if not data:
            return None
        return {
            "funding_rate_pct": round(float(data.get("lastFundingRate", 0)) * 100, 4),
            "mark_price": float(data.get("markPrice", 0)),
            "time": data.get("time"),
        }

    def open_interest(self, symbol: str = "BTCUSDT") -> Optional[dict]:
        fut_symbol = self._futures_pair(symbol)
        if not fut_symbol or not self.futures_available:
            return None
        data = self._get_first_host(BINANCE_FUTURES_HOSTS, "/fapi/v1/openInterest",
                                    {"symbol": fut_symbol}, timeout=FUT_TIMEOUT, retries=FUT_RETRIES)
        if not data:
            return None
        return {"open_interest": float(data.get("openInterest", 0))}

    def long_short_ratio(self, symbol: str = "BTCUSDT", period: str = "5m",
                         limit: int = 1) -> Optional[dict]:
        fut_symbol = self._futures_pair(symbol)
        if not fut_symbol or not self.futures_available:
            return None
        data = self._get_first_host(
            BINANCE_FUTURES_HOSTS, "/futures/data/globalLongShortAccountRatio",
            {"symbol": fut_symbol, "period": period, "limit": limit},
            timeout=FUT_TIMEOUT, retries=FUT_RETRIES)
        if not data:
            return None
        latest = data[-1] if isinstance(data, list) and data else data
        return {"long_short_ratio": float(latest.get("longShortRatio", 0))}

    def liquidations(self, symbol: str = "BTCUSDT") -> Optional[dict]:
        """Recent forced-liquidations snapshot (via allForceOrders is heavy, so
        we use the public 24h stats + the top longs/shorts as a proxy)."""
        fut_symbol = self._futures_pair(symbol)
        if not fut_symbol or not self.futures_available:
            return None
        data = self._get_first_host(BINANCE_FUTURES_HOSTS, "/fapi/v1/ticker/24hr",
                                    {"symbol": fut_symbol}, timeout=FUT_TIMEOUT, retries=FUT_RETRIES)
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
        """Futures/provider context, cached per symbol.

        Crypto pairs such as BTCUSDT and ETHUSDT include optional Binance
        futures fields when the network permits. XAUUSD/GOLD is routed to
        PAXGUSDT spot candles and explicitly reports that futures context is
        not available rather than looking geo-blocked.
        """
        spec = resolve_symbol(symbol)
        now = time.time()
        hit = self._context_cache.get(spec.symbol)
        if hit and now - hit[0] < _CONTEXT_TTL:
            return hit[1]

        ctx = {
            "symbol": spec.symbol,
            "data_symbol": spec.data_symbol,
            "market": spec.market,
            "provider": spec.provider,
            "futures": False,
            "note": spec.note or "futures unreachable from this network",
        }
        if spec.futures_symbol and self.futures_available:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=4) as ex:
                fr = ex.submit(self.funding_rate, spec.symbol)
                oi = ex.submit(self.open_interest, spec.symbol)
                ls = ex.submit(self.long_short_ratio, spec.symbol)
                liq = ex.submit(self.liquidations, spec.symbol)
                # .exception() instead of .result(): a failing future must never
                # re-raise and kill the whole scan.
                def _safe(fut):
                    try:
                        if fut.exception():
                            return None
                        return fut.result()
                    except Exception:
                        return None
                fr, oi, ls, liq = (_safe(f) for f in (fr, oi, ls, liq))
            ctx.update({
                "futures": True,
                "note": "futures context available",
                "futures_symbol": spec.futures_symbol,
                "funding_rate_pct": fr["funding_rate_pct"] if fr else None,
                "open_interest": oi["open_interest"] if oi else None,
                "long_short_ratio": ls["long_short_ratio"] if ls else None,
                "liq_24h_high": liq["24h_high"] if liq else None,
                "liq_24h_low": liq["24h_low"] if liq else None,
                "liq_24h_change_pct": liq["24h_price_change_pct"] if liq else None,
            })
        elif spec.futures_symbol:
            ctx["note"] = "futures unreachable from this network"
        self._context_cache[spec.symbol] = (now, ctx)
        return ctx
