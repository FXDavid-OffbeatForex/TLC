"""Mt5Provider — bars from MetaTrader 5 via the MBT toolkit (PRD §1.10).

Symbol resolution applies the broker's suffix quirk (EURUSD → EURUSDzero).

`fetch` is platform I/O:
  - In the PUBLIC on-demand path, the coding agent fetches bars itself by calling
    the MBT MCP tool `mcp__MBT__get_ohlcv` — Python cannot call an MCP tool, so
    this method is not used there.
  - On a VPS / headless run, MBT's own core (`core.ohlcv.fetch_recent`) is used,
    which needs the MetaTrader5 package (the embedded pyembed Python under Wine).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..normalize import canonical_symbol
from .base import DataProvider


class Mt5Provider(DataProvider):
    name = "mt5"

    def __init__(self, suffix: str = "", config: Optional[Dict[str, Any]] = None):
        self.suffix = suffix or ""
        self.config = config or {}

    def resolve_symbol(self, user_symbol: str) -> str:
        s = canonical_symbol(user_symbol)
        if ":" in s:                       # tolerate a TV-style prefix, strip it
            s = s.split(":")[-1]
        if self.suffix and not s.lower().endswith(self.suffix.lower()):
            return s + self.suffix
        return s

    def fetch(self, symbol: str, timeframe: str, count: int = 200) -> List[dict]:
        # Headless path: defer to MBT core (needs the MetaTrader5 package).
        try:
            from core.ohlcv import fetch_recent  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on MBT + MT5 env
            raise NotImplementedError(
                "MT5 bars are fetched by the agent via the MBT MCP tool "
                "`mcp__MBT__get_ohlcv` in the public path, or by MBT core "
                "(`core.ohlcv.fetch_recent`) on a VPS with the MetaTrader5 package. "
                f"MBT core not importable here: {exc}"
            ) from exc
        return fetch_recent(symbol, timeframe, count)  # pragma: no cover
