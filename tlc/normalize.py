"""Forgiving input → canonical form.

Canonical timeframes match MBT's set exactly: 1m 5m 15m 30m 1h 4h 1d 1w.
Accept MT5 notation (M15, H1, D1, W1), suffix notation (15m, 1h), and a few
unambiguous bare numbers (15 → 15m, 60 → 1h).
"""

CANONICAL_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]

# MT5 letter+number style → canonical
_MT5_STYLE = {
    "m1": "1m", "m5": "5m", "m15": "15m", "m30": "30m",
    "h1": "1h", "h4": "4h", "d1": "1d", "w1": "1w",
}

# unambiguous bare numbers (minutes, plus common hour values)
_BARE = {
    "1": "1m", "5": "5m", "15": "15m", "30": "30m",
    "60": "1h", "240": "4h", "1440": "1d",
}


def canonical_timeframe(value: str) -> str:
    """Normalize a timeframe string to MBT canonical form. Raises ValueError."""
    if value is None:
        raise ValueError("timeframe is required")
    t = str(value).strip().lower()
    if t in CANONICAL_TIMEFRAMES:
        return t
    if t in _MT5_STYLE:
        return _MT5_STYLE[t]
    if t in _BARE:
        return _BARE[t]
    raise ValueError(
        f"unrecognized timeframe '{value}'. Use one of "
        f"{CANONICAL_TIMEFRAMES} (also accepts M15/H1/D1 style)."
    )


def canonical_symbol(value: str) -> str:
    """Normalize a symbol: strip, upper-case. Raises ValueError if empty."""
    if value is None or not str(value).strip():
        raise ValueError("symbol is required")
    return str(value).strip().upper()
