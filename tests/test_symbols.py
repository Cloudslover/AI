"""Tests for BTC / ETH / XAUUSD symbol aliasing and data routing."""
from __future__ import annotations

from data.binance_client import BinanceClient
from data.symbols import normalize_symbol, parse_symbol_list, resolve_symbol, symbol_choices


def test_symbol_aliases_normalize():
    assert normalize_symbol("BTC") == "BTCUSDT"
    assert normalize_symbol("ETH") == "ETHUSDT"
    assert normalize_symbol("TEH") == "ETHUSDT"  # common typo from the user prompt
    assert normalize_symbol("eth/usd") == "ETHUSDT"
    assert normalize_symbol("GOLD") == "XAUUSD"
    assert normalize_symbol("xau") == "XAUUSD"
    assert normalize_symbol("xauusd") == "XAUUSD"
    assert normalize_symbol("goldusdt") == "XAUUSD"
    assert normalize_symbol("PAXGUSDT") == "XAUUSD"
    assert normalize_symbol("sol") == "SOLUSDT"


def test_parse_watchlist_dedupes_and_exposes_choices():
    watchlist = parse_symbol_list("BTC,ETH,GOLD,XAUUSD,ETHUSDT")
    assert watchlist == ["BTCUSDT", "ETHUSDT", "XAUUSD"]
    choices = symbol_choices(watchlist)
    assert [c["symbol"] for c in choices] == ["BTCUSDT", "ETHUSDT", "XAUUSD"]
    assert choices[2]["data_symbol"] == "PAXGUSDT"
    assert choices[2]["futures"] is False
    assert choices[2]["contract_size"] == 100.0


def test_resolve_xauusd_uses_paxg_spot_proxy():
    spec = resolve_symbol("GOLD")
    assert spec.symbol == "XAUUSD"
    assert spec.data_symbol == "PAXGUSDT"
    assert spec.market == "gold"
    assert spec.futures_symbol is None
    assert spec.contract_size == 100.0
    assert "PAXGUSDT" in spec.note


def test_binance_klines_routes_xau_alias_to_paxg(monkeypatch):
    calls = []

    def fake_get_first_host(self, hosts, path, params, timeout=None, retries=None):
        calls.append({"hosts": hosts, "path": path, "params": dict(params)})
        return [[
            1_780_000_000_000,
            "2000.0", "2010.0", "1990.0", "2005.0", "12.5",
            1_780_000_900_000, "0", 1, "0", "0", "0",
        ]]

    monkeypatch.setattr(BinanceClient, "_get_first_host", fake_get_first_host)
    df = BinanceClient().klines("XAU", "15m", 1)

    assert calls[0]["path"] == "/api/v3/klines"
    assert calls[0]["params"]["symbol"] == "PAXGUSDT"
    assert df.attrs["symbol"] == "XAUUSD"
    assert df.attrs["data_symbol"] == "PAXGUSDT"
    assert float(df.iloc[0].close) == 2005.0


def test_xauusd_market_context_skips_futures_probe(monkeypatch):
    def fail_if_called(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("XAUUSD should not call futures endpoints")

    monkeypatch.setattr(BinanceClient, "_get_first_host", fail_if_called)
    ctx = BinanceClient().market_context("GOLD")
    assert ctx["symbol"] == "XAUUSD"
    assert ctx["data_symbol"] == "PAXGUSDT"
    assert ctx["futures"] is False
    assert "PAXGUSDT" in ctx["note"]
