"""Data providers — the data-source seam (PRD §1.10).

A *platform* governs only where bars come from and how symbols are named.
Everything above the bars (legends, ballots, Chairman) is identical regardless
of platform. This mirrors the Sink seam (§1.9): one interface, swappable impls.

    Mt5Provider      — wraps the MBT MCP / MBT core (requires a running MT5 terminal)
    TvRemixProvider  — wraps the tvremix remote MCP (requires only an API key)

`routing` resolves which platform a request lands on (explicit → asset class →
default), and `get_provider` builds the matching provider from config.
"""

from .base import DataProvider, get_provider
from .routing import classify_asset, resolve_platform
from .mt5 import Mt5Provider
from .tvremix import TvRemixProvider

__all__ = [
    "DataProvider",
    "get_provider",
    "classify_asset",
    "resolve_platform",
    "Mt5Provider",
    "TvRemixProvider",
]
