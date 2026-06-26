"""Tests for the platform/data-provider layer (PRD §1.10).

Pure-Python: no MT5, no LLM, no network. The live tvremix fetch is exercised
separately (see scripts under scratchpad), not in the unit suite.
"""

import pytest

from tlc.market_packet import build_packet
from tlc.providers import Mt5Provider, TvRemixProvider, get_provider
from tlc.providers.routing import classify_asset, resolve_platform
from tlc.providers.tvremix import _normalize_bars, _fmt_time


# ---- asset classification ----------------------------------------------

@pytest.mark.parametrize("symbol,expected", [
    ("EURUSD", "forex"), ("eurusd", "forex"), ("GBPJPY", "forex"),
    ("XAUUSD", "metals"), ("XAGUSD", "metals"),
    ("BTCUSD", "crypto"), ("BTCUSDT", "crypto"), ("ETHUSDT", "crypto"),
    ("AAPL", "stocks"), ("TSLA", "stocks"), ("NVDA", "stocks"),
    ("NASDAQ:AAPL", "stocks"), ("BINANCE:BTCUSDT", "crypto"),
])
def test_classify_asset(symbol, expected):
    assert classify_asset(symbol) == expected


# ---- platform resolution order -----------------------------------------

def _cfg(enabled):
    return {
        "enabled_platforms": enabled,
        "default_platform": "mt5",
        "routing": {"forex": "mt5", "metals": "mt5", "stocks": "tradingview", "crypto": "tradingview"},
    }


def test_single_platform_collapses():
    cfg = _cfg(["tradingview"])
    # Even forex routes to the only enabled platform.
    assert resolve_platform("EURUSD", cfg) == "tradingview"
    assert resolve_platform("AAPL", cfg, explicit="mt5") == "tradingview"


def test_auto_route_by_asset_class():
    cfg = _cfg(["mt5", "tradingview"])
    assert resolve_platform("EURUSD", cfg) == "mt5"
    assert resolve_platform("AAPL", cfg) == "tradingview"
    assert resolve_platform("BTCUSD", cfg) == "tradingview"


def test_explicit_override_wins():
    cfg = _cfg(["mt5", "tradingview"])
    assert resolve_platform("EURUSD", cfg, explicit="tv") == "tradingview"
    assert resolve_platform("AAPL", cfg, explicit="mt5") == "mt5"
    # aliases
    assert resolve_platform("EURUSD", cfg, explicit="tradingview") == "tradingview"
    assert resolve_platform("EURUSD", cfg, explicit="metatrader") == "mt5"


def test_explicit_for_disabled_platform_falls_back():
    cfg = _cfg(["mt5"])  # tradingview not enabled
    # asks for tv but only mt5 enabled → collapses to mt5
    assert resolve_platform("AAPL", cfg, explicit="tv") == "mt5"


def test_default_when_no_route():
    cfg = _cfg(["mt5", "tradingview"])
    cfg["routing"] = {}  # nothing routes
    assert resolve_platform("AAPL", cfg) == "mt5"  # default_platform


# ---- symbol resolution per provider ------------------------------------

def test_mt5_symbol_suffix():
    p = Mt5Provider(suffix="zero")
    assert p.resolve_symbol("eurusd") == "EURUSDzero"
    # already-suffixed input is not doubled (case-insensitive guard)
    assert p.resolve_symbol("EURUSDzero").lower() == "eurusdzero"
    assert p.resolve_symbol("NASDAQ:AAPL") == "AAPLzero"    # strips TV prefix
    assert Mt5Provider(suffix="").resolve_symbol("eurusd") == "EURUSD"


def test_tvremix_symbol_resolution():
    p = TvRemixProvider(config={"exchange_map": {"AAPL": "NASDAQ:AAPL"}})
    assert p.resolve_symbol("AAPL") == "NASDAQ:AAPL"          # exchange_map override
    assert p.resolve_symbol("MSFT") == "MSFT"                 # bare stock
    assert p.resolve_symbol("BTCUSD") == "BINANCE:BTCUSDT"    # crypto prefix + quote
    assert p.resolve_symbol("ETHUSDT") == "BINANCE:ETHUSDT"
    assert p.resolve_symbol("EURUSD") == "FX_IDC:EURUSD"      # forex prefix
    assert p.resolve_symbol("FX_IDC:EURUSD") == "FX_IDC:EURUSD"  # already qualified


def test_get_provider_factory():
    cfg = {"platforms": {
        "mt5": {"provider": "mt5", "symbol_suffix": "zero"},
        "tradingview": {"provider": "tvremix", "endpoint": "https://x"},
    }}
    assert isinstance(get_provider("mt5", cfg), Mt5Provider)
    assert isinstance(get_provider("tradingview", cfg), TvRemixProvider)
    with pytest.raises(ValueError):
        get_provider("bogus", {"platforms": {"bogus": {"provider": "nope"}}})


# ---- tvremix bar normalization -----------------------------------------

def test_normalize_bars_epoch_to_newest_first():
    raw = {"bars": [
        {"time": 1000, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10},
        {"time": 2000, "open": 1.5, "high": 2.5, "low": 1, "close": 2.0, "volume": 20},
    ]}
    bars = _normalize_bars(raw)
    assert len(bars) == 2
    assert bars[0]["close"] == 2.0          # newest-first (2000 before 1000)
    assert bars[0]["time"] == _fmt_time(2000)
    assert set(bars[0]) == {"time", "open", "high", "low", "close", "volume"}


def test_fmt_time_handles_epoch_and_string():
    assert _fmt_time(0) == "1970-01-01 00:00"
    assert _fmt_time("2026-06-26 07:00") == "2026-06-26 07:00"


# ---- packet platform tag -----------------------------------------------

def test_packet_carries_platform():
    bars = [{"time": "t", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1},
            {"time": "t0", "open": 1, "high": 2, "low": 0.5, "close": 1.4, "volume": 1}]
    p = build_packet("BINANCE:BTCUSDT", "1h", {"1h": bars}, platform="tradingview")
    assert p["platform"] == "tradingview"
    # default stays neutral/empty when unspecified (back-compat)
    p2 = build_packet("EURUSD", "1h", {"1h": bars})
    assert p2["platform"] == ""
