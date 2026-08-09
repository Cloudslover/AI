"""Tradable symbol registry and aliases.

The engine can already analyse any Binance-style spot pair (for example
``BTCUSDT`` or ``SOLUSDT``).  This module adds a small, explicit watchlist and
friendly aliases so the CLI/dashboard can expose BTC, ETH and XAU/GOLD consistently
without hard-coding provider symbols in multiple places.

``XAUUSD``/``GOLD`` is routed to Binance spot ``PAXGUSDT`` candles (PAX Gold
tokenized spot gold).  Signals keep the user-facing asset as ``XAUUSD`` while
payloads also include provider metadata via ``market_context``.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class SymbolSpec:
    """Resolved tradable asset metadata.

    Attributes:
        symbol: Canonical/user-facing asset stored in signals and the DB.
        data_symbol: Provider symbol used to fetch OHLCV candles.
        label: Friendly display name for dashboard controls.
        market: High-level market bucket.
        provider: OHLCV provider name.
        futures_symbol: Binance USD-M futures symbol when futures context exists.
        aliases: Inputs that should resolve to this symbol.
        contract_size: Trading units per standard lot for sizing estimates.
        note: Extra explanation shown in degraded/non-futures context.
    """

    symbol: str
    data_symbol: str
    label: str
    market: str = "crypto"
    provider: str = "binance_spot"
    futures_symbol: str | None = None
    contract_size: float = 1.0
    aliases: tuple[str, ...] = ()
    note: str = ""

    @property
    def supports_futures(self) -> bool:
        return bool(self.futures_symbol)

    def as_choice(self) -> dict:
        """Small JSON/template-safe shape for UI watchlist controls."""
        return {
            "symbol": self.symbol,
            "data_symbol": self.data_symbol,
            "label": self.label,
            "market": self.market,
            "provider": self.provider,
            "futures": self.supports_futures,
            "contract_size": self.contract_size,
            "note": self.note,
        }


BUILTIN_SYMBOLS: dict[str, SymbolSpec] = {
    "BTCUSDT": SymbolSpec(
        symbol="BTCUSDT",
        data_symbol="BTCUSDT",
        label="Bitcoin / USDT",
        market="crypto",
        futures_symbol="BTCUSDT",
        aliases=("BTC", "BTCUSD", "BITCOIN"),
    ),
    "ETHUSDT": SymbolSpec(
        symbol="ETHUSDT",
        data_symbol="ETHUSDT",
        label="Ethereum / USDT",
        market="crypto",
        futures_symbol="ETHUSDT",
        aliases=("ETH", "TEH", "ETHUSD", "ETHEREUM"),
    ),
    "XAUUSD": SymbolSpec(
        symbol="XAUUSD",
        data_symbol="PAXGUSDT",
        label="Gold XAU/USD",
        market="gold",
        provider="binance_spot_proxy",
        futures_symbol=None,
        contract_size=100.0,
        aliases=("XAU", "GOLD", "GOLDUSD", "GOLDUSDT", "XAUUSDT", "PAXG", "PAXGUSDT"),
        note="XAUUSD/GOLD is analysed with Binance PAXGUSDT spot candles (PAX Gold proxy); futures/funding metrics are not available.",
    ),
}

DEFAULT_WATCHLIST: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "XAUUSD")


def _compact(value: str) -> str:
    """Uppercase and remove separators (ETH/USDT -> ETHUSDT)."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


_ALIAS_TO_SYMBOL: dict[str, str] = {}
for _symbol, _spec in BUILTIN_SYMBOLS.items():
    _ALIAS_TO_SYMBOL[_compact(_symbol)] = _symbol
    _ALIAS_TO_SYMBOL[_compact(_spec.data_symbol)] = _symbol
    for _alias in _spec.aliases:
        _ALIAS_TO_SYMBOL[_compact(_alias)] = _symbol


def normalize_symbol(value: str | None, *, default: str = "BTCUSDT") -> str:
    """Return the canonical user-facing symbol.

    Known aliases map to the built-ins (``ETH`` -> ``ETHUSDT``, ``GOLD`` /
    ``XAU`` / ``PAXGUSDT`` -> ``XAUUSD``).  Unknown bare tickers are treated as
    USDT pairs (``SOL`` -> ``SOLUSDT``) while explicit pairs pass through.
    """
    raw = _compact(value or default)
    if not raw:
        raw = _compact(default)
    if raw in _ALIAS_TO_SYMBOL:
        return _ALIAS_TO_SYMBOL[raw]
    if raw in BUILTIN_SYMBOLS:
        return raw
    # Friendly support for common crypto shorthand beyond the built-ins.
    if raw.isalpha() and not raw.endswith("USDT") and len(raw) <= 10:
        return f"{raw}USDT"
    return raw


def resolve_symbol(value: str | None, *, default: str = "BTCUSDT") -> SymbolSpec:
    """Resolve user input into a provider-aware symbol spec.

    Unknown symbols are assumed to be Binance spot/USDT symbols so the existing
    engine behaviour remains backwards-compatible.
    """
    canonical = normalize_symbol(value, default=default)
    if canonical in BUILTIN_SYMBOLS:
        return BUILTIN_SYMBOLS[canonical]
    return SymbolSpec(
        symbol=canonical,
        data_symbol=canonical,
        label=canonical,
        market="crypto",
        provider="binance_spot",
        futures_symbol=canonical if canonical.endswith("USDT") else None,
    )


def parse_symbol_list(value: str | Iterable[str] | None,
                      *, default: Iterable[str] = DEFAULT_WATCHLIST) -> list[str]:
    """Parse a comma/list watchlist into canonical symbols without duplicates."""
    if value is None:
        raw_items = list(default)
    elif isinstance(value, str):
        raw_items = [x.strip() for x in value.split(",")]
    else:
        raw_items = list(value)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if not str(item).strip():
            continue
        sym = normalize_symbol(str(item))
        if sym not in seen:
            out.append(sym)
            seen.add(sym)
    if not out:
        out = [normalize_symbol(x) for x in default]
    return out


def symbol_choices(symbols: Iterable[str] | None = None) -> list[dict]:
    """Return UI-friendly choices for the configured watchlist."""
    return [resolve_symbol(sym).as_choice()
            for sym in parse_symbol_list(symbols if symbols is not None else DEFAULT_WATCHLIST)]
