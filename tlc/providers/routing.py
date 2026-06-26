"""Asset-class classification + platform resolution (PRD §1.10).

Pure functions, no I/O — fully testable. The resolution order (most specific
wins) is:

    1. Explicit override   — a platform token/phrase on the request.
    2. Auto-route          — classify the symbol's asset class → routing table.
    3. Config default      — default_platform; else the first enabled platform.

If only one platform is enabled the router collapses to it (a TV-only user
fetches even forex from TradingView).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Words a user may type to force a platform → canonical platform key.
PLATFORM_ALIASES = {
    "mt5": "mt5", "mt": "mt5", "metatrader": "mt5", "metatrader5": "mt5",
    "broker": "mt5", "forex": "mt5",
    "tradingview": "tradingview", "tv": "tradingview", "tvremix": "tradingview",
    "remix": "tradingview",
}

_CURRENCIES = {
    "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD",
    "SEK", "NOK", "DKK", "SGD", "HKD", "ZAR", "MXN", "PLN", "TRY", "CNH",
}
_METALS = {"XAU", "XAG", "XPT", "XPD"}
_CRYPTO_BASES = {
    "BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "BNB", "LTC", "DOT", "AVAX",
    "LINK", "MATIC", "TRX", "BCH", "ATOM", "ETC", "XLM", "NEAR", "APT", "ARB",
    "OP", "SUI", "TON", "SHIB", "PEPE", "UNI", "AAVE",
}
_CRYPTO_QUOTES = {"USDT", "USDC", "USD", "BUSD", "DAI"}


def _strip_exchange(symbol: str) -> str:
    """Drop a TradingView exchange prefix, e.g. NASDAQ:AAPL → AAPL."""
    return symbol.split(":")[-1] if ":" in symbol else symbol


def classify_asset(symbol: str) -> str:
    """Best-effort asset class: forex | metals | crypto | stocks.

    Values match the `routing` table keys. Heuristic, not authoritative —
    `exchange_map` / explicit override exist for the cases this gets wrong.
    """
    s = _strip_exchange(str(symbol).strip().upper())

    # Metals (XAUUSD, XAGUSD, …) before forex so the USD quote doesn't shadow them.
    if s[:3] in _METALS:
        return "metals"

    # Crypto: explicit USDT/USDC quote, or a known crypto base vs a fiat/stable quote.
    if s.endswith("USDT") or s.endswith("USDC"):
        return "crypto"
    for q in sorted(_CRYPTO_QUOTES, key=len, reverse=True):
        if s.endswith(q) and s[: -len(q)] in _CRYPTO_BASES:
            return "crypto"

    # Forex: two known currency codes back to back (EURUSD, GBPJPY).
    if len(s) == 6 and s[:3] in _CURRENCIES and s[3:] in _CURRENCIES:
        return "forex"

    return "stocks"


def resolve_platform(
    symbol: str,
    config: Dict[str, Any],
    explicit: Optional[str] = None,
) -> str:
    """Resolve the platform a request should run on (see module docstring)."""
    enabled = config.get("enabled_platforms") or ["mt5"]

    # One platform enabled → collapse; nothing to switch to.
    if len(enabled) == 1:
        return enabled[0]

    # 1. Explicit override (only if that platform is actually enabled).
    if explicit:
        p = PLATFORM_ALIASES.get(str(explicit).strip().lower())
        if p and p in enabled:
            return p

    # 2. Auto-route by asset class.
    asset = classify_asset(symbol)
    routed = (config.get("routing") or {}).get(asset)
    if routed and routed in enabled:
        return routed

    # 3. Config default, else first enabled.
    default = config.get("default_platform")
    if default in enabled:
        return default
    return enabled[0]
