"""Pluggable, exception-isolated market context providers.

Every provider implements exactly ``fetch_context(symbol) -> dict``.  The
analytical core never imports a connector and never performs network I/O; the
imperative shell gathers providers and passes their plain output downstream.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class ContextProvider(Protocol):
    name: str
    required: bool

    @property
    def configured(self) -> bool:
        ...

    def fetch_context(self, symbol: str) -> dict:
        ...


@dataclass(frozen=True)
class CallableContextProvider:
    name: str
    fetcher: Callable[[str], dict]
    required: bool = True
    is_configured: bool = True

    @property
    def configured(self) -> bool:
        return self.is_configured

    def fetch_context(self, symbol: str) -> dict:
        result = self.fetcher(symbol)
        return result if isinstance(result, dict) else {"available": False}


@dataclass(frozen=True)
class CryptoDadaContextProvider:
    name: str = "cryptodada"
    required: bool = False

    @property
    def configured(self) -> bool:
        from data.sources.cryptodada_website import CryptoDadaConnector
        return CryptoDadaConnector().configured

    def fetch_context(self, symbol: str) -> dict:
        from data.sources.cryptodada_website import (CryptoDadaConnector,
                                                     summarize_cryptodada)
        return summarize_cryptodada(CryptoDadaConnector().fetch())


@dataclass(frozen=True)
class DiscordContextProvider:
    name: str = "discord"
    required: bool = False

    @property
    def configured(self) -> bool:
        from data.sources.discord_reader import DiscordReader
        return DiscordReader().can_read

    def fetch_context(self, symbol: str) -> dict:
        from data.sources.discord_reader import DiscordReader, summarize_discord
        reader = DiscordReader()
        return summarize_discord(reader.read_all(limit=50))


def collect_provider_context(providers: list[ContextProvider], symbol: str = "") -> dict:
    """Fetch configured providers in parallel and expose completeness honestly.

    A failed optional source can never prevent the remaining context or signal
    from being produced. Unconfigured optional providers are marked ``skipped``
    rather than counted as failed core context.
    """
    data: dict[str, dict] = {}
    status: dict[str, dict] = {}
    attempted: list[ContextProvider] = []

    for provider in providers:
        configured = bool(provider.configured)
        if not configured and not provider.required:
            status[provider.name] = {
                "available": False, "configured": False, "required": False,
                "status": "skipped",
            }
            data[provider.name] = {"available": False, "configured": False}
        else:
            attempted.append(provider)

    def _fetch(provider: ContextProvider) -> tuple[str, dict, str | None]:
        try:
            value = provider.fetch_context(symbol)
            return provider.name, value, None
        except Exception as exc:  # provider isolation is the central contract
            return provider.name, {"available": False}, f"{type(exc).__name__}: {exc}"

    if attempted:
        with ThreadPoolExecutor(max_workers=len(attempted)) as executor:
            futures = {executor.submit(_fetch, p): p for p in attempted}
            for future in as_completed(futures):
                provider = futures[future]
                name, value, error = future.result()
                explicit = value.get("available")
                available = bool(explicit if explicit is not None else value)
                data[name] = value
                status[name] = {
                    "available": available,
                    "configured": bool(provider.configured),
                    "required": bool(provider.required),
                    "status": "ok" if available else "failed",
                }
                if error:
                    status[name]["error"] = error

    required_names = [p.name for p in providers if p.required]
    configured_optional = [p.name for p in providers if not p.required and p.configured]
    expected = required_names + configured_optional
    available_names = [name for name in expected if status.get(name, {}).get("available")]
    missing = [name for name in expected if name not in available_names]
    ratio = len(available_names) / len(expected) if expected else 1.0
    return {
        "data": data,
        "providers": status,
        "context_completeness": {
            "available": len(available_names),
            "expected": len(expected),
            "ratio": round(ratio, 3),
            "label": "complete" if ratio == 1 else "partial" if ratio > 0 else "unavailable",
            "missing": missing,
            "optional_skipped": [name for name, st in status.items()
                                 if st.get("status") == "skipped"],
        },
    }
