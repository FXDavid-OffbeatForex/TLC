"""DataProvider interface + factory (PRD §1.10).

A provider has two jobs:
  - resolve_symbol: a user symbol (EURUSD, AAPL, BTCUSD) → the platform's native
    symbol (EURUSDzero, NASDAQ:AAPL, BINANCE:BTCUSDT).
  - fetch: pull canonical newest-first bars for (symbol, timeframe, count).

Bars are the exact shape the rest of TLC expects:
    {"time", "open", "high", "low", "close", "volume"}, NEWEST-FIRST.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class DataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def resolve_symbol(self, user_symbol: str) -> str:
        """User symbol → this platform's native symbol string."""

    @abstractmethod
    def fetch(self, symbol: str, timeframe: str, count: int = 200) -> List[dict]:
        """Newest-first canonical bars for the platform's native `symbol`."""

    def supports(self, user_symbol: str) -> bool:
        """Whether this provider can serve the symbol. Default: yes."""
        return True


def get_provider(platform: str, config: Optional[Dict[str, Any]] = None) -> DataProvider:
    """Build the provider for a resolved platform name from config.

    `platform` is a canonical platform key (e.g. "mt5", "tradingview"), not an
    alias — resolve aliases via routing.resolve_platform first.
    """
    config = config or {}
    spec = (config.get("platforms") or {}).get(platform, {})
    provider_kind = spec.get("provider", platform)

    # Imported here to avoid a circular import at module load.
    from .mt5 import Mt5Provider
    from .tvremix import TvRemixProvider

    if provider_kind == "mt5":
        return Mt5Provider(suffix=spec.get("symbol_suffix", ""), config=spec)
    if provider_kind == "tvremix":
        # Surface the top-level rate-limit budget + data dir into the provider so
        # its tvremix calls are guarded (§2.16). Absent rate_limits → guard off.
        tv_spec = dict(spec)
        rl = (config.get("rate_limits") or {}).get("tradingview")
        if rl is not None:
            tv_spec.setdefault("rate_limits", rl)
        tv_spec.setdefault("data_dir", config.get("data_dir", "data"))
        return TvRemixProvider(config=tv_spec)
    raise ValueError(f"unknown provider '{provider_kind}' for platform '{platform}'")
